"""Message and thread repository."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.orm import Session

from datetime import datetime, timedelta, timezone

from local_agent.agent.models import ConversationPreview
from local_agent.agent.system_prompt import (
    is_turn_context_system_message,
    patch_persona_in_system_content,
)
from local_agent.agent.thread_config import ThreadConfig
from local_agent.storage.fts import like_terms, prepare_fts5_query, should_try_like_fallback
from local_agent.storage.models import CanvasRow, MessageRow, ThreadRow, utcnow
from local_agent.storage.serializer import MessageSerializer


DISPLAY_ROLES = ("user", "assistant", "tool")


def _truncate_preview(text: str, max_len: int = 48) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 1] + "…"


def _rows_before_anchor(query, anchor: MessageRow):
    """Stable keyset cursor: skip rows at or after anchor (created_at, id)."""
    return query.where(
        or_(
            MessageRow.created_at < anchor.created_at,
            and_(
                MessageRow.created_at == anchor.created_at,
                MessageRow.id < anchor.id,
            ),
        )
    )


class ThreadRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, agent_id: str, title: str | None = None) -> ThreadRow:
        thread_id = str(uuid.uuid4())
        now = utcnow()
        row = ThreadRow(
            id=thread_id,
            agent_id=agent_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def get(self, thread_id: str) -> ThreadRow | None:
        return self.session.get(ThreadRow, thread_id)

    def list_by_agent(self, agent_id: str) -> list[ThreadRow]:
        last_msg = (
            select(
                MessageRow.thread_id.label("thread_id"),
                func.max(MessageRow.created_at).label("last_msg_at"),
            )
            .group_by(MessageRow.thread_id)
            .subquery()
        )
        activity = func.coalesce(last_msg.c.last_msg_at, ThreadRow.updated_at)
        return list(
            self.session.scalars(
                select(ThreadRow)
                .outerjoin(last_msg, ThreadRow.id == last_msg.c.thread_id)
                .where(ThreadRow.agent_id == agent_id)
                .order_by(activity.desc(), ThreadRow.created_at.desc())
            ).all()
        )

    def touch(self, thread_id: str) -> None:
        row = self.session.get(ThreadRow, thread_id)
        if row:
            row.updated_at = utcnow()
            self.session.commit()

    def update_title(self, thread_id: str, title: str) -> None:
        row = self.session.get(ThreadRow, thread_id)
        if row:
            row.title = title
            row.updated_at = utcnow()
            self.session.commit()

    def get_config(self, thread_id: str) -> ThreadConfig:
        row = self.session.get(ThreadRow, thread_id)
        if not row:
            return ThreadConfig()
        return ThreadConfig.from_json(row.config_override)

    def update_config(self, thread_id: str, config: ThreadConfig) -> ThreadConfig:
        row = self.session.get(ThreadRow, thread_id)
        if not row:
            raise KeyError(f"Thread not found: {thread_id}")
        row.config_override = config.to_json() or None
        if config.title:
            row.title = config.title
        row.updated_at = utcnow()
        self.session.commit()
        return config

    def delete(self, thread_id: str) -> bool:
        row = self.session.get(ThreadRow, thread_id)
        if not row:
            return False
        self.session.execute(delete(MessageRow).where(MessageRow.thread_id == thread_id))
        self.session.execute(
            text("DELETE FROM messages_fts WHERE thread_id = :tid"),
            {"tid": thread_id},
        )
        self.session.execute(delete(CanvasRow).where(CanvasRow.thread_id == thread_id))
        self.session.delete(row)
        self.session.commit()
        return True


class MessageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_messages(self, thread_id: str, messages: list[dict]) -> None:
        existing_rows = list(
            self.session.scalars(
                select(MessageRow)
                .where(MessageRow.thread_id == thread_id)
                .order_by(MessageRow.created_at, MessageRow.id)
            ).all()
        )
        self.session.execute(delete(MessageRow).where(MessageRow.thread_id == thread_id))
        self.session.execute(
            text("DELETE FROM messages_fts WHERE thread_id = :tid"),
            {"tid": thread_id},
        )

        preserve_ids = len(messages) >= len(existing_rows)
        base = datetime.now(timezone.utc)

        for i, msg in enumerate(messages):
            row_id = (
                existing_rows[i].id
                if preserve_ids and i < len(existing_rows)
                else None
            )
            # Millisecond steps keep ordering unique even when OS clock resolution is coarse.
            created_at = (base + timedelta(milliseconds=i)).isoformat()

            row = MessageSerializer.to_db(
                thread_id, msg, msg_id=row_id, created_at=created_at
            )
            self.session.add(row)
            fts_content = msg.get("content") or msg.get("thinking")
            if fts_content:
                self.session.execute(
                    text(
                        "INSERT INTO messages_fts(message_id, thread_id, content) "
                        "VALUES (:mid, :tid, :content)"
                    ),
                    {"mid": row.id, "tid": thread_id, "content": fts_content},
                )
        thread = self.session.get(ThreadRow, thread_id)
        if thread:
            thread.updated_at = utcnow()
        self.session.commit()

    def append_message(self, thread_id: str, message: dict) -> MessageRow:
        row = MessageSerializer.to_db(thread_id, message)
        self.session.add(row)
        if message.get("content"):
            self.session.execute(
                text(
                    "INSERT INTO messages_fts(message_id, thread_id, content) "
                    "VALUES (:mid, :tid, :content)"
                ),
                {"mid": row.id, "tid": thread_id, "content": message["content"]},
            )
        self.session.commit()
        return row

    def load_messages(self, thread_id: str) -> list[dict]:
        rows = self.session.scalars(
            select(MessageRow)
            .where(MessageRow.thread_id == thread_id)
            .order_by(MessageRow.created_at, MessageRow.id)
        ).all()
        return [MessageSerializer.from_db(r) for r in rows]

    def patch_base_system_persona(self, thread_id: str, persona_prompt: str) -> bool:
        """Update the base system message persona for an existing conversation."""
        messages = self.load_messages(thread_id)
        if not messages:
            return False
        patched = False
        for msg in messages:
            if msg.get("role") != "system":
                continue
            content = msg.get("content")
            if not isinstance(content, str) or is_turn_context_system_message(content):
                continue
            msg["content"] = patch_persona_in_system_content(content, persona_prompt)
            patched = True
            break
        if patched:
            self.save_messages(thread_id, messages)
        return patched

    def count_messages(self, thread_id: str) -> int:
        from sqlalchemy import func

        return int(
            self.session.scalar(
                select(func.count())
                .select_from(MessageRow)
                .where(MessageRow.thread_id == thread_id)
            )
            or 0
        )

    def _paginate_rows(
        self,
        query,
        *,
        limit: int,
    ) -> tuple[list[MessageRow], bool]:
        rows = list(
            self.session.scalars(
                query.order_by(
                    MessageRow.created_at.desc(), MessageRow.id.desc()
                ).limit(limit + 1)
            ).all()
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        page.reverse()
        return page, has_more

    def _rows_to_api_messages(self, rows: list[MessageRow]) -> list[dict]:
        messages = [MessageSerializer.from_db(r) for r in rows]
        return [self._message_for_api(m, r) for m, r in zip(messages, rows)]

    def load_messages_page(
        self,
        thread_id: str,
        *,
        limit: int = 30,
        before_id: str | None = None,
    ) -> tuple[list[dict], bool]:
        """Return a page of messages (oldest-first) and whether older messages exist."""
        limit = max(1, min(limit, 100))
        query = select(MessageRow).where(MessageRow.thread_id == thread_id)

        if before_id:
            anchor = self.session.get(MessageRow, before_id)
            if anchor and anchor.thread_id == thread_id:
                query = _rows_before_anchor(query, anchor)

        page, has_more = self._paginate_rows(query, limit=limit)
        return self._rows_to_api_messages(page), has_more

    def load_latest_messages(
        self,
        thread_id: str,
        *,
        limit: int = 30,
    ) -> tuple[list[dict], bool]:
        """Return the most recent messages (oldest-first within the page)."""
        limit = max(1, min(limit, 100))
        query = select(MessageRow).where(MessageRow.thread_id == thread_id)
        page, has_more = self._paginate_rows(query, limit=limit)
        return self._rows_to_api_messages(page), has_more

    def load_visible_messages_page(
        self,
        thread_id: str,
        *,
        limit: int = 50,
        before_id: str | None = None,
    ) -> tuple[list[dict], bool]:
        """Paginate user/assistant/tool messages only (oldest-first within page)."""
        limit = max(1, min(limit, 100))
        query = select(MessageRow).where(
            MessageRow.thread_id == thread_id,
            MessageRow.role.in_(DISPLAY_ROLES),
        )

        if before_id:
            anchor = self.session.get(MessageRow, before_id)
            if anchor and anchor.thread_id == thread_id:
                query = _rows_before_anchor(query, anchor)

        page, has_more = self._paginate_rows(query, limit=limit)
        return self._rows_to_api_messages(page), has_more

    def load_latest_visible_messages(
        self,
        thread_id: str,
        *,
        limit: int = 50,
    ) -> tuple[list[dict], bool]:
        """Return the most recent visible messages (oldest-first within the page)."""
        limit = max(1, min(limit, 100))
        query = select(MessageRow).where(
            MessageRow.thread_id == thread_id,
            MessageRow.role.in_(DISPLAY_ROLES),
        )
        page, has_more = self._paginate_rows(query, limit=limit)
        return self._rows_to_api_messages(page), has_more

    @staticmethod
    def _message_for_api(msg: dict, row: MessageRow) -> dict:
        enriched = dict(msg)
        enriched["id"] = row.id
        enriched["created_at"] = row.created_at
        return enriched

    def get_thread_preview(self, thread_id: str) -> ConversationPreview:
        rows = self.session.scalars(
            select(MessageRow)
            .where(MessageRow.thread_id == thread_id)
            .order_by(MessageRow.created_at, MessageRow.id)
        ).all()
        if not rows:
            return ConversationPreview.empty()

        preview = "（暂无对话）"
        turn_count = 0
        last_active: datetime | None = None

        for row in rows:
            if row.created_at:
                last_active = datetime.fromisoformat(row.created_at)
            if row.role != "user" or not row.content:
                continue
            turn_count += 1
            if preview == "（暂无对话）":
                preview = _truncate_preview(row.content)

        return ConversationPreview(
            preview=preview,
            turn_count=turn_count,
            last_active=last_active,
        )

    def search(self, query: str, thread_id: str | None = None, limit: int = 10) -> list[dict]:
        q = (query or "").strip()
        if not q:
            return []

        message_ids: list[str] = []
        fts_query = prepare_fts5_query(q)
        if fts_query is not None:
            sql = (
                "SELECT m.id FROM messages m "
                "JOIN messages_fts fts ON m.id = fts.message_id "
                "WHERE messages_fts MATCH :query"
            )
            params: dict = {"query": fts_query, "limit": limit}
            if thread_id:
                sql += " AND m.thread_id = :thread_id"
                params["thread_id"] = thread_id
            sql += " ORDER BY rank LIMIT :limit"
            rows = self.session.execute(text(sql), params).fetchall()
            message_ids = [r[0] for r in rows if r[0]]

        if should_try_like_fallback(q, len(message_ids)):
            message_ids = self._search_messages_like(q, thread_id, limit)

        results = []
        for message_id in message_ids:
            msg_row = self.session.get(MessageRow, message_id)
            if msg_row:
                results.append(MessageSerializer.from_db(msg_row))
        return results

    def _search_messages_like(
        self, query: str, thread_id: str | None, limit: int
    ) -> list[str]:
        terms = like_terms(query)
        if not terms:
            return []
        sql = (
            "SELECT id FROM messages WHERE "
            "COALESCE(content, thinking) IS NOT NULL"
        )
        params: dict = {"limit": limit}
        if thread_id:
            sql += " AND thread_id = :thread_id"
            params["thread_id"] = thread_id
        for i, term in enumerate(terms):
            key = f"p{i}"
            sql += f" AND COALESCE(content, thinking) LIKE :{key}"
            params[key] = f"%{term}%"
        sql += " ORDER BY created_at DESC LIMIT :limit"
        rows = self.session.execute(text(sql), params).fetchall()
        return [r[0] for r in rows if r[0]]

    def export_json(self, thread_id: str) -> str:
        messages = self.load_messages(thread_id)
        return json.dumps(MessageSerializer.to_json_export(messages), ensure_ascii=False, indent=2)

    def import_json(self, thread_id: str, data: str) -> int:
        messages = json.loads(data)
        self.save_messages(thread_id, messages)
        return len(messages)

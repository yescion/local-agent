"""Memory atoms and scenarios repository."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from local_agent.storage.fts import like_terms, prepare_fts5_query, should_try_like_fallback
from local_agent.storage.models import MemoryAtomRow, MemoryScenarioRow, utcnow


class MemoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_atom(
        self,
        agent_id: str,
        atom_type: str,
        content: str,
        confidence: float = 0.8,
        thread_id: str | None = None,
        source_message_ids: list[str] | None = None,
    ) -> MemoryAtomRow:
        atom_id = str(uuid.uuid4())
        row = MemoryAtomRow(
            id=atom_id,
            agent_id=agent_id,
            thread_id=thread_id,
            type=atom_type,
            content=content,
            confidence=confidence,
            source_message_ids=json.dumps(source_message_ids or [], ensure_ascii=False),
            created_at=utcnow(),
        )
        self.session.add(row)
        self.session.execute(
            text("INSERT INTO atoms_fts(atom_id, agent_id, content) VALUES (:aid, :agid, :content)"),
            {"aid": atom_id, "agid": agent_id, "content": content},
        )
        self.session.commit()
        return row

    def list_atoms(self, agent_id: str, limit: int = 100) -> list[MemoryAtomRow]:
        return list(
            self.session.scalars(
                select(MemoryAtomRow)
                .where(MemoryAtomRow.agent_id == agent_id)
                .order_by(MemoryAtomRow.created_at.desc())
                .limit(limit)
            ).all()
        )

    def search_atoms(self, agent_id: str, query: str, limit: int = 8) -> list[MemoryAtomRow]:
        q = (query or "").strip()
        if not q:
            return []

        atom_ids: list[str] = []
        fts_query = prepare_fts5_query(q)
        if fts_query is not None:
            rows = self.session.execute(
                text(
                    "SELECT a.id FROM memory_atoms a "
                    "JOIN atoms_fts fts ON a.id = fts.atom_id "
                    "WHERE atoms_fts MATCH :query AND a.agent_id = :agent_id "
                    "ORDER BY rank LIMIT :limit"
                ),
                {"query": fts_query, "agent_id": agent_id, "limit": limit},
            ).fetchall()
            atom_ids = [r[0] for r in rows if r[0]]

        if should_try_like_fallback(q, len(atom_ids)):
            atom_ids = self._search_atoms_like(agent_id, q, limit)

        return [self.session.get(MemoryAtomRow, atom_id) for atom_id in atom_ids if atom_id]

    def _search_atoms_like(self, agent_id: str, query: str, limit: int) -> list[str]:
        terms = like_terms(query)
        if not terms:
            return []
        sql = "SELECT id FROM memory_atoms WHERE agent_id = :agent_id"
        params: dict = {"agent_id": agent_id, "limit": limit}
        for i, term in enumerate(terms):
            key = f"p{i}"
            sql += f" AND content LIKE :{key}"
            params[key] = f"%{term}%"
        sql += " ORDER BY created_at DESC LIMIT :limit"
        rows = self.session.execute(text(sql), params).fetchall()
        return [r[0] for r in rows if r[0]]

    def add_scenario(
        self,
        agent_id: str,
        title: str,
        summary: str,
        atom_ids: list[str],
        md_path: str | None = None,
    ) -> MemoryScenarioRow:
        scenario_id = str(uuid.uuid4())
        now = utcnow()
        row = MemoryScenarioRow(
            id=scenario_id,
            agent_id=agent_id,
            title=title,
            summary=summary,
            atom_ids=json.dumps(atom_ids, ensure_ascii=False),
            md_path=md_path,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def list_scenarios(self, agent_id: str) -> list[MemoryScenarioRow]:
        return list(
            self.session.scalars(
                select(MemoryScenarioRow)
                .where(MemoryScenarioRow.agent_id == agent_id)
                .order_by(MemoryScenarioRow.updated_at.desc())
            ).all()
        )

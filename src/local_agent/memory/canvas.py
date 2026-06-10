"""Mermaid task canvas management."""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_agent.storage.models import CanvasRow, utcnow


class CanvasManager:
    def __init__(self, session: Session, canvas_dir: Path, max_tokens: int = 1500) -> None:
        self.session = session
        self.canvas_dir = canvas_dir
        self.max_tokens = max_tokens
        self.canvas_dir.mkdir(parents=True, exist_ok=True)

    def get_canvas(self, thread_id: str) -> str:
        rows = list(
            self.session.scalars(
                select(CanvasRow).where(CanvasRow.thread_id == thread_id)
            ).all()
        )
        if not rows:
            return self._default_canvas()
        return rows[-1].mermaid_content

    def add_node(self, thread_id: str, label: str, node_id: str | None = None) -> str:
        node_id = node_id or f"n_{uuid.uuid4().hex[:6]}"
        current = self.get_canvas(thread_id)
        if "graph TD" not in current:
            current = self._default_canvas()
        new_line = f'    {node_id}["{label}"]'
        if "graph TD" in current:
            lines = current.strip().split("\n")
            lines.append(new_line)
            updated = "\n".join(lines)
        else:
            updated = current + f"\n{new_line}"
        self._save(thread_id, updated)
        return node_id

    def to_context_message(self, thread_id: str) -> dict | None:
        canvas = self.get_canvas(thread_id)
        if not canvas or canvas == self._default_canvas():
            return None
        tokens = len(canvas) // 4
        if tokens > self.max_tokens:
            canvas = canvas[: self.max_tokens * 4] + "\n...[canvas truncated]"
        return {
            "role": "system",
            "content": f"## Task Canvas (Mermaid)\n```mermaid\n{canvas}\n```",
        }

    def _save(self, thread_id: str, content: str) -> None:
        canvas_id = str(uuid.uuid4())
        row = CanvasRow(
            id=canvas_id,
            thread_id=thread_id,
            mermaid_content=content,
            updated_at=utcnow(),
        )
        self.session.add(row)
        self.session.commit()
        path = self.canvas_dir / f"{thread_id}.mmd"
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _default_canvas() -> str:
        return "graph TD\n    start[\"对话开始\"]"

"""Agent repository."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_agent.agent.models import AgentInstance, Persona
from local_agent.storage.models import AgentRow, utcnow


class AgentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        name: str,
        persona: Persona,
        skills: list[str] | None = None,
        llm_override: dict | None = None,
        memory_scope: str = "agent",
        active_skill_id: str | None = None,
        active_skill_content: str | None = None,
    ) -> AgentInstance:
        agent_id = str(uuid.uuid4())
        now = utcnow()
        row = AgentRow(
            id=agent_id,
            name=name,
            persona=persona.model_dump_json(),
            skills=json.dumps(skills or [], ensure_ascii=False),
            active_skill_id=active_skill_id,
            active_skill_content=active_skill_content,
            llm_override=json.dumps(llm_override) if llm_override else None,
            memory_scope=memory_scope,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self.session.commit()
        return self._to_model(row)

    def get(self, agent_id: str) -> AgentInstance | None:
        row = self.session.get(AgentRow, agent_id)
        return self._to_model(row) if row else None

    def list_all(self) -> list[AgentInstance]:
        rows = self.session.scalars(select(AgentRow).order_by(AgentRow.created_at.desc())).all()
        return [self._to_model(r) for r in rows]

    def delete(self, agent_id: str) -> bool:
        row = self.session.get(AgentRow, agent_id)
        if not row:
            return False
        self.session.delete(row)
        self.session.commit()
        return True

    def update_active_skill(
        self, agent_id: str, skill_id: str | None, content: str | None
    ) -> None:
        row = self.session.get(AgentRow, agent_id)
        if not row:
            return
        row.active_skill_id = skill_id
        row.active_skill_content = content
        row.updated_at = utcnow()
        self.session.commit()

    def update_skills(self, agent_id: str, skills: list[str]) -> None:
        row = self.session.get(AgentRow, agent_id)
        if not row:
            return
        row.skills = json.dumps(skills, ensure_ascii=False)
        row.updated_at = utcnow()
        self.session.commit()

    def update_persona(self, agent_id: str, persona: Persona) -> None:
        row = self.session.get(AgentRow, agent_id)
        if not row:
            return
        row.persona = persona.model_dump_json()
        row.updated_at = utcnow()
        self.session.commit()

    def update_name(self, agent_id: str, name: str) -> None:
        row = self.session.get(AgentRow, agent_id)
        if not row:
            return
        row.name = name
        row.updated_at = utcnow()
        self.session.commit()

    def _to_model(self, row: AgentRow) -> AgentInstance:
        return AgentInstance(
            id=row.id,
            name=row.name,
            persona=Persona.model_validate_json(row.persona),
            skills=json.loads(row.skills),
            active_skill_id=row.active_skill_id,
            active_skill_content=row.active_skill_content or "",
            llm_override=json.loads(row.llm_override) if row.llm_override else None,
            memory_scope=row.memory_scope,
            created_at=datetime.fromisoformat(row.created_at),
            updated_at=datetime.fromisoformat(row.updated_at),
        )

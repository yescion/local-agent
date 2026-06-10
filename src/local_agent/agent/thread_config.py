"""Per-thread session configuration overrides."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from local_agent.agent.models import Persona


class ThreadConfig(BaseModel):
    """Session-level overrides; null fields inherit from the parent agent."""

    title: str | None = None
    persona: Persona | None = None
    skills: list[str] | None = None
    llm_override: dict | None = None

    @classmethod
    def from_json(cls, raw: str | None) -> ThreadConfig:
        if not raw:
            return cls()
        try:
            return cls.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            return cls()

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=True)

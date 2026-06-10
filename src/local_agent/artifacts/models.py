"""Artifact domain models."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class Artifact(BaseModel):
    """A file produced during an agent conversation."""

    id: str
    agent_id: str
    thread_id: str
    name: str
    path: Path
    tool_name: str | None = None
    description: str | None = None
    size_bytes: int | None = None
    created_at: datetime


class ArtifactSummary(BaseModel):
    """Aggregate artifact info for list views."""

    count: int = 0
    names: list[str] = Field(default_factory=list)

    @classmethod
    def empty(cls) -> ArtifactSummary:
        return cls()

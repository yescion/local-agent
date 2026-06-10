"""Skill metadata models."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class SkillMetadata(BaseModel):
    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    enabled: bool = True
    execution: Literal["host", "sandbox"] = "host"
    path: Path
    content: str = ""

    def summary_line(self) -> str:
        suffix = " [沙盒执行]" if self.execution == "sandbox" else ""
        return f"{self.id}: {self.description or self.name}{suffix}"

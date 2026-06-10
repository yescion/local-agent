"""Agent domain models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Persona(BaseModel):
    role: str = "通用 AI 助手"
    tone: str = "简洁专业"
    constraints: list[str] = Field(default_factory=list)
    custom_instructions: str = ""

    def to_system_prompt(self) -> str:
        lines = [
            f"你是{self.role}。",
            f"语气风格：{self.tone}。",
            "思考过程（thinking）请使用中文，与回复语言保持一致。",
        ]
        if self.constraints:
            lines.append("约束：")
            lines.extend(f"- {c}" for c in self.constraints)
        if self.custom_instructions:
            lines.append(self.custom_instructions)
        return "\n".join(lines)


class AgentInstance(BaseModel):
    id: str
    name: str
    persona: Persona
    skills: list[str] = Field(default_factory=list)
    active_skill_id: str | None = None
    active_skill_content: str = ""
    llm_override: dict | None = None
    memory_scope: str = "agent"
    created_at: datetime
    updated_at: datetime


class ConversationPreview(BaseModel):
    """Agent 最近会话的对话摘要，用于列表展示。"""

    preview: str = "（暂无对话）"
    turn_count: int = 0
    last_active: datetime | None = None

    @classmethod
    def empty(cls) -> ConversationPreview:
        return cls()

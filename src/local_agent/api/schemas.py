"""API Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from local_agent.agent.thread_config import ThreadConfig


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


class PersonaSchema(BaseModel):
    role: str = "通用 AI 助手"
    tone: str = "简洁专业"
    constraints: list[str] = Field(default_factory=list)
    custom_instructions: str = ""


class CreateAgentRequest(BaseModel):
    name: str
    persona: PersonaSchema = Field(default_factory=PersonaSchema)
    skills: list[str] = Field(default_factory=list)
    llm_override: dict[str, Any] | None = None


class UpdateAgentRequest(BaseModel):
    name: str | None = None
    persona: PersonaSchema | None = None
    skills: list[str] | None = None
    llm_override: dict[str, Any] | None = None


class AgentResponse(BaseModel):
    id: str
    name: str
    persona: PersonaSchema
    skills: list[str]
    active_skill_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ThreadSummaryResponse(BaseModel):
    id: str
    agent_id: str
    agent_name: str | None = None
    title: str | None
    preview: str
    turn_count: int
    artifact_count: int
    artifact_names: list[str] = Field(default_factory=list)
    last_active: str | None = None
    updated_at: str
    created_at: str


class CreateThreadRequest(BaseModel):
    title: str | None = None


class ThreadConfigRequest(BaseModel):
    title: str | None = None
    persona: PersonaSchema | None = None
    skills: list[str] | None = None
    llm_override: dict[str, Any] | None = None


class ThreadConfigResponse(ThreadConfig):
    pass


class ThreadConfigDetailResponse(BaseModel):
    """Session overrides plus inherited Agent defaults and system preset prompts."""

    title: str | None = None
    persona: PersonaSchema | None = None
    skills: list[str] | None = None
    llm_override: dict[str, Any] | None = None

    agent_id: str
    agent_name: str
    agent_defaults: PersonaSchema
    agent_skills: list[str] = Field(default_factory=list)
    effective_persona: PersonaSchema
    effective_skills: list[str] | None = None
    effective_skill_ids: list[str] = Field(default_factory=list)
    has_persona_override: bool = False
    has_skills_override: bool = False
    system_directives: list[str] = Field(default_factory=list)
    system_prompt_preview: str = ""


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str | None = None
    thinking: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    created_at: str | None = None


class MessagesPageResponse(BaseModel):
    messages: list[MessageResponse]
    has_more: bool


class ChatRequest(BaseModel):
    message: str = ""
    thread_id: str | None = None
    stream: bool = True
    attachment_ids: list[str] = Field(default_factory=list)
    reference_ids: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    content: str
    thread_id: str


class SkillResponse(BaseModel):
    id: str
    name: str
    description: str
    version: str
    enabled: bool
    tools: list[str] = Field(default_factory=list)
    path: str | None = None


class SkillDetailResponse(SkillResponse):
    markdown: str = ""
    source: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    execution: str = "host"


class ArtifactResponse(BaseModel):
    id: str
    agent_id: str
    thread_id: str
    name: str
    path: str
    tool_name: str | None = None
    description: str | None = None
    size_bytes: int | None = None
    created_at: datetime
    preview_kind: str | None = None


class ConfigUpdateRequest(BaseModel):
    path: str
    value: Any


class ConfigBatchUpdateRequest(BaseModel):
    updates: list[ConfigUpdateRequest] = Field(default_factory=list)


class JobSummaryResponse(BaseModel):
    id: str
    name: str
    enabled: bool
    schedule_type: str
    cron_expression: str | None = None
    at_time: str | None = None
    interval_minutes: int | None = None
    action_type: str
    action_payload: dict[str, Any] = Field(default_factory=dict)
    agent_id: str | None = None
    thread_id: str | None = None
    max_runs: int | None = None
    run_count: int = 0
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    timeout_secs: int = 300


class JobRunResponse(BaseModel):
    id: str
    status: str
    started_at: str
    finished_at: str | None = None
    output: str | None = None
    error: str | None = None


class JobRunsResponse(BaseModel):
    job_id: str
    job_name: str
    runs: list[JobRunResponse] = Field(default_factory=list)

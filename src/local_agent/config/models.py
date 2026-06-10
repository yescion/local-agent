"""Pydantic configuration models."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ArtifactsConfig(BaseModel):
    enabled: bool = True
    subdir: str = "artifacts"


class AppConfig(BaseModel):
    data_dir: Path = Path("./data")
    log_level: str = "INFO"
    artifacts: ArtifactsConfig = Field(default_factory=ArtifactsConfig)


class LLMConfig(BaseModel):
    provider: str = "litellm"
    model: str = "gpt-4o-mini"
    api_base: str | None = None
    api_key: str | None = None
    temperature: float = 0.7
    max_tokens: int = 8192
    timeout: int = 120
    stream: bool = True
    debug: bool = False
    debug_log: Path = Path("./data/logs/litellm.log")


class AgentConfig(BaseModel):
    max_tool_rounds: int = 50
    context_window: int = 128000
    context_reserve: int = 8000
    system_prompt_template: str | None = None


class ShortTermMemoryConfig(BaseModel):
    offload_enabled: bool = True
    offload_threshold_tokens: int = 64000
    canvas_enabled: bool = True
    canvas_max_tokens: int = 8000


class LongTermMemoryConfig(BaseModel):
    extraction_enabled: bool = True
    aggregation_interval: int = 10
    persona_update_interval: int = 50


class RetrievalConfig(BaseModel):
    top_k: int = 8
    use_vector: bool = False
    use_bm25: bool = True
    rrf_k: int = 60
    auto_inject: bool = True
    auto_inject_top_k: int = 5
    auto_inject_min_query_chars: int = 2


class MemoryConfig(BaseModel):
    enabled: bool = True
    compact_mode: Literal["simple", "full"] = "full"
    compact_threshold: int = 100000
    compact_split_ratio: float = 0.7
    short_term: ShortTermMemoryConfig = Field(default_factory=ShortTermMemoryConfig)
    long_term: LongTermMemoryConfig = Field(default_factory=LongTermMemoryConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)


class SkillsConfig(BaseModel):
    directories: list[Path] = Field(
        default_factory=lambda: [Path("./skills/_builtin"), Path("./skills/custom")]
    )
    # 子目录名黑名单：mx-skills 为妙想脚本实现，仅 mx_finance 包装技能对 Agent 可见
    exclude_dir_names: list[str] = Field(default_factory=lambda: ["mx-skills"])
    auto_reload: bool = True


class StorageConfig(BaseModel):
    sqlite_path: Path = Path("./data/agent.db")
    enable_wal: bool = True


class BackgroundLoopConfig(BaseModel):
    enabled: bool = True
    default_interval_mins: int = 10
    sleep_slice_secs: int = 1


class JobSchedulerConfig(BaseModel):
    """宿主机定时任务调度器（SQLite 持久化）。"""

    enabled: bool = True
    poll_interval_secs: int = 30
    max_concurrent_jobs: int = 3
    default_timeout_secs: int = 300


class APIConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8080
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


class MxSkillsConfig(BaseModel):
    """东方财富妙想 (MiaoXiang) 金融技能包配置。"""

    enabled: bool = True
    skills_root: Path = Path("./skills/custom/mx-skills")
    output_dir: Path = Path("./data/miaoxiang")
    quota_file: Path = Path("./data/mx_skills_quota.json")
    daily_limit: int = 50
    api_key: str | None = None


class ToolsConfig(BaseModel):
    shell_enabled: bool = False
    write_paths: list[Path] = Field(default_factory=lambda: [Path("./data")])


class DaytonaSandboxConfig(BaseModel):
    """Daytona 沙盒连接与创建参数（参见 https://www.daytona.io/docs/en/python-sdk/）。"""

    enabled: bool = True
    api_key: str | None = None
    api_url: str | None = None
    target: str | None = None
    language: Literal["python", "typescript", "javascript"] = "python"
    snapshot: str | None = None
    image: str | None = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    auto_stop_interval: int = 5
    ephemeral: bool = True
    create_timeout: float = 60.0
    exec_timeout: int = 120
    max_output_chars: int = 100_000
    auto_cleanup_on_turn_end: bool = True
    cleanup_action: Literal["delete", "stop"] = "delete"


class Settings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    background_loop: BackgroundLoopConfig = Field(default_factory=BackgroundLoopConfig)
    jobs: JobSchedulerConfig = Field(default_factory=JobSchedulerConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    mx_skills: MxSkillsConfig = Field(default_factory=MxSkillsConfig)
    daytona: DaytonaSandboxConfig = Field(default_factory=DaytonaSandboxConfig)

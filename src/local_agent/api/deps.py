"""FastAPI dependency injection."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from local_agent.agent.manager import AgentManager
from local_agent.cli.context import get_manager, get_settings, reload_settings
from local_agent.config.loader import load_settings, save_settings
from local_agent.config.models import Settings
from local_agent.jobs.service import JobService, get_job_service


def get_agent_manager() -> AgentManager:
    return get_manager()


def get_app_settings() -> Settings:
    return get_settings()


def get_config_path() -> Path:
    import os

    return Path(os.environ.get("LOCAL_AGENT_CONFIG", "config/default.yaml"))


def reload_app_settings() -> Settings:
    reload_settings()
    return get_settings()


def persist_settings(settings: Settings) -> None:
    save_settings(settings, get_config_path())
    reload_settings()


def get_job_scheduler() -> JobService:
    return get_job_service()

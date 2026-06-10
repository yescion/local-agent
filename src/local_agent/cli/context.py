"""Shared CLI context (settings, DB, manager)."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from local_agent.agent.manager import AgentManager
from local_agent.config.loader import load_settings
from local_agent.config.models import Settings
from local_agent.jobs.service import configure_job_scheduler, stop_job_scheduler
from local_agent.skills.registry import SkillRegistry
from local_agent.storage.database import get_engine, get_session_factory as make_session_factory, init_db
from local_agent.tools.router import ToolRouter

_settings: Settings | None = None
_session_factory: sessionmaker[Session] | None = None
_manager: AgentManager | None = None


def _ensure_init() -> None:
    global _settings, _session_factory, _manager
    if _settings is None:
        _settings = load_settings()
        engine = get_engine(_settings.storage.sqlite_path, _settings.storage.enable_wal)
        init_db(engine)
        _session_factory = make_session_factory(engine)
        _manager = AgentManager(_settings, _session_factory)
        _settings.app.data_dir.mkdir(parents=True, exist_ok=True)
        configure_job_scheduler(_settings, _session_factory, get_manager)


def get_settings() -> Settings:
    _ensure_init()
    assert _settings is not None
    return _settings


def reload_settings() -> None:
    global _settings
    _settings = load_settings()


def get_session_factory() -> sessionmaker[Session]:
    _ensure_init()
    assert _session_factory is not None
    return _session_factory


def get_session() -> Session:
    return get_session_factory()()


def get_manager() -> AgentManager:
    _ensure_init()
    assert _manager is not None
    return _manager


def get_skill_registry() -> SkillRegistry:
    session = get_session()
    tool_router = ToolRouter()
    settings = get_settings()
    registry = SkillRegistry(
        directories=settings.skills.directories,
        tool_router=tool_router,
        session=session,
        exclude_dir_names=settings.skills.exclude_dir_names,
    )
    registry.scan_directories()
    return registry

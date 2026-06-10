"""Skills API routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from local_agent.agent.manager import AgentManager
from local_agent.api.deps import get_agent_manager
from local_agent.api.schemas import SkillDetailResponse, SkillResponse
from local_agent.cli.context import get_session, get_settings
from local_agent.skills.registry import SkillRegistry
from local_agent.tools.router import ToolRouter

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


def _build_registry() -> SkillRegistry:
    session = get_session()
    settings = get_settings()
    registry = SkillRegistry(
        directories=settings.skills.directories,
        tool_router=ToolRouter(),
        session=session,
        exclude_dir_names=settings.skills.exclude_dir_names,
    )
    registry.scan_directories()
    return registry


def _to_response(meta) -> SkillResponse:
    return SkillResponse(
        id=meta.id,
        name=meta.name,
        description=meta.description,
        version=meta.version,
        enabled=meta.enabled,
        tools=list(meta.tools),
        path=str(meta.path),
    )


@router.get("", response_model=list[SkillResponse])
def list_skills():
    registry = _build_registry()
    return [_to_response(s) for s in registry.list_skills(enabled_only=False)]


@router.post("/scan", response_model=dict)
def scan_skills(manager: AgentManager = Depends(get_agent_manager)):
    count = manager.reload_skills()
    return {"scanned": count}


@router.post("/register", response_model=SkillResponse)
def register_skill(path: str, manager: AgentManager = Depends(get_agent_manager)):
    skill_path = Path(path)
    if not skill_path.exists():
        raise HTTPException(404, f"Skill path not found: {path}")
    session = get_session()
    settings = get_settings()
    try:
        registry = SkillRegistry(
            directories=settings.skills.directories,
            tool_router=ToolRouter(),
            session=session,
            exclude_dir_names=settings.skills.exclude_dir_names,
        )
        meta = registry.register(skill_path)
        manager.reload_skills()
        return _to_response(meta)
    finally:
        session.close()


def _skill_detail_response(registry: SkillRegistry, skill_id: str) -> SkillDetailResponse:
    meta = registry.get_skill(skill_id)
    if not meta:
        raise HTTPException(404, "Skill not found")
    try:
        source = meta.path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(500, f"Failed to read skill file: {exc}") from exc
    return SkillDetailResponse(
        id=meta.id,
        name=meta.name,
        description=meta.description,
        version=meta.version,
        enabled=meta.enabled,
        tools=list(meta.tools),
        path=str(meta.path),
        markdown=meta.content,
        source=source,
        author=meta.author,
        tags=list(meta.tags),
        execution=meta.execution,
    )


@router.get("/detail/{skill_id}", response_model=SkillDetailResponse)
def get_skill_detail(skill_id: str):
    registry = _build_registry()
    return _skill_detail_response(registry, skill_id)


@router.get("/{skill_id}", response_model=SkillDetailResponse)
def get_skill(skill_id: str):
    registry = _build_registry()
    return _skill_detail_response(registry, skill_id)


@router.delete("/{skill_id}", status_code=204)
def unregister_skill(skill_id: str, manager: AgentManager = Depends(get_agent_manager)):
    session = get_session()
    settings = get_settings()
    try:
        registry = SkillRegistry(
            directories=settings.skills.directories,
            tool_router=ToolRouter(),
            session=session,
            exclude_dir_names=settings.skills.exclude_dir_names,
        )
        registry.scan_directories()
        if not registry.get_skill(skill_id):
            raise HTTPException(404, "Skill not found")
        registry.unregister(skill_id)
        manager.reload_skills()
    finally:
        session.close()

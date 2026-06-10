"""User attachment upload API."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from local_agent.agent.manager import AgentManager
from local_agent.api.artifact_preview import preview_kind
from local_agent.api.deps import get_agent_manager
from local_agent.api.schemas import ArtifactResponse
from local_agent.artifacts.manager import ArtifactManager
from local_agent.cli.context import get_session

router = APIRouter(prefix="/api/v1", tags=["uploads"])


def _to_response(artifact) -> ArtifactResponse:
    path_str = str(artifact.path)
    return ArtifactResponse(
        id=artifact.id,
        agent_id=artifact.agent_id,
        thread_id=artifact.thread_id,
        name=artifact.name,
        path=path_str,
        tool_name=artifact.tool_name,
        description=artifact.description,
        size_bytes=artifact.size_bytes,
        created_at=artifact.created_at,
        preview_kind=preview_kind(Path(path_str)),
    )


@router.post("/threads/{thread_id}/uploads", response_model=ArtifactResponse)
async def upload_thread_attachment(
    thread_id: str,
    file: UploadFile = File(...),
    manager: AgentManager = Depends(get_agent_manager),
):
    thread = manager.get_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Thread not found")

    if not manager.settings.app.artifacts.enabled:
        raise HTTPException(400, "会话文件/附件功能未启用")

    filename = file.filename or "upload"
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")

    session = get_session()
    try:
        artifact_manager = ArtifactManager(session, manager.artifacts_dir)
        try:
            artifact = artifact_manager.save_user_upload(
                thread.agent_id, thread_id, filename, data
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return _to_response(artifact)
    finally:
        session.close()

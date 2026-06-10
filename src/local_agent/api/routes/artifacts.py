"""Artifact API routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from local_agent.agent.manager import AgentManager
from local_agent.api.artifact_preview import build_preview, preview_kind
from local_agent.api.deps import get_agent_manager
from local_agent.api.schemas import ArtifactResponse
from local_agent.cli.context import get_session
from local_agent.storage.repositories.artifact_repo import ArtifactRepository

router = APIRouter(prefix="/api/v1", tags=["artifacts"])


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


@router.get("/threads/{thread_id}/artifacts", response_model=list[ArtifactResponse])
def list_thread_artifacts(
    thread_id: str, manager: AgentManager = Depends(get_agent_manager)
):
    if not manager.get_thread(thread_id):
        raise HTTPException(404, "Thread not found")
    artifacts = manager.list_artifacts("", thread_id=thread_id)
    return [_to_response(a) for a in artifacts]


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: str):
    session = get_session()
    try:
        artifact = ArtifactRepository(session).get(artifact_id)
        if not artifact:
            raise HTTPException(404, "Artifact not found")
        return _to_response(artifact)
    finally:
        session.close()


@router.get("/artifacts/{artifact_id}/preview")
def preview_artifact(artifact_id: str):
    session = get_session()
    try:
        artifact = ArtifactRepository(session).get(artifact_id)
        if not artifact:
            raise HTTPException(404, "Artifact not found")
        return build_preview(Path(artifact.path))
    finally:
        session.close()


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str):
    session = get_session()
    try:
        artifact = ArtifactRepository(session).get(artifact_id)
        if not artifact:
            raise HTTPException(404, "Artifact not found")
        path = Path(artifact.path)
        if not path.is_file():
            raise HTTPException(404, "File not found on disk")
        return FileResponse(path, filename=artifact.name)
    finally:
        session.close()

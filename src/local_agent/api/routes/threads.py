"""Thread (session) API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from local_agent.agent.manager import AgentManager
from local_agent.agent.models import Persona
from local_agent.agent.thread_config import ThreadConfig
from local_agent.api.deps import get_agent_manager, get_job_scheduler
from local_agent.api.schemas import (
    CreateThreadRequest,
    JobRunResponse,
    JobRunsResponse,
    JobSummaryResponse,
    MessageResponse,
    MessagesPageResponse,
    ThreadConfigDetailResponse,
    ThreadConfigRequest,
    ThreadConfigResponse,
    ThreadSummaryResponse,
)
from local_agent.cli.context import get_session
from local_agent.jobs.service import JobService
from local_agent.storage.repositories.message_repo import MessageRepository, ThreadRepository

router = APIRouter(prefix="/api/v1", tags=["threads"])


def _thread_summary(
    thread,
    preview,
    artifact_count: int,
    artifact_names: list[str] | None = None,
    *,
    agent_name: str | None = None,
) -> ThreadSummaryResponse:
    last_active = (
        preview.last_active.isoformat()
        if preview.last_active
        else thread.updated_at
    )
    return ThreadSummaryResponse(
        id=thread.id,
        agent_id=thread.agent_id,
        agent_name=agent_name,
        title=thread.title,
        preview=preview.preview,
        turn_count=preview.turn_count,
        artifact_count=artifact_count,
        artifact_names=artifact_names or [],
        last_active=last_active,
        updated_at=thread.updated_at,
        created_at=thread.created_at,
    )


@router.get("/threads", response_model=list[ThreadSummaryResponse])
def list_all_threads(manager: AgentManager = Depends(get_agent_manager)):
    rows = manager.list_all_threads_with_preview()
    return [
        _thread_summary(t, p, c, names, agent_name=agent_name)
        for t, p, c, names, agent_name in rows
    ]


@router.get("/agents/{agent_id}/threads", response_model=list[ThreadSummaryResponse])
def list_threads(agent_id: str, manager: AgentManager = Depends(get_agent_manager)):
    if not manager.get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    agent = manager.get_agent(agent_id)
    rows = manager.list_threads_with_preview(agent_id)
    return [
        _thread_summary(t, p, c, names, agent_name=agent.name if agent else None)
        for t, p, c, names in rows
    ]


@router.post("/agents/{agent_id}/threads", response_model=ThreadSummaryResponse, status_code=201)
def create_thread(
    agent_id: str,
    body: CreateThreadRequest,
    manager: AgentManager = Depends(get_agent_manager),
):
    if not manager.get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    thread = manager.create_thread(agent_id, title=body.title or "新会话")
    from local_agent.agent.models import ConversationPreview

    return _thread_summary(thread, ConversationPreview.empty(), 0, [])


@router.get("/threads/{thread_id}", response_model=ThreadSummaryResponse)
def get_thread(thread_id: str, manager: AgentManager = Depends(get_agent_manager)):
    thread = manager.get_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Thread not found")
    preview = manager.get_thread_preview(thread_id)
    summary = manager.get_artifact_summary(thread_id=thread_id)
    agent = manager.get_agent(thread.agent_id)
    return _thread_summary(
        thread,
        preview,
        summary.count,
        summary.names,
        agent_name=agent.name if agent else None,
    )


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: str, manager: AgentManager = Depends(get_agent_manager)):
    if not manager.delete_thread(thread_id):
        raise HTTPException(404, "Thread not found")


@router.get("/threads/{thread_id}/messages", response_model=MessagesPageResponse)
def get_messages(
    thread_id: str,
    limit: int = Query(30, ge=1, le=100),
    before_id: str | None = None,
    manager: AgentManager = Depends(get_agent_manager),
):
    if not manager.get_thread(thread_id):
        raise HTTPException(404, "Thread not found")
    session = get_session()
    try:
        repo = MessageRepository(session)
        if before_id:
            messages, has_more = repo.load_visible_messages_page(
                thread_id, limit=limit, before_id=before_id
            )
        else:
            messages, has_more = repo.load_latest_visible_messages(
                thread_id, limit=limit
            )
        return MessagesPageResponse(
            messages=[MessageResponse.model_validate(m) for m in messages],
            has_more=has_more,
        )
    finally:
        session.close()


@router.get("/threads/{thread_id}/config", response_model=ThreadConfigDetailResponse)
def get_thread_config(
    thread_id: str, manager: AgentManager = Depends(get_agent_manager)
):
    if not manager.get_thread(thread_id):
        raise HTTPException(404, "Thread not found")
    try:
        return ThreadConfigDetailResponse.model_validate(
            manager.get_thread_config_detail(thread_id)
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/threads/{thread_id}/config", response_model=ThreadConfigResponse)
def update_thread_config(
    thread_id: str,
    body: ThreadConfigRequest,
    manager: AgentManager = Depends(get_agent_manager),
):
    if not manager.get_thread(thread_id):
        raise HTTPException(404, "Thread not found")
    config = ThreadConfig(
        title=body.title,
        persona=(
            Persona.model_validate(body.persona.model_dump()) if body.persona else None
        ),
        skills=body.skills,
        llm_override=body.llm_override,
    )
    updated = manager.update_thread_config(thread_id, config)
    return ThreadConfigResponse.model_validate(updated.model_dump())


@router.get("/threads/{thread_id}/jobs", response_model=list[JobSummaryResponse])
def list_thread_jobs(
    thread_id: str,
    manager: AgentManager = Depends(get_agent_manager),
    job_service: JobService = Depends(get_job_scheduler),
):
    if not manager.get_thread(thread_id):
        raise HTTPException(404, "Thread not found")
    jobs = job_service.list_jobs_for_thread(thread_id)
    return [JobSummaryResponse.model_validate(j) for j in jobs]


@router.get("/threads/{thread_id}/jobs/{job_id}/runs", response_model=JobRunsResponse)
def get_thread_job_runs(
    thread_id: str,
    job_id: str,
    limit: int = Query(10, ge=1, le=50),
    manager: AgentManager = Depends(get_agent_manager),
    job_service: JobService = Depends(get_job_scheduler),
):
    if not manager.get_thread(thread_id):
        raise HTTPException(404, "Thread not found")
    session = get_session()
    try:
        from local_agent.storage.repositories.job_repo import JobRepository

        job = JobRepository(session).get(job_id)
        if not job or job.thread_id != thread_id:
            raise HTTPException(404, "Job not found")
        runs = job_service.get_job_runs(job_id, limit=limit)
        return JobRunsResponse(
            job_id=job.id,
            job_name=job.name,
            runs=[JobRunResponse.model_validate(r) for r in runs],
        )
    finally:
        session.close()

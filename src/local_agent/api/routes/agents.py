"""Agent API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from local_agent.agent.manager import AgentManager
from local_agent.agent.models import Persona
from local_agent.api.deps import get_agent_manager
from local_agent.api.schemas import (
    AgentResponse,
    CreateAgentRequest,
    PersonaSchema,
    UpdateAgentRequest,
)
from local_agent.storage.repositories.agent_repo import AgentRepository
from local_agent.cli.context import get_session

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _to_response(agent) -> AgentResponse:
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        persona=PersonaSchema.model_validate(agent.persona.model_dump()),
        skills=agent.skills,
        active_skill_id=agent.active_skill_id,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


@router.get("", response_model=list[AgentResponse])
def list_agents(manager: AgentManager = Depends(get_agent_manager)):
    return [_to_response(a) for a in manager.list_agents()]


@router.post("", response_model=AgentResponse, status_code=201)
def create_agent(
    body: CreateAgentRequest,
    manager: AgentManager = Depends(get_agent_manager),
):
    agent = manager.create_agent(
        name=body.name,
        persona=Persona.model_validate(body.persona.model_dump()),
        skills=body.skills,
        llm_override=body.llm_override,
    )
    return _to_response(agent)


@router.get("/default", response_model=AgentResponse)
def get_default_agent(manager: AgentManager = Depends(get_agent_manager)):
    agent = manager.resolve_default_agent()
    if not agent:
        raise HTTPException(404, "No agent found")
    return _to_response(agent)


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: str, manager: AgentManager = Depends(get_agent_manager)):
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return _to_response(agent)


@router.patch("/{agent_id}", response_model=AgentResponse)
def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    manager: AgentManager = Depends(get_agent_manager),
):
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    session = get_session()
    try:
        repo = AgentRepository(session)
        if body.name is not None:
            repo.update_name(agent_id, body.name)
        if body.persona is not None:
            repo.update_persona(
                agent_id, Persona.model_validate(body.persona.model_dump())
            )
        if body.skills is not None:
            repo.update_skills(agent_id, body.skills)
        updated = repo.get(agent_id)
        return _to_response(updated)
    finally:
        session.close()


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: str, manager: AgentManager = Depends(get_agent_manager)):
    if not manager.delete_agent(agent_id):
        raise HTTPException(404, "Agent not found")

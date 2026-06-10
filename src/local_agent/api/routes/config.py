"""Global configuration API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from local_agent.api.config_utils import settings_to_api
from local_agent.api.deps import get_app_settings, get_config_path, persist_settings
from local_agent.api.schemas import ConfigBatchUpdateRequest, ConfigUpdateRequest
from local_agent.config.models import Settings

router = APIRouter(prefix="/api/v1/config", tags=["config"])


def _set_nested(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


@router.get("")
def get_config(settings: Settings = Depends(get_app_settings)):
    return {
        "path": str(get_config_path()),
        "settings": settings_to_api(settings),
    }


@router.put("")
def update_config(
    body: ConfigUpdateRequest,
    settings: Settings = Depends(get_app_settings),
):
    data = settings.model_dump()
    _set_nested(data, body.path, body.value)
    try:
        updated = Settings.model_validate(data)
    except Exception as exc:
        raise HTTPException(400, f"Invalid config: {exc}") from exc
    persist_settings(updated)
    return {"path": str(get_config_path()), "settings": settings_to_api(updated)}


@router.patch("")
def batch_update_config(
    body: ConfigBatchUpdateRequest,
    settings: Settings = Depends(get_app_settings),
):
    data = settings.model_dump()
    for item in body.updates:
        _set_nested(data, item.path, item.value)
    try:
        updated = Settings.model_validate(data)
    except Exception as exc:
        raise HTTPException(400, f"Invalid config: {exc}") from exc
    persist_settings(updated)
    return {"path": str(get_config_path()), "settings": settings_to_api(updated)}

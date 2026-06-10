"""Config serialization helpers for API responses."""

from __future__ import annotations

from typing import Any

from local_agent.config.models import Settings

_SENSITIVE_KEYS = frozenset(
    {"api_key", "secret", "password", "token", "credential"}
)


def mask_secrets(data: Any) -> Any:
    if isinstance(data, dict):
        masked: dict[str, Any] = {}
        for key, value in data.items():
            if any(s in key.lower() for s in _SENSITIVE_KEYS) and value:
                masked[key] = "***"
            else:
                masked[key] = mask_secrets(value)
        return masked
    if isinstance(data, list):
        return [mask_secrets(item) for item in data]
    return data


def settings_to_api(settings: Settings) -> dict[str, Any]:
    raw = settings.model_dump(mode="json")
    return mask_secrets(raw)

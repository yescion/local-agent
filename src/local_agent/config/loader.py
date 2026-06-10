"""Configuration loader with YAML and environment variable support."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from local_agent.config.models import Settings

_ENV_PREFIX = "LOCAL_AGENT_"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _env_overrides() -> dict[str, Any]:
    """Map LOCAL_AGENT_* env vars to nested config keys."""
    overrides: dict[str, Any] = {}
    mapping = {
        "LOCAL_AGENT_DATA_DIR": ("app", "data_dir"),
        "LOCAL_AGENT_CONFIG": None,  # handled separately
        "LITELLM_API_BASE": ("llm", "api_base"),
    }
    for env_key, path in mapping.items():
        if path is None:
            continue
        val = os.environ.get(env_key)
        if val:
            node = overrides
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = val

    if model := os.environ.get("LOCAL_AGENT_LLM_MODEL"):
        overrides.setdefault("llm", {})["model"] = model
    if api_key := os.environ.get("OPENAI_API_KEY"):
        overrides.setdefault("llm", {})["api_key"] = api_key
    if daytona_key := os.environ.get("DAYTONA_API_KEY"):
        overrides.setdefault("daytona", {})["api_key"] = daytona_key
    if daytona_url := os.environ.get("DAYTONA_API_URL"):
        overrides.setdefault("daytona", {})["api_url"] = daytona_url
    if daytona_target := os.environ.get("DAYTONA_TARGET"):
        overrides.setdefault("daytona", {})["target"] = daytona_target
    if em_api_key := os.environ.get("EM_API_KEY"):
        overrides.setdefault("mx_skills", {})["api_key"] = em_api_key
    return overrides


def load_settings(config_path: Path | str | None = None) -> Settings:
    """Load settings from YAML file with env overrides."""
    if config_path is None:
        config_path = os.environ.get("LOCAL_AGENT_CONFIG", "config/default.yaml")
    path = Path(config_path)
    data: dict[str, Any] = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    data = _deep_merge(data, _env_overrides())
    settings = Settings.model_validate(data)

    # Resolve relative paths from project root (cwd)
    settings.app.data_dir = Path(settings.app.data_dir)
    settings.storage.sqlite_path = Path(settings.storage.sqlite_path)
    settings.skills.directories = [Path(d) for d in settings.skills.directories]
    settings.tools.write_paths = [Path(p) for p in settings.tools.write_paths]
    settings.mx_skills.skills_root = Path(settings.mx_skills.skills_root)
    settings.mx_skills.output_dir = Path(settings.mx_skills.output_dir)
    settings.mx_skills.quota_file = Path(settings.mx_skills.quota_file)
    return settings


def save_settings(settings: Settings, path: Path) -> None:
    """Persist settings to YAML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(settings.model_dump_json())
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)

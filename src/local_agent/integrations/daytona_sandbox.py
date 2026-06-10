"""Bridge between app settings and the daytona_sandbox skill manager."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from local_agent.config.models import DaytonaSandboxConfig

_MANAGER: Any | None = None


def _skill_manager_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    return root / "skills" / "_builtin" / "daytona_sandbox" / "sandbox_manager.py"


def _get_manager():
    global _MANAGER
    if _MANAGER is not None:
        return _MANAGER
    path = _skill_manager_path()
    spec = importlib.util.spec_from_file_location("daytona_sandbox_manager_bridge", path)
    if not spec or not spec.loader:
        raise ImportError(f"Cannot load daytona sandbox manager from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["daytona_sandbox_manager_bridge"] = module
    spec.loader.exec_module(module)
    _MANAGER = module
    return module


def configure(config: DaytonaSandboxConfig) -> None:
    _get_manager().configure(config.model_dump())


def begin_turn() -> None:
    _get_manager().begin_turn()


def set_turn_artifact_context(
    artifact_dir: str | None,
    artifacts_root: str | None = None,
) -> None:
    _get_manager().set_turn_artifact_context(artifact_dir, artifacts_root)


def cleanup_turn() -> list[str]:
    return _get_manager().cleanup_turn_sandboxes()

"""Daytona sandbox client and session state for the daytona_sandbox skill."""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_client: Any | None = None
_active_sandbox_id: str | None = None
_sandboxes: dict[str, Any] = {}
_turn_sandbox_ids: set[str] = set()
_turn_artifact_dir: str | None = None
_turn_artifacts_root: str | None = None
_config: dict[str, Any] | None = None

_DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "api_key": None,
    "api_url": None,
    "target": None,
    "language": "python",
    "snapshot": None,
    "image": None,
    "env_vars": {},
    "labels": {},
    "auto_stop_interval": 5,
    "ephemeral": True,
    "create_timeout": 60.0,
    "exec_timeout": 120,
    "max_output_chars": 100_000,
    "auto_cleanup_on_turn_end": True,
    "cleanup_action": "delete",
}


def configure(config: dict[str, Any]) -> None:
    global _config, _client
    with _lock:
        _config = {**_DEFAULT_CONFIG, **{k: v for k, v in config.items() if v is not None}}
        _client = None


def get_config() -> dict[str, Any]:
    global _config
    if _config is None:
        try:
            from local_agent.config.loader import load_settings

            configure(load_settings().daytona.model_dump())
        except Exception:
            _config = dict(_DEFAULT_CONFIG)
    return _config


def _load_daytona():
    try:
        from daytona import Daytona, DaytonaConfig

        return Daytona, DaytonaConfig
    except ImportError as e:
        raise RuntimeError("未安装 daytona SDK，请运行: pip install daytona") from e


def get_client():
    global _client
    cfg = get_config()
    if not cfg.get("enabled", True):
        raise RuntimeError("Daytona 沙盒已在配置中禁用（daytona.enabled=false）")
    with _lock:
        if _client is None:
            Daytona, DaytonaConfig = _load_daytona()
            daytona_kwargs: dict[str, Any] = {}
            if cfg.get("api_key"):
                daytona_kwargs["api_key"] = cfg["api_key"]
            if cfg.get("api_url"):
                daytona_kwargs["api_url"] = cfg["api_url"]
            if cfg.get("target"):
                daytona_kwargs["target"] = cfg["target"]
            _client = Daytona(DaytonaConfig(**daytona_kwargs)) if daytona_kwargs else Daytona()
        return _client


def begin_turn() -> None:
    global _turn_artifact_dir, _turn_artifacts_root
    with _lock:
        _turn_sandbox_ids.clear()
        _turn_artifact_dir = None
        _turn_artifacts_root = None


def set_turn_artifact_context(
    artifact_dir: str | None,
    artifacts_root: str | None = None,
) -> None:
    global _turn_artifact_dir, _turn_artifacts_root
    with _lock:
        _turn_artifact_dir = artifact_dir
        _turn_artifacts_root = artifacts_root or artifact_dir


def get_turn_artifact_dir() -> str | None:
    with _lock:
        return _turn_artifact_dir


def get_turn_artifacts_root() -> str | None:
    with _lock:
        return _turn_artifacts_root


def mark_turn_sandbox(sandbox_id: str) -> None:
    with _lock:
        _turn_sandbox_ids.add(sandbox_id)


def cleanup_turn_sandboxes() -> list[str]:
    cfg = get_config()
    if not cfg.get("auto_cleanup_on_turn_end", True):
        return []
    action = cfg.get("cleanup_action", "delete")
    with _lock:
        ids = list(_turn_sandbox_ids)
        _turn_sandbox_ids.clear()

    cleaned: list[str] = []
    if not ids:
        return cleaned

    try:
        client = get_client()
    except Exception:
        return cleaned

    for sid in ids:
        try:
            with _lock:
                sandbox = _sandboxes.get(sid)
            if sandbox is None:
                sandbox = client.get(sid)
            if action == "delete":
                client.delete(sandbox)
            else:
                sandbox.stop()
            remove_sandbox(sid)
            cleaned.append(sid)
        except Exception:
            remove_sandbox(sid)
    return cleaned


def get_active_sandbox_id() -> str | None:
    with _lock:
        return _active_sandbox_id


def set_active_sandbox(sandbox: Any, *, track_turn: bool = False) -> str:
    global _active_sandbox_id
    with _lock:
        _sandboxes[sandbox.id] = sandbox
        _active_sandbox_id = sandbox.id
        if track_turn:
            _turn_sandbox_ids.add(sandbox.id)
        return sandbox.id


def cache_sandbox(sandbox: Any) -> None:
    with _lock:
        _sandboxes[sandbox.id] = sandbox


def remove_sandbox(sandbox_id: str) -> None:
    global _active_sandbox_id
    with _lock:
        _sandboxes.pop(sandbox_id, None)
        _turn_sandbox_ids.discard(sandbox_id)
        if _active_sandbox_id == sandbox_id:
            _active_sandbox_id = None


def resolve_sandbox(sandbox_id: str | None = None) -> Any:
    with _lock:
        sid = sandbox_id or _active_sandbox_id
        if not sid:
            raise ValueError(
                "未指定沙盒且当前无活动沙盒。请先调用 sandbox_create 或 sandbox_connect。"
            )
        sandbox = _sandboxes.get(sid)
        if sandbox:
            return sandbox
    client = get_client()
    sandbox = client.get(sid)
    cache_sandbox(sandbox)
    return sandbox


def get_create_defaults() -> dict[str, Any]:
    cfg = get_config()
    return {
        "language": cfg.get("language", "python"),
        "snapshot": cfg.get("snapshot") or "",
        "image": cfg.get("image") or "",
        "env_vars": dict(cfg.get("env_vars") or {}),
        "labels": dict(cfg.get("labels") or {}),
        "auto_stop_interval": cfg.get("auto_stop_interval", 5),
        "ephemeral": bool(cfg.get("ephemeral", True)),
        "create_timeout": float(cfg.get("create_timeout", 60.0)),
    }


def format_sandbox_info(sandbox: Any) -> str:
    lines = [
        f"ID: {sandbox.id}",
        f"名称: {getattr(sandbox, 'name', '') or '(未命名)'}",
        f"状态: {getattr(sandbox, 'state', 'unknown')}",
        f"语言: {getattr(sandbox, 'language', 'unknown')}",
        f"CPU: {getattr(sandbox, 'cpu', '?')}",
        f"内存: {getattr(sandbox, 'memory', '?')} GiB",
        f"工作目录: {sandbox.get_work_dir()}",
        f"用户主目录: {sandbox.get_user_home_dir()}",
    ]
    labels = getattr(sandbox, "labels", None)
    if labels:
        lines.append(f"标签: {labels}")
    return "\n".join(lines)


def format_exec_response(resp: Any, max_chars: int | None = None) -> str:
    if max_chars is None:
        max_chars = int(get_config().get("max_output_chars", 100_000))
    stdout = ""
    stderr = ""
    if getattr(resp, "artifacts", None):
        stdout = getattr(resp.artifacts, "stdout", None) or ""
    if not stdout:
        stdout = getattr(resp, "result", None) or getattr(resp, "output", None) or ""
    if hasattr(resp, "stdout") and resp.stdout:
        stdout = resp.stdout
    if hasattr(resp, "stderr") and resp.stderr:
        stderr = resp.stderr

    parts: list[str] = []
    if stdout:
        parts.append(stdout.rstrip())
    if stderr:
        parts.append(f"[stderr]\n{stderr.rstrip()}")

    exit_code = getattr(resp, "exit_code", None)
    if exit_code is not None:
        parts.append(f"[exit_code={exit_code}]")

    text = "\n".join(parts) if parts else "(无输出)"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…（输出已截断，共约 {len(text)} 字符）"
    return text


def truncate_text(text: str, max_chars: int | None = None) -> str:
    if max_chars is None:
        max_chars = int(get_config().get("max_output_chars", 100_000))
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n…（已截断，共约 {len(text)} 字符）"

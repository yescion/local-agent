"""Execute agent-created (sandbox) skills in ephemeral Daytona sandboxes."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_turn_exec_sandboxes: dict[str, Any] = {}
_runner_source: str | None = None

RUNNER_FILENAME = "_skill_runner.py"


def _runner_path() -> Path:
    return Path(__file__).resolve().parents[3] / "skills" / "_builtin" / "skill_studio" / RUNNER_FILENAME


def get_runner_source() -> str:
    global _runner_source
    if _runner_source is None:
        _runner_source = _runner_path().read_text(encoding="utf-8")
    return _runner_source


def begin_execution_turn() -> None:
    with _lock:
        _turn_exec_sandboxes.clear()


def get_execution_sandbox(skill_id: str) -> Any | None:
    """Return the ephemeral sandbox used for a sandbox-execution skill this turn."""
    with _lock:
        return _turn_exec_sandboxes.get(skill_id.strip())


def pop_execution_sandbox(skill_id: str) -> Any | None:
    """Remove and return a per-turn execution sandbox (after agent releases it)."""
    with _lock:
        return _turn_exec_sandboxes.pop(skill_id.strip(), None)


def cleanup_execution_sandboxes() -> list[str]:
    """Delete per-turn execution sandboxes (no persistent skill-runtime VM)."""
    with _lock:
        sandboxes = list(_turn_exec_sandboxes.values())
        _turn_exec_sandboxes.clear()

    if not sandboxes:
        return []

    try:
        from local_agent.integrations.daytona_sandbox import _get_manager

        mgr = _get_manager()
        client = mgr.get_client()
    except Exception:
        return []

    cleaned: list[str] = []
    for sandbox in sandboxes:
        sid = getattr(sandbox, "id", None)
        if not sid:
            continue
        try:
            client.delete(sandbox)
            mgr.remove_sandbox(sid)
            cleaned.append(sid)
        except Exception:
            mgr.remove_sandbox(sid)
    return cleaned


def _get_daytona_manager():
    from local_agent.integrations.daytona_sandbox import _get_manager

    return _get_manager()


def _remote_skill_dir(skill_id: str) -> str:
    return f"/tmp/agent_skills/{skill_id}"


def _ensure_execution_sandbox(skill_id: str) -> Any:
    with _lock:
        cached = _turn_exec_sandboxes.get(skill_id)
        if cached is not None:
            return cached

    mgr = _get_daytona_manager()
    defaults = mgr.get_create_defaults()
    from daytona import CreateSandboxFromSnapshotParams

    client = mgr.get_client()
    params = CreateSandboxFromSnapshotParams(
        language=defaults.get("language", "python"),
        ephemeral=True,
        auto_stop_interval=0,
        labels={"role": "agent-skill-exec", "skill_id": skill_id},
    )
    snapshot = defaults.get("snapshot")
    if snapshot:
        params.snapshot = snapshot
    timeout = float(defaults.get("create_timeout", 60.0))
    sandbox = client.create(params, timeout=timeout)
    mgr.cache_sandbox(sandbox)

    with _lock:
        _turn_exec_sandboxes[skill_id] = sandbox
    return sandbox


def _upload_skill_bundle(sandbox: Any, skill_id: str, skill_dir: Path) -> str:
    remote_dir = _remote_skill_dir(skill_id)
    sandbox.fs.create_folder(remote_dir, "755")
    for name in ("SKILL.md", "tools.py", "requirements.txt"):
        local = skill_dir / name
        if local.is_file():
            sandbox.fs.upload_file(local.read_bytes(), f"{remote_dir}/{name}")
    sandbox.fs.upload_file(
        get_runner_source().encode("utf-8"),
        f"{remote_dir}/{RUNNER_FILENAME}",
    )
    return remote_dir


def _install_requirements(sandbox: Any, remote_dir: str) -> str | None:
    req_path = f"{remote_dir}/requirements.txt"
    try:
        sandbox.fs.download_file(req_path)
    except Exception:
        return None
    cmd = f"pip install -q -r {req_path}"
    resp = sandbox.process.exec(cmd, timeout=300)
    exit_code = getattr(resp, "exit_code", None)
    if exit_code not in (None, 0):
        stdout = ""
        if getattr(resp, "artifacts", None):
            stdout = getattr(resp.artifacts, "stdout", None) or ""
        stderr = getattr(resp, "stderr", None) or ""
        return f"依赖安装失败 (exit={exit_code}):\n{stdout}\n{stderr}".strip()
    return None


def invoke_skill_tool(skill_id: str, skill_dir: Path, tool_name: str, arguments: dict[str, Any]) -> str:
    """Run one tool from an agent-created skill inside an ephemeral sandbox."""
    if not (skill_dir / "tools.py").is_file():
        return f"错误：技能 {skill_id} 缺少 tools.py"

    try:
        sandbox = _ensure_execution_sandbox(skill_id)
        remote_dir = _upload_skill_bundle(sandbox, skill_id, skill_dir)
        install_err = _install_requirements(sandbox, remote_dir)
        if install_err:
            return install_err

        args_path = f"{remote_dir}/_invoke_args.json"
        sandbox.fs.upload_file(
            json.dumps(arguments, ensure_ascii=False).encode("utf-8"),
            args_path,
        )
        cmd = (
            f"python {remote_dir}/{RUNNER_FILENAME} "
            f"--skill-dir {remote_dir} --tool {tool_name} "
            f"--args-file {args_path}"
        )
        mgr = _get_daytona_manager()
        exec_timeout = int(mgr.get_config().get("exec_timeout", 120))
        resp = sandbox.process.exec(cmd, timeout=max(1, exec_timeout))
        output = mgr.format_exec_response(resp)
        return _parse_runner_output(output)
    except Exception as e:
        return f"错误：沙盒执行技能工具失败 — {e}"


def _parse_runner_output(raw: str) -> str:
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if not line or line.startswith("[exit_code=") or line.startswith("[stderr]"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            if payload.get("ok"):
                return str(payload.get("result", ""))
            return f"错误：{payload.get('error', '未知错误')}"
    return raw.strip() or "(无输出)"

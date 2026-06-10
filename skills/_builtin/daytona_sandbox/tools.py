"""Daytona sandbox skill tools — isolated command and file operations."""

from __future__ import annotations

import importlib.util
import json
import shlex
import sys
from pathlib import Path
from typing import Any

_mgr_path = Path(__file__).with_name("sandbox_manager.py")
_spec = importlib.util.spec_from_file_location("daytona_sandbox_manager", _mgr_path)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
sys.modules["daytona_sandbox_manager"] = _mod
_spec.loader.exec_module(_mod)

format_exec_response = _mod.format_exec_response
format_sandbox_info = _mod.format_sandbox_info
get_client = _mod.get_client
get_config = _mod.get_config
get_create_defaults = _mod.get_create_defaults
get_turn_artifact_dir = _mod.get_turn_artifact_dir
get_turn_artifacts_root = _mod.get_turn_artifacts_root
remove_sandbox = _mod.remove_sandbox
resolve_sandbox = _mod.resolve_sandbox
set_active_sandbox = _mod.set_active_sandbox
truncate_text = _mod.truncate_text

_SANDBOX_ID_PARAM = {
    "type": "string",
    "description": "沙盒 ID 或名称；省略则使用当前活动沙盒",
}

TOOLS = [
    {
        "name": "sandbox_create",
        "description": (
            "创建新的 Daytona 隔离沙盒并设为当前活动沙盒。"
            "未传参数时使用 config/default.yaml 中 daytona 段的默认值（默认 ephemeral=true）。"
            "用完须立即 sandbox_delete 释放；回合结束也会自动清理。"
        ),
        "parameters": {
            "properties": {
                "name": {"type": "string", "description": "沙盒名称（可选）"},
                "language": {
                    "type": "string",
                    "description": "编程语言，默认 python",
                    "enum": ["python", "typescript", "javascript"],
                },
                "snapshot": {"type": "string", "description": "使用的快照名称（可选）"},
                "image": {"type": "string", "description": "Docker 镜像，如 debian:12（可选，与 snapshot 二选一）"},
                "env_vars": {
                    "type": "object",
                    "description": "环境变量键值对",
                },
                "labels": {"type": "object", "description": "自定义标签键值对"},
                "auto_stop_interval": {
                    "type": "integer",
                    "description": "空闲自动停止间隔（分钟），0 表示禁用，默认 15",
                },
                "ephemeral": {
                    "type": "boolean",
                    "description": "是否创建临时沙盒（停止后立即删除）",
                },
            },
            "required": [],
        },
    },
    {
        "name": "sandbox_connect",
        "description": "连接已有沙盒（按 ID 或名称）并设为当前活动沙盒。",
        "parameters": {
            "properties": {"sandbox_id": {"type": "string", "description": "沙盒 ID 或名称"}},
            "required": ["sandbox_id"],
        },
    },
    {
        "name": "sandbox_list",
        "description": "列出组织内的沙盒（可按标签过滤）。",
        "parameters": {
            "properties": {
                "labels": {"type": "object", "description": "标签过滤，如 {\"env\": \"dev\"}"},
                "limit": {"type": "integer", "description": "最大返回数量，默认 20"},
            },
            "required": [],
        },
    },
    {
        "name": "sandbox_info",
        "description": "获取沙盒详细信息（状态、资源、工作目录等）。",
        "parameters": {
            "properties": {"sandbox_id": _SANDBOX_ID_PARAM},
            "required": [],
        },
    },
    {
        "name": "sandbox_stop",
        "description": (
            "停止沙盒以暂停计费（资源仍保留）。"
            "任务完成后优先 sandbox_delete 彻底释放；"
            "execution:sandbox 技能可传 execution_skill_id 定位其执行沙盒。"
        ),
        "parameters": {
            "properties": {
                "sandbox_id": _SANDBOX_ID_PARAM,
                "execution_skill_id": {
                    "type": "string",
                    "description": "execution:sandbox 技能 ID（如 excel_tool）；优先于 sandbox_id",
                },
                "force": {"type": "boolean", "description": "是否强制 SIGKILL 停止"},
            },
            "required": [],
        },
    },
    {
        "name": "sandbox_delete",
        "description": (
            "删除沙盒并释放资源（**沙盒技能用完必须调用**）。"
            "可传 sandbox_id，或 execution_skill_id 释放 execution:sandbox 技能的执行沙盒。"
        ),
        "parameters": {
            "properties": {
                "sandbox_id": _SANDBOX_ID_PARAM,
                "execution_skill_id": {
                    "type": "string",
                    "description": "execution:sandbox 技能 ID（如 excel_tool）；优先于 sandbox_id",
                },
            },
            "required": [],
        },
    },
    {
        "name": "sandbox_exec",
        "description": (
            "在沙盒中执行 shell 命令。**所有命令执行必须通过此工具**，禁止在宿主机执行。"
        ),
        "parameters": {
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
                "cwd": {"type": "string", "description": "工作目录（沙盒内路径）"},
                "env": {"type": "object", "description": "命令级环境变量"},
                "timeout": {"type": "integer", "description": "超时秒数，默认 120"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["command"],
        },
    },
    {
        "name": "sandbox_code_run",
        "description": "在沙盒中运行代码片段（支持 Python 等，自动选择运行时）。",
        "parameters": {
            "properties": {
                "code": {"type": "string", "description": "要执行的代码"},
                "timeout": {"type": "integer", "description": "超时秒数，默认 120"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["code"],
        },
    },
    {
        "name": "sandbox_session_create",
        "description": "创建持久 shell 会话（可保持 cd、环境变量等状态）。",
        "parameters": {
            "properties": {
                "session_id": {"type": "string", "description": "会话唯一标识"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "sandbox_session_exec",
        "description": "在持久会话中执行命令（保持 shell 状态）。",
        "parameters": {
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "command": {"type": "string", "description": "要执行的命令"},
                "run_async": {
                    "type": "boolean",
                    "description": "是否异步执行，默认 false（同步等待结果）",
                },
                "timeout": {"type": "integer", "description": "超时秒数"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["session_id", "command"],
        },
    },
    {
        "name": "sandbox_session_delete",
        "description": "删除持久 shell 会话。",
        "parameters": {
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "sandbox_fs_list",
        "description": "列出沙盒内目录内容（类似 ls -l）。",
        "parameters": {
            "properties": {
                "path": {"type": "string", "description": "目录路径，默认工作目录"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": [],
        },
    },
    {
        "name": "sandbox_fs_read",
        "description": (
            "读取沙盒内文件内容。大文件请用 offset/limit 分批按行读取"
            "（在沙盒内 sed 切片，仅传输所需行）。"
        ),
        "parameters": {
            "properties": {
                "path": {"type": "string", "description": "文件路径（沙盒内）"},
                "max_chars": {
                    "type": "integer",
                    "description": "最大返回字符数，默认 50000（全文读取时生效）",
                },
                "offset": {
                    "type": "integer",
                    "description": "起始行号（1 起算）。正数从文件开头计数，负数从末尾倒数（-1 为最后一行）。"
                    "仅读取部分行时提供。",
                },
                "limit": {
                    "type": "integer",
                    "description": "读取行数。与 offset 配合分批读取大文件；"
                    "仅提供 limit 时从第 1 行开始读取。",
                },
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["path"],
        },
    },
    {
        "name": "sandbox_fs_write",
        "description": (
            "将文本内容写入沙盒内文件（覆盖）。"
            "沙盒内路径须使用英文/ASCII 文件名，勿用中文路径。"
        ),
        "parameters": {
            "properties": {
                "path": {
                    "type": "string",
                    "description": "目标文件路径（沙盒内，须英文/ASCII 文件名）",
                },
                "content": {"type": "string", "description": "文件内容"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "sandbox_fs_upload_local",
        "description": "从宿主机上传本地文件到沙盒。",
        "parameters": {
            "properties": {
                "local_path": {"type": "string", "description": "宿主机本地文件路径"},
                "remote_path": {"type": "string", "description": "沙盒内目标路径"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["local_path", "remote_path"],
        },
    },
    {
        "name": "sandbox_fs_download_local",
        "description": (
            "从沙盒下载文件到宿主机产物目录（支持二进制文件如 .xlsx、.png）。"
            "沙盒内源路径须使用英文/ASCII 文件名；下载到本地时可通过 local_path 指定中文文件名。"
            "省略 local_path 时保存到当前会话产物目录，文件名为沙盒路径的 basename。"
            "从 execution:sandbox 技能（如 excel_tool）导出时须传 execution_skill_id。"
        ),
        "parameters": {
            "properties": {
                "remote_path": {
                    "type": "string",
                    "description": "沙盒内源文件路径（须英文/ASCII 文件名，勿用中文路径）",
                },
                "sandbox_path": {
                    "type": "string",
                    "description": "同 remote_path（沙盒内源文件路径，须英文/ASCII 文件名）",
                },
                "local_path": {
                    "type": "string",
                    "description": "宿主机目标路径；相对路径写入会话产物目录，可使用中文文件名；省略则用 remote_path 的文件名",
                },
                "sandbox_id": _SANDBOX_ID_PARAM,
                "execution_skill_id": {
                    "type": "string",
                    "description": "execution:sandbox 技能 ID（如 excel_tool）；从该技能执行沙盒下载，优先于 sandbox_id",
                },
            },
            "required": [],
        },
    },
    {
        "name": "sandbox_fs_mkdir",
        "description": "在沙盒内创建目录。",
        "parameters": {
            "properties": {
                "path": {"type": "string", "description": "目录路径"},
                "mode": {"type": "string", "description": "权限八进制，默认 755"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["path"],
        },
    },
    {
        "name": "sandbox_fs_delete",
        "description": "删除沙盒内文件或目录。",
        "parameters": {
            "properties": {
                "path": {"type": "string", "description": "文件或目录路径"},
                "recursive": {"type": "boolean", "description": "删除目录时是否递归"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["path"],
        },
    },
    {
        "name": "sandbox_fs_move",
        "description": "移动或重命名沙盒内文件/目录。",
        "parameters": {
            "properties": {
                "source": {"type": "string", "description": "源路径"},
                "destination": {"type": "string", "description": "目标路径"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["source", "destination"],
        },
    },
    {
        "name": "sandbox_fs_find",
        "description": "在沙盒内按内容搜索（类似 grep）。",
        "parameters": {
            "properties": {
                "path": {"type": "string", "description": "搜索根路径"},
                "pattern": {"type": "string", "description": "搜索模式"},
                "max_results": {"type": "integer", "description": "最大匹配数，默认 50"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["path", "pattern"],
        },
    },
    {
        "name": "sandbox_fs_search",
        "description": "在沙盒内按文件名 glob 搜索（如 *.py）。",
        "parameters": {
            "properties": {
                "path": {"type": "string", "description": "搜索根路径"},
                "pattern": {"type": "string", "description": "glob 模式，如 *.py"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["path", "pattern"],
        },
    },
    {
        "name": "sandbox_git_clone",
        "description": "在沙盒内克隆 Git 仓库。",
        "parameters": {
            "properties": {
                "url": {"type": "string", "description": "仓库 URL"},
                "path": {"type": "string", "description": "克隆目标路径（沙盒内）"},
                "branch": {"type": "string", "description": "分支名（可选）"},
                "username": {"type": "string", "description": "认证用户名（可选）"},
                "password": {"type": "string", "description": "认证密码或 token（可选）"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["url", "path"],
        },
    },
    {
        "name": "sandbox_git_status",
        "description": "查看沙盒内 Git 仓库状态。",
        "parameters": {
            "properties": {
                "path": {"type": "string", "description": "仓库根路径"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["path"],
        },
    },
    {
        "name": "sandbox_git_commit",
        "description": "在沙盒内暂存文件并提交。",
        "parameters": {
            "properties": {
                "path": {"type": "string", "description": "仓库根路径"},
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要暂存的文件列表，相对仓库根路径",
                },
                "message": {"type": "string", "description": "提交信息"},
                "author": {"type": "string", "description": "作者名"},
                "email": {"type": "string", "description": "作者邮箱"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["path", "files", "message", "author", "email"],
        },
    },
    {
        "name": "sandbox_git_pull",
        "description": "在沙盒内拉取远程更新。",
        "parameters": {
            "properties": {
                "path": {"type": "string", "description": "仓库根路径"},
                "username": {"type": "string", "description": "认证用户名（可选）"},
                "password": {"type": "string", "description": "认证密码或 token（可选）"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["path"],
        },
    },
    {
        "name": "sandbox_git_push",
        "description": "在沙盒内推送本地提交到远程。",
        "parameters": {
            "properties": {
                "path": {"type": "string", "description": "仓库根路径"},
                "username": {"type": "string", "description": "认证用户名（可选）"},
                "password": {"type": "string", "description": "认证密码或 token（可选）"},
                "sandbox_id": _SANDBOX_ID_PARAM,
            },
            "required": ["path"],
        },
    },
]


def _err(e: Exception) -> str:
    return f"错误：{e}"


def _exec_stdout(resp: Any) -> str:
    if getattr(resp, "artifacts", None):
        stdout = getattr(resp.artifacts, "stdout", None) or ""
        if stdout:
            return stdout
    stdout = getattr(resp, "result", None) or getattr(resp, "output", None) or ""
    if stdout:
        return stdout
    if hasattr(resp, "stdout") and resp.stdout:
        return resp.stdout
    return ""


def _exec_stderr(resp: Any) -> str:
    if hasattr(resp, "stderr") and resp.stderr:
        return resp.stderr
    if getattr(resp, "artifacts", None):
        return getattr(resp.artifacts, "stderr", None) or ""
    return ""


def _sandbox_process_exec(sandbox: Any, command: str, timeout: int | None = None) -> Any:
    exec_timeout = timeout if timeout is not None else int(get_config().get("exec_timeout", 120))
    return sandbox.process.exec(command, timeout=max(1, exec_timeout))


def _sandbox_fs_read_lines(
    sandbox: Any,
    path: str,
    offset: int | None,
    limit: int | None,
) -> str:
    from local_agent.tools.builtin import format_text_line_range, resolve_text_line_range

    try:
        info = sandbox.fs.get_file_info(path)
        if getattr(info, "is_dir", False):
            return f"错误：不是文件 — {path}"
    except Exception as e:
        return f"错误：文件不存在 — {path} ({e})"

    quoted = shlex.quote(path)
    wc_resp = _sandbox_process_exec(sandbox, f"wc -l < {quoted}")
    wc_exit = getattr(wc_resp, "exit_code", None)
    if wc_exit not in (0, None):
        detail = _exec_stderr(wc_resp) or _exec_stdout(wc_resp)
        return f"错误：统计行数失败 — {detail or wc_exit}"

    wc_out = _exec_stdout(wc_resp).strip()
    if not wc_out.isdigit():
        return f"错误：无法解析行数 — {wc_out!r}"

    total_lines = int(wc_out)
    resolved = resolve_text_line_range(total_lines, offset, limit)
    if isinstance(resolved, str):
        return resolved
    start_line, end_line = resolved

    sed_resp = _sandbox_process_exec(
        sandbox,
        f"sed -n '{start_line},{end_line}p' {quoted}",
    )
    sed_exit = getattr(sed_resp, "exit_code", None)
    if sed_exit not in (0, None):
        detail = _exec_stderr(sed_resp) or _exec_stdout(sed_resp)
        return f"错误：读取文件失败 — {detail or sed_exit}"

    selected = _exec_stdout(sed_resp).splitlines()
    return format_text_line_range(selected, start_line, end_line, total_lines)


def sandbox_create(
    name: str = "",
    language: str = "",
    snapshot: str = "",
    image: str = "",
    env_vars: dict[str, str] | None = None,
    labels: dict[str, str] | None = None,
    auto_stop_interval: int | None = None,
    ephemeral: bool | None = None,
) -> str:
    try:
        from daytona import (
            CreateSandboxFromImageParams,
            CreateSandboxFromSnapshotParams,
        )

        defaults = get_create_defaults()
        client = get_client()
        base_kwargs: dict[str, Any] = {
            "language": language or defaults["language"],
            "auto_stop_interval": (
                auto_stop_interval
                if auto_stop_interval is not None
                else defaults["auto_stop_interval"]
            ),
            "ephemeral": defaults["ephemeral"] if ephemeral is None else ephemeral,
        }
        merged_env = dict(defaults["env_vars"])
        if env_vars:
            merged_env.update(env_vars)
        if merged_env:
            base_kwargs["env_vars"] = merged_env
        merged_labels = dict(defaults["labels"])
        if labels:
            merged_labels.update(labels)
        if merged_labels:
            base_kwargs["labels"] = merged_labels
        if name:
            base_kwargs["name"] = name

        use_image = image or defaults["image"]
        use_snapshot = snapshot or defaults["snapshot"]
        timeout = defaults["create_timeout"]

        if use_image:
            params = CreateSandboxFromImageParams(image=use_image, **base_kwargs)
            sandbox = client.create(params, timeout=timeout)
        else:
            snap_kwargs = dict(base_kwargs)
            if use_snapshot:
                snap_kwargs["snapshot"] = use_snapshot
            params = CreateSandboxFromSnapshotParams(**snap_kwargs)
            sandbox = client.create(params, timeout=timeout)

        set_active_sandbox(sandbox, track_turn=True)
        ephemeral_hint = "是" if base_kwargs.get("ephemeral") else "否"
        return (
            f"沙盒已创建并设为活动沙盒（ephemeral={ephemeral_hint}，"
            f"回合结束后将自动{get_config().get('cleanup_action', 'delete')}）。\n\n"
            f"{format_sandbox_info(sandbox)}"
        )
    except Exception as e:
        return _err(e)


def sandbox_connect(sandbox_id: str) -> str:
    try:
        client = get_client()
        sandbox = client.get(sandbox_id.strip())
        set_active_sandbox(sandbox)
        return f"已连接沙盒。\n\n{format_sandbox_info(sandbox)}"
    except Exception as e:
        return _err(e)


def sandbox_list(labels: dict[str, str] | None = None, limit: int = 20) -> str:
    try:
        from daytona import ListSandboxesQuery

        client = get_client()
        query = ListSandboxesQuery(labels=labels) if labels else None
        lines = []
        for i, sb in enumerate(client.list(query)):
            if i >= max(1, limit):
                break
            state = getattr(sb, "state", "?")
            name = getattr(sb, "name", "") or "(未命名)"
            lines.append(f"- {sb.id} | {name} | 状态: {state}")
        return "\n".join(lines) if lines else "(无匹配沙盒)"
    except Exception as e:
        return _err(e)


def sandbox_info(sandbox_id: str = "") -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        sandbox.refresh_data()
        return format_sandbox_info(sandbox)
    except Exception as e:
        return _err(e)


def sandbox_stop(
    sandbox_id: str = "",
    execution_skill_id: str = "",
    force: bool = False,
) -> str:
    try:
        sandbox = _resolve_sandbox_target(sandbox_id, execution_skill_id)
        sandbox.stop(force=force)
        return f"沙盒 {sandbox.id} 已停止。"
    except Exception as e:
        return _err(e)


def sandbox_delete(sandbox_id: str = "", execution_skill_id: str = "") -> str:
    try:
        sandbox = _resolve_sandbox_target(sandbox_id, execution_skill_id)
        sid = sandbox.id
        client = get_client()
        client.delete(sandbox)
        remove_sandbox(sid)
        skill_id = execution_skill_id.strip()
        if skill_id:
            from local_agent.integrations.skill_runtime import pop_execution_sandbox

            pop_execution_sandbox(skill_id)
        return f"沙盒 {sid} 已删除。"
    except Exception as e:
        return _err(e)


def sandbox_exec(
    command: str,
    cwd: str = "",
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    sandbox_id: str = "",
) -> str:
    command = command.strip()
    if not command:
        return "错误：命令不能为空"
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        exec_timeout = timeout if timeout is not None else int(get_config().get("exec_timeout", 120))
        kwargs: dict[str, Any] = {"timeout": max(1, exec_timeout)}
        if cwd:
            kwargs["cwd"] = cwd
        if env:
            kwargs["env"] = env
        resp = sandbox.process.exec(command, **kwargs)
        return format_exec_response(resp)
    except Exception as e:
        return _err(e)


def sandbox_code_run(
    code: str,
    timeout: int | None = None,
    sandbox_id: str = "",
) -> str:
    if not code.strip():
        return "错误：代码不能为空"
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        exec_timeout = timeout if timeout is not None else int(get_config().get("exec_timeout", 120))
        resp = sandbox.process.code_run(code, timeout=max(1, exec_timeout))
        return format_exec_response(resp)
    except Exception as e:
        return _err(e)


def sandbox_session_create(session_id: str, sandbox_id: str = "") -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        sandbox.process.create_session(session_id)
        return f"会话「{session_id}」已创建。"
    except Exception as e:
        return _err(e)


def sandbox_session_exec(
    session_id: str,
    command: str,
    run_async: bool = False,
    timeout: int | None = None,
    sandbox_id: str = "",
) -> str:
    try:
        from daytona import SessionExecuteRequest

        sandbox = resolve_sandbox(sandbox_id or None)
        req = SessionExecuteRequest(command=command, run_async=run_async)
        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        resp = sandbox.process.execute_session_command(session_id, req, **kwargs)
        return format_exec_response(resp)
    except Exception as e:
        return _err(e)


def sandbox_session_delete(session_id: str, sandbox_id: str = "") -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        sandbox.process.delete_session(session_id)
        return f"会话「{session_id}」已删除。"
    except Exception as e:
        return _err(e)


def sandbox_fs_list(path: str = "", sandbox_id: str = "") -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        target = path or sandbox.get_work_dir()
        files = sandbox.fs.list_files(target)
        if not files:
            return f"(空目录) {target}"
        lines = [f"目录: {target}"]
        for f in files[:200]:
            prefix = "[DIR] " if f.is_dir else "      "
            size = f.size if not f.is_dir else "-"
            lines.append(f"{prefix}{f.name}  ({size} bytes)")
        if len(files) > 200:
            lines.append(f"... 还有 {len(files) - 200} 项")
        return "\n".join(lines)
    except Exception as e:
        return _err(e)


def sandbox_fs_read(
    path: str,
    max_chars: int = 50_000,
    offset: int | None = None,
    limit: int | None = None,
    sandbox_id: str = "",
) -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        if offset is not None or limit is not None:
            return _sandbox_fs_read_lines(sandbox, path, offset, limit)
        data = sandbox.fs.download_file(path)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return f"错误：{path} 不是 UTF-8 文本文件（{len(data)} 字节二进制）"
        return truncate_text(text, max_chars)
    except Exception as e:
        return _err(e)


def sandbox_fs_write(path: str, content: str, sandbox_id: str = "") -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        sandbox.fs.upload_file(content.encode("utf-8"), path)
        return f"已写入 {path}（{len(content)} 字符）"
    except Exception as e:
        return _err(e)


def _resolve_sandbox_target(sandbox_id: str, execution_skill_id: str) -> Any:
    skill_id = execution_skill_id.strip()
    if skill_id:
        from local_agent.integrations.skill_runtime import get_execution_sandbox

        sandbox = get_execution_sandbox(skill_id)
        if sandbox is None:
            raise ValueError(
                f"技能「{skill_id}」在本轮尚未执行过，无法定位其沙盒。"
                "请先调用该技能的工具，再操作沙盒。"
            )
        return sandbox
    return resolve_sandbox(sandbox_id or None)


def _resolve_download_sandbox(sandbox_id: str, execution_skill_id: str) -> Any:
    return _resolve_sandbox_target(sandbox_id, execution_skill_id)


def _artifact_context() -> tuple[str | None, str | None]:
    try:
        from local_agent.integrations.daytona_sandbox import _get_manager

        mgr = _get_manager()
        return mgr.get_turn_artifact_dir(), mgr.get_turn_artifacts_root()
    except Exception:
        return get_turn_artifact_dir(), get_turn_artifacts_root()


def _resolve_local_download_path(local_path: str, remote_path: str) -> Path:
    artifact_dir, artifacts_root = _artifact_context()
    remote_name = Path(remote_path).name

    if local_path.strip():
        p = Path(local_path).expanduser()
        if not p.is_absolute():
            if not artifact_dir:
                raise ValueError(
                    "未指定 local_path 的绝对路径，且当前无可用的会话产物目录"
                )
            p = Path(artifact_dir) / p
        resolved = p.resolve()
    else:
        if not artifact_dir:
            raise ValueError("未指定 local_path 且当前无可用的会话产物目录")
        resolved = (Path(artifact_dir) / remote_name).resolve()

    if artifacts_root:
        root = Path(artifacts_root).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"路径不在产物目录白名单内 — {resolved}") from exc
    return resolved


def sandbox_fs_download_local(
    remote_path: str = "",
    local_path: str = "",
    sandbox_id: str = "",
    execution_skill_id: str = "",
    sandbox_path: str = "",
) -> str:
    remote_path = (remote_path or sandbox_path).strip()
    if not remote_path:
        return "错误：remote_path（或 sandbox_path）不能为空"
    try:
        sandbox = _resolve_download_sandbox(sandbox_id, execution_skill_id)
        data = sandbox.fs.download_file(remote_path)
        if not data:
            return f"错误：沙盒文件为空 — {remote_path}"
        target = _resolve_local_download_path(local_path, remote_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return f"已下载到 {target}（{len(data)} 字节）"
    except Exception as e:
        return _err(e)


def sandbox_fs_upload_local(
    local_path: str, remote_path: str, sandbox_id: str = ""
) -> str:
    try:
        p = Path(local_path).expanduser().resolve()
        if not p.exists():
            return f"错误：本地文件不存在 — {local_path}"
        if not p.is_file():
            return f"错误：不是文件 — {local_path}"
        sandbox = resolve_sandbox(sandbox_id or None)
        sandbox.fs.upload_file(str(p), remote_path)
        return f"已上传 {p} → 沙盒:{remote_path}（{p.stat().st_size} 字节）"
    except Exception as e:
        return _err(e)


def sandbox_fs_mkdir(path: str, mode: str = "755", sandbox_id: str = "") -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        sandbox.fs.create_folder(path, mode)
        return f"已创建目录 {path}（mode={mode}）"
    except Exception as e:
        return _err(e)


def sandbox_fs_delete(path: str, recursive: bool = False, sandbox_id: str = "") -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        sandbox.fs.delete_file(path, recursive=recursive)
        return f"已删除 {path}"
    except Exception as e:
        return _err(e)


def sandbox_fs_move(source: str, destination: str, sandbox_id: str = "") -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        sandbox.fs.move_files(source, destination)
        return f"已移动 {source} → {destination}"
    except Exception as e:
        return _err(e)


def sandbox_fs_find(
    path: str, pattern: str, max_results: int = 50, sandbox_id: str = ""
) -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        matches = sandbox.fs.find_files(path, pattern)
        lines = []
        for m in matches[: max(1, max_results)]:
            lines.append(f"{m.file}:{m.line}: {m.content.strip()}")
        if not lines:
            return f"未找到匹配「{pattern}」的内容"
        if len(matches) > max_results:
            lines.append(f"... 还有 {len(matches) - max_results} 条匹配")
        return "\n".join(lines)
    except Exception as e:
        return _err(e)


def sandbox_fs_search(path: str, pattern: str, sandbox_id: str = "") -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        result = sandbox.fs.search_files(path, pattern)
        files = result.files or []
        if not files:
            return f"未找到匹配「{pattern}」的文件"
        return "\n".join(files[:200])
    except Exception as e:
        return _err(e)


def sandbox_git_clone(
    url: str,
    path: str,
    branch: str = "",
    username: str = "",
    password: str = "",
    sandbox_id: str = "",
) -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        kwargs: dict[str, str] = {"url": url, "path": path}
        if branch:
            kwargs["branch"] = branch
        if username:
            kwargs["username"] = username
        if password:
            kwargs["password"] = password
        sandbox.git.clone(**kwargs)
        return f"已克隆 {url} → {path}"
    except Exception as e:
        return _err(e)


def sandbox_git_status(path: str, sandbox_id: str = "") -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        status = sandbox.git.status(path)
        data = {
            "current_branch": status.current_branch,
            "ahead": status.ahead,
            "behind": status.behind,
            "branch_published": status.branch_published,
            "file_status": [
                {"file": fs.file, "status": fs.status}
                for fs in (status.file_status or [])
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(e)


def sandbox_git_commit(
    path: str,
    files: list[str],
    message: str,
    author: str,
    email: str,
    sandbox_id: str = "",
) -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        sandbox.git.add(path, files)
        resp = sandbox.git.commit(
            path=path, message=message, author=author, email=email
        )
        return f"已提交，SHA: {resp.sha}"
    except Exception as e:
        return _err(e)


def sandbox_git_pull(
    path: str,
    username: str = "",
    password: str = "",
    sandbox_id: str = "",
) -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        kwargs: dict[str, str] = {"path": path}
        if username:
            kwargs["username"] = username
        if password:
            kwargs["password"] = password
        sandbox.git.pull(**kwargs)
        return f"已拉取 {path}"
    except Exception as e:
        return _err(e)


def sandbox_git_push(
    path: str,
    username: str = "",
    password: str = "",
    sandbox_id: str = "",
) -> str:
    try:
        sandbox = resolve_sandbox(sandbox_id or None)
        kwargs: dict[str, str] = {"path": path}
        if username:
            kwargs["username"] = username
        if password:
            kwargs["password"] = password
        sandbox.git.push(**kwargs)
        return f"已推送 {path}"
    except Exception as e:
        return _err(e)

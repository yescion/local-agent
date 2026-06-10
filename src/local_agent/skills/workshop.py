"""Skill workshop — draft in sandbox, publish to local skills/custom."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable

import frontmatter

from local_agent.integrations.skill_runtime import (
    RUNNER_FILENAME,
    _install_requirements,
    _parse_runner_output,
    get_runner_source,
)

_SKILL_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DRAFT_FILES = frozenset({"SKILL.md", "tools.py", "requirements.txt"})
_workshop_sandboxes: dict[str, Any] = {}

_rescan_hook: Callable[[], int] | None = None
_unregister_hook: Callable[[str], None] | None = None


def set_rescan_hook(fn: Callable[[], int] | None) -> None:
    global _rescan_hook
    _rescan_hook = fn


def set_unregister_hook(fn: Callable[[str], None] | None) -> None:
    global _unregister_hook
    _unregister_hook = fn


def _reload_registry() -> str:
    if _rescan_hook:
        try:
            count = _rescan_hook()
            return f"\n已热重载技能注册表（共 {count} 个技能）。"
        except Exception:
            return "\n请执行 /reload-skills 或重启会话以生效。"
    try:
        from local_agent.cli.context import get_manager

        count = get_manager().reload_skills()
        return f"\n已热重载技能注册表（共 {count} 个技能）。"
    except Exception:
        return "\n请执行 /reload-skills 以生效。"


def _unregister_in_registry(skill_id: str) -> None:
    if _unregister_hook:
        _unregister_hook(skill_id)
        return
    try:
        from local_agent.cli.context import get_manager

        for runtime in get_manager()._runtimes.values():
            if runtime.skill_registry.get_skill(skill_id):
                runtime.skill_registry.unregister(skill_id)
    except Exception:
        pass


def _get_daytona_manager():
    from local_agent.integrations.daytona_sandbox import _get_manager

    return _get_manager()


def validate_skill_id(skill_id: str) -> str | None:
    if not _SKILL_ID_RE.match(skill_id):
        return (
            "错误：技能 ID 须为小写字母开头，仅含小写字母、数字、下划线，"
            "长度 1–64，例如 my_calc_tool"
        )
    if skill_id in ("skill_studio", "daytona_sandbox", "web_search", "system_context"):
        return f"错误：技能 ID 保留不可用 — {skill_id}"
    return None


def _drafts_root(sandbox: Any) -> str:
    """User-writable draft root; never use /workspace (missing & not creatable in Daytona)."""
    try:
        home = str(sandbox.get_user_home_dir() or "").rstrip("/")
    except Exception:
        home = ""
    if home:
        return f"{home}/.local-agent/skill_drafts"
    return "/tmp/skill_drafts"


def _draft_dir(skill_id: str, sandbox: Any) -> str:
    return f"{_drafts_root(sandbox)}/{skill_id}"


def _mkdir_one(sandbox: Any, path: str, mode: str) -> None:
    try:
        sandbox.fs.create_folder(path, mode)
    except Exception as exc:
        msg = str(exc).lower()
        if "exist" in msg or "already" in msg:
            return
        raise


def _ensure_sandbox_folders(sandbox: Any, path: str, mode: str = "755") -> None:
    """Create sandbox directories including missing parents (Daytona create_folder is not recursive)."""
    norm = path.rstrip("/")
    if not norm:
        return

    is_abs = norm.startswith("/")
    segments = [part for part in norm.split("/") if part]
    current = f"/{segments[0]}" if is_abs else segments[0]
    _mkdir_one(sandbox, current, mode)

    for part in segments[1:]:
        current = f"{current}/{part}"
        _mkdir_one(sandbox, current, mode)


def _load_tools_defs(tools_py: str) -> tuple[list[dict], str | None]:
    namespace: dict[str, Any] = {"__name__": "skill_draft_tools"}
    try:
        exec(compile(tools_py, "<tools.py>", "exec"), namespace)  # noqa: S102
    except Exception as e:
        return [], f"tools.py 语法错误 — {e}"
    tool_defs = namespace.get("TOOLS") or namespace.get("tools") or []
    if not isinstance(tool_defs, list):
        return [], "tools.py 须定义 TOOLS 列表"
    for td in tool_defs:
        if not isinstance(td, dict) or "name" not in td:
            return [], "TOOLS 中每项须为含 name 字段的字典"
        fn = namespace.get(td["name"])
        if not callable(fn):
            return [], f"tools.py 缺少与 TOOLS 同名的可调用函数 — {td['name']}"
    return tool_defs, None


def _merge_skill_md(skill_md: str, skill_id: str, tool_names: list[str]) -> str:
    post = frontmatter.loads(skill_md)
    post.metadata["id"] = skill_id
    post.metadata["execution"] = "sandbox"
    post.metadata.setdefault("author", "agent")
    if tool_names:
        post.metadata["tools"] = tool_names
    post.metadata.setdefault("enabled", True)
    return frontmatter.dumps(post)


def workshop_begin(skill_id: str) -> str:
    err = validate_skill_id(skill_id)
    if err:
        return err
    try:
        mgr = _get_daytona_manager()
        defaults = mgr.get_create_defaults()
        from daytona import CreateSandboxFromSnapshotParams

        client = mgr.get_client()
        params = CreateSandboxFromSnapshotParams(
            language=defaults.get("language", "python"),
            ephemeral=True,
            auto_stop_interval=0,
            name=f"skill-workshop-{skill_id}",
            labels={"role": "skill-workshop", "skill_id": skill_id},
        )
        snapshot = defaults.get("snapshot")
        if snapshot:
            params.snapshot = snapshot
        timeout = float(defaults.get("create_timeout", 60.0))
        sandbox = client.create(params, timeout=timeout)
        mgr.set_active_sandbox(sandbox, track_turn=True)
        draft = _draft_dir(skill_id, sandbox)
        _ensure_sandbox_folders(sandbox, draft)
        _local_draft_dir(skill_id).mkdir(parents=True, exist_ok=True)
        _workshop_sandboxes[skill_id] = sandbox.id
        local_mirror = _local_draft_dir(skill_id)
        return (
            f"技能工坊沙盒已就绪（ID: {sandbox.id}）。\n"
            f"沙盒草稿: {draft}\n"
            f"本地镜像: {local_mirror}（workshop_publish 从此发布到 skills/custom/）\n"
            f"请用 workshop_write 写入 SKILL.md、tools.py，可选 requirements.txt。\n"
            f"tools.py 须声明模块级 TOOLS 列表（每项含 name/description/parameters），"
            f"且每项 name 须有同名 Python 函数；仅写 def 不会被注册。"
            f"写入后可用 workshop_test 试跑，通过再 workshop_publish。"
        )
    except Exception as e:
        return f"错误：创建工坊沙盒失败 — {e}"


def _resolve_workshop_sandbox(skill_id: str) -> Any:
    sid = _workshop_sandboxes.get(skill_id)
    if not sid:
        raise ValueError(
            f"未找到技能 {skill_id} 的工坊沙盒。请先调用 workshop_begin(skill_id=\"{skill_id}\")"
        )
    return _get_daytona_manager().resolve_sandbox(sid)


def workshop_write(skill_id: str, filename: str, content: str) -> str:
    err = validate_skill_id(skill_id)
    if err:
        return err
    name = filename.strip().lstrip("/")
    if name not in _DRAFT_FILES:
        return f"错误：仅允许写入 {_DRAFT_FILES}"
    extra = ""
    if name == "tools.py":
        _, tools_err = _load_tools_defs(content)
        if tools_err:
            return f"tools.py 校验失败：{tools_err}"
        extra = "（tools.py 结构校验通过）"

    local_path = _mirror_draft_file(skill_id, name, content)
    sandbox_note = ""
    try:
        sandbox = _resolve_workshop_sandbox(skill_id)
        remote_path = f"{_draft_dir(skill_id, sandbox)}/{name}"
        sandbox.fs.upload_file(content.encode("utf-8"), remote_path)
        sandbox_note = f"沙盒 {remote_path}、"
    except Exception as exc:
        sandbox_note = f"沙盒未同步（{exc}）、"

    return f"已写入 {sandbox_note}本地镜像 {local_path}{extra}"


def workshop_read(skill_id: str, filename: str) -> str:
    err = validate_skill_id(skill_id)
    if err:
        return err
    name = filename.strip().lstrip("/")
    if name not in _DRAFT_FILES:
        return f"错误：仅允许读取 {_DRAFT_FILES}"
    local_path = _local_draft_dir(skill_id) / name
    if local_path.is_file():
        return local_path.read_text(encoding="utf-8")

    try:
        sandbox = _resolve_workshop_sandbox(skill_id)
        path = f"{_draft_dir(skill_id, sandbox)}/{name}"
        data = sandbox.fs.download_file(path)
        text = data.decode("utf-8", errors="replace")
        _mirror_draft_file(skill_id, name, text)
        return text
    except Exception as e:
        return f"错误：读取草稿失败 — {e}"


def workshop_test(skill_id: str, tool_name: str, args_json: str = "{}") -> str:
    err = validate_skill_id(skill_id)
    if err:
        return err
    if not tool_name.strip():
        return "错误：tool_name 不能为空"
    try:
        kwargs = json.loads(args_json) if args_json.strip() else {}
        if not isinstance(kwargs, dict):
            return "错误：args_json 须为 JSON 对象"
    except json.JSONDecodeError as e:
        return f"错误：args_json 解析失败 — {e}"

    try:
        sandbox = _resolve_workshop_sandbox(skill_id)
        draft = _draft_dir(skill_id, sandbox)
        tools_text = sandbox.fs.download_file(f"{draft}/tools.py").decode("utf-8")
        tool_defs, tools_err = _load_tools_defs(tools_text)
        if tools_err:
            return tools_err
        if tool_name not in {td["name"] for td in tool_defs}:
            return f"错误：tools.py 中未定义工具 — {tool_name}"

        remote_dir = draft
        sandbox.fs.upload_file(
            get_runner_source().encode("utf-8"),
            f"{remote_dir}/{RUNNER_FILENAME}",
        )
        install_err = _install_requirements(sandbox, remote_dir)
        if install_err:
            return install_err

        args_path = f"{remote_dir}/_test_args.json"
        sandbox.fs.upload_file(
            json.dumps(kwargs, ensure_ascii=False).encode("utf-8"),
            args_path,
        )
        cmd = (
            f"python {remote_dir}/{RUNNER_FILENAME} "
            f"--skill-dir {remote_dir} --tool {tool_name} --args-file {args_path}"
        )
        mgr = _get_daytona_manager()
        exec_timeout = int(mgr.get_config().get("exec_timeout", 120))
        resp = sandbox.process.exec(cmd, timeout=max(1, exec_timeout))
        return _parse_runner_output(mgr.format_exec_response(resp))
    except Exception as e:
        return f"错误：沙盒测试失败 — {e}"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _custom_skills_dir() -> Path:
    return _project_root() / "skills" / "custom"


def _data_dir() -> Path:
    try:
        from local_agent.config.loader import load_settings

        return Path(load_settings().app.data_dir).resolve()
    except Exception:
        return _project_root() / "data"


def _local_draft_dir(skill_id: str) -> Path:
    """Host-side draft mirror; publish reads here so it never depends on sandbox lifetime."""
    return _data_dir() / "skill_drafts" / skill_id


def _mirror_draft_file(skill_id: str, filename: str, content: str) -> Path:
    draft_dir = _local_draft_dir(skill_id)
    draft_dir.mkdir(parents=True, exist_ok=True)
    path = draft_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def _mirror_draft_bytes(skill_id: str, filename: str, data: bytes) -> Path:
    draft_dir = _local_draft_dir(skill_id)
    draft_dir.mkdir(parents=True, exist_ok=True)
    path = draft_dir / filename
    path.write_bytes(data)
    return path


def _load_draft_bundle(skill_id: str) -> tuple[str, str, bytes | None] | str:
    """Load SKILL.md + tools.py (+ optional requirements) from local mirror or sandbox."""
    local = _local_draft_dir(skill_id)
    skill_path = local / "SKILL.md"
    tools_path = local / "tools.py"
    if skill_path.is_file() and tools_path.is_file():
        req_path = local / "requirements.txt"
        return (
            skill_path.read_text(encoding="utf-8"),
            tools_path.read_text(encoding="utf-8"),
            req_path.read_bytes() if req_path.is_file() else None,
        )

    try:
        sandbox = _resolve_workshop_sandbox(skill_id)
        draft = _draft_dir(skill_id, sandbox)
        skill_md = sandbox.fs.download_file(f"{draft}/SKILL.md").decode("utf-8")
        tools_py = sandbox.fs.download_file(f"{draft}/tools.py").decode("utf-8")
        try:
            requirements = sandbox.fs.download_file(f"{draft}/requirements.txt")
        except Exception:
            requirements = None
        _mirror_draft_file(skill_id, "SKILL.md", skill_md)
        _mirror_draft_file(skill_id, "tools.py", tools_py)
        if requirements is not None:
            _mirror_draft_bytes(skill_id, "requirements.txt", requirements)
        return skill_md, tools_py, requirements
    except Exception as e:
        return f"错误：读取草稿失败（需要 SKILL.md 与 tools.py）— {e}"


def _publish_skill_bundle(
    skill_id: str,
    skill_md: str,
    tools_py: str,
    requirements: bytes | None,
) -> tuple[list[str], Path] | str:
    tool_defs, tools_err = _load_tools_defs(tools_py)
    if tools_err:
        return tools_err
    tool_names = [str(td["name"]) for td in tool_defs]

    post = frontmatter.loads(skill_md)
    if post.metadata.get("id") and post.metadata["id"] != skill_id:
        return f"错误：SKILL.md 中 id={post.metadata['id']} 与参数 skill_id={skill_id} 不一致"
    skill_md_final = _merge_skill_md(skill_md, skill_id, tool_names)

    target_dir = _custom_skills_dir() / skill_id
    if target_dir.exists() and (target_dir / "SKILL.md").exists():
        existing = frontmatter.loads((target_dir / "SKILL.md").read_text(encoding="utf-8"))
        if existing.metadata.get("execution") != "sandbox":
            return f"错误：已存在同名宿主机技能 {skill_id}，无法覆盖"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "SKILL.md").write_text(skill_md_final, encoding="utf-8")
    (target_dir / "tools.py").write_text(tools_py, encoding="utf-8")
    if requirements is not None:
        (target_dir / "requirements.txt").write_bytes(requirements)
    else:
        (target_dir / "requirements.txt").unlink(missing_ok=True)
    return tool_names, target_dir


def workshop_publish(skill_id: str) -> str:
    err = validate_skill_id(skill_id)
    if err:
        return err

    bundle = _load_draft_bundle(skill_id)
    if isinstance(bundle, str):
        return bundle
    skill_md, tools_py, requirements = bundle

    publish_result = _publish_skill_bundle(skill_id, skill_md, tools_py, requirements)
    if isinstance(publish_result, str):
        return publish_result
    tool_names, target_dir = publish_result

    _workshop_sandboxes.pop(skill_id, None)
    shutil.rmtree(_local_draft_dir(skill_id), ignore_errors=True)

    reload_msg = _reload_registry()

    tools_hint = "、".join(tool_names)
    return (
        f"技能「{skill_id}」已发布到 {target_dir}。\n"
        f"执行模式: sandbox（工具在沙盒中运行，每轮对话结束自动销毁沙盒）。\n"
        f"可用工具: {tools_hint}\n"
        f"注销请使用 workshop_unregister(skill_id)。{reload_msg}"
    )


def workshop_unregister(skill_id: str, delete_files: bool = True) -> str:
    """Remove a custom skill from registry and optionally delete skills/custom/{id}/."""
    err = validate_skill_id(skill_id)
    if err:
        return err

    target_dir = _custom_skills_dir() / skill_id
    skill_md_path = target_dir / "SKILL.md"
    if delete_files:
        if not skill_md_path.is_file():
            return (
                f"错误：skills/custom/{skill_id}/ 不存在或未发布。"
                "若仅需从注册表移除，可设 delete_files=false。"
            )
        try:
            custom_root = _custom_skills_dir().resolve()
            if not target_dir.resolve().is_relative_to(custom_root):
                return "错误：拒绝删除 skills/custom 以外的路径。"
            shutil.rmtree(target_dir)
        except Exception as e:
            return f"错误：删除技能目录失败 — {e}"
    elif not skill_md_path.is_file():
        _unregister_in_registry(skill_id)
        return f"技能「{skill_id}」已从注册表注销（磁盘目录不存在）。"

    _workshop_sandboxes.pop(skill_id, None)
    shutil.rmtree(_local_draft_dir(skill_id), ignore_errors=True)
    _unregister_in_registry(skill_id)

    removed = f"已删除 {target_dir}" if delete_files else "已保留磁盘文件"
    msg = f"技能「{skill_id}」已注销（{removed}）。"
    if delete_files:
        msg += _reload_registry()
    else:
        msg += "\n工具已从当前会话移除；磁盘文件保留，/reload-skills 或 scan 会重新注册。"
    return msg


def workshop_discard(skill_id: str) -> str:
    err = validate_skill_id(skill_id)
    if err:
        return err
    _workshop_sandboxes.pop(skill_id, None)
    shutil.rmtree(_local_draft_dir(skill_id), ignore_errors=True)
    return f"已丢弃技能 {skill_id} 的工坊草稿（沙盒仍由回合结束自动清理）。"

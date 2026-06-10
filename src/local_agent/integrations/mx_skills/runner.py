"""Load mx-skills scripts and run API calls with quota enforcement."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from local_agent.integrations.mx_skills.quota import MxSkillsQuota, QuotaStatus

# 与 skills/custom/mx-skills 各脚本中的默认密钥保持一致
_DEFAULT_EM_API_KEY = "em_2VALEtBj6xOmKyTABJuljLnC5KKesUCx"
# 本地代理（如 Clash 127.0.0.1:7890）对东方财富 API 常导致 SSL EOF，需直连
_MX_NO_PROXY_HOSTS = ("ai-saas.eastmoney.com", "eastmoney.com", ".eastmoney.com")

_CONFIG: dict[str, Any] = {
    "skills_root": Path("./skills/custom/mx-skills"),
    "output_dir": Path("./data/miaoxiang"),
    "api_key": "",
    "enabled": True,
    "daily_limit": 50,
    "quota_file": Path("./data/mx_skills_quota.json"),
}

_QUOTA: MxSkillsQuota | None = None
_MODULE_CACHE: dict[str, Any] = {}


def _ensure_mx_no_proxy() -> None:
    """Append eastmoney hosts to NO_PROXY so httpx/urllib bypass local system proxy."""
    for env_key in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(env_key, "")
        parts = [p.strip() for p in current.split(",") if p.strip()]
        for host in _MX_NO_PROXY_HOSTS:
            if host not in parts:
                parts.append(host)
        os.environ[env_key] = ",".join(parts)


def configure(
    *,
    skills_root: Path | str,
    output_dir: Path | str,
    quota_file: Path | str,
    api_key: str | None = None,
    enabled: bool = True,
    daily_limit: int = 50,
) -> None:
    global _QUOTA
    _ensure_mx_no_proxy()
    root = Path(skills_root).resolve()
    out = Path(output_dir).resolve()
    qfile = Path(quota_file).resolve()
    _CONFIG.update(
        {
            "skills_root": root,
            "output_dir": out,
            "quota_file": qfile,
            "api_key": (
                api_key or os.environ.get("EM_API_KEY") or _DEFAULT_EM_API_KEY
            ).strip(),
            "enabled": enabled,
            "daily_limit": daily_limit,
        }
    )
    if _CONFIG["api_key"]:
        os.environ.setdefault("EM_API_KEY", _CONFIG["api_key"])
    out.mkdir(parents=True, exist_ok=True)
    _QUOTA = MxSkillsQuota(
        quota_file=qfile,
        daily_limit=daily_limit,
        enabled=enabled,
    )


def _get_quota() -> MxSkillsQuota:
    if _QUOTA is None:
        configure(
            skills_root=_CONFIG["skills_root"],
            output_dir=_CONFIG["output_dir"],
            quota_file=_CONFIG["quota_file"],
        )
    assert _QUOTA is not None
    return _QUOTA


def quota_status() -> QuotaStatus:
    return _get_quota().status()


def skills_root() -> Path:
    return Path(_CONFIG["skills_root"])


def output_dir() -> Path:
    path = Path(_CONFIG["output_dir"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def sub_output_dir(name: str) -> Path:
    path = output_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_script(relative_path: str) -> Any:
    cache_key = relative_path.replace("\\", "/")
    if cache_key in _MODULE_CACHE:
        return _MODULE_CACHE[cache_key]

    script_path = skills_root() / relative_path
    if not script_path.is_file():
        raise FileNotFoundError(f"妙想脚本不存在: {script_path}")

    scripts_dir = str(script_path.parent.resolve())
    added_path = False
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
        added_path = True

    module_name = f"mx_skill_{cache_key.replace('/', '_').replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if not spec or not spec.loader:
        raise ImportError(f"无法加载妙想脚本: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if added_path:
            try:
                sys.path.remove(scripts_dir)
            except ValueError:
                pass

    _MODULE_CACHE[cache_key] = module
    return module


async def run_mx_tool(
    tool_name: str,
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    format_result: Callable[[Any], str] | None = None,
) -> str:
    quota = _get_quota()
    blocked = quota.check()
    if blocked:
        return blocked
    try:
        result = await coro_factory()
    except Exception as exc:
        return f"错误：妙想工具 {tool_name} 执行失败 — {exc}"

    status = quota.consume(tool_name)
    body = format_result(result) if format_result else _default_format(result)
    return f"{body}\n\n---\n{status.as_text()}"


def _default_format(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        if result.get("error"):
            return f"错误：{result['error']}"
        compact = {k: v for k, v in result.items() if k != "raw" and k != "raw_response"}
        return json.dumps(compact, ensure_ascii=False, indent=2)
    return str(result)


def format_dict_result(result: dict[str, Any]) -> str:
    if result.get("error"):
        return f"错误：{result['error']}"
    if result.get("ok") is False:
        msg = result.get("message") or result.get("error") or "请求失败"
        return f"错误：{msg}"
    lines: list[str] = []
    for key in (
        "answer",
        "content",
        "title",
        "message",
        "file_path",
        "csv_path",
        "csv_paths",
        "description_path",
        "output_path",
        "row_count",
        "row_counts",
        "share_url",
        "shareUrl",
        "pdf_file_path",
        "word_file_path",
        "attachments",
        "files",
        "references",
    ):
        if key in result and result[key] not in (None, "", [], {}):
            value = result[key]
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, indent=2)
            lines.append(f"{key}: {value}")
    if lines:
        return "\n".join(lines)
    compact = {k: v for k, v in result.items() if k not in ("raw", "raw_response", "raw_preview")}
    return json.dumps(compact, ensure_ascii=False, indent=2)


async def ask_financial_qa(question: str, deep_think: bool = False) -> dict[str, Any]:
    mod = load_script("mx-financial-assistant/scripts/generate_answer.py")
    payload = await mod._call_api(question=question, deep_think=deep_think)
    return mod.build_qa_output(question=question, deep_think=deep_think, payload=payload)


async def industry_tracker_report(query: str) -> dict[str, Any]:
    mod = load_script("industry-stock-tracker/scripts/generate_industry_stock_tracker_report.py")
    loop = asyncio.get_event_loop()
    payload = await loop.run_in_executor(None, mod._call_api, query)
    return mod.build_report_output(query=query, payload=payload)


async def earnings_review(query: str, report_date: str = "") -> dict[str, Any]:
    validate_mod = load_script("stock-earnings-review/scripts/validate_entity.py")
    period_mod = load_script("stock-earnings-review/scripts/normalize_report_period.py")
    review_mod = load_script("stock-earnings-review/scripts/call_review_api.py")

    entity = await validate_mod.validate_entity(query)
    options = await period_mod.fetch_report_options(entity)
    chosen = period_mod.choose_report_option_by_model(
        options,
        selected_report_date=report_date or None,
        strict=bool(report_date),
    )
    out_root = sub_output_dir("stock-earnings-review")
    result = await review_mod.call_review_api(
        entity,
        chosen.report_date,
        attachment_dir=str(out_root / "attachments"),
    )
    result["entity"] = {
        "name": getattr(entity, "secu_name", ""),
        "code": getattr(entity, "em_code", ""),
        "report_date": chosen.report_date,
    }
    return result

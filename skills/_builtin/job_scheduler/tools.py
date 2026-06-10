"""Host job scheduler tools — delegate to JobService."""

from __future__ import annotations

import json

from local_agent.jobs.service import get_job_service
from local_agent.tools.session_context import resolve_session_ids


TOOLS = [
    {
        "name": "job_create",
        "description": (
            "注册宿主机定时任务（持久化到 SQLite）。"
            "schedule_type: cron|once|interval；"
            "action_type: script|skill_tool|agent_prompt。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "schedule_type": {
                    "type": "string",
                    "enum": ["cron", "once", "interval"],
                    "description": "调度类型",
                },
                "action_type": {
                    "type": "string",
                    "enum": ["script", "skill_tool", "agent_prompt"],
                    "description": "执行动作类型",
                },
                "name": {"type": "string", "description": "任务名称（可选）"},
                "cron_expression": {
                    "type": "string",
                    "description": "cron 表达式（schedule_type=cron 时必填）",
                },
                "at_time": {
                    "type": "string",
                    "description": "执行时间 YYYY-MM-DD HH:MM:SS（schedule_type=once 时必填）",
                },
                "interval_minutes": {
                    "type": "integer",
                    "description": "间隔分钟（schedule_type=interval 时必填）",
                },
                "script_path": {
                    "type": "string",
                    "description": "脚本路径（action_type=script 时必填，须在 data/ 白名单内）",
                },
                "skill_id": {
                    "type": "string",
                    "description": "技能 ID（action_type=skill_tool 时必填，须 execution:host）",
                },
                "tool_name": {
                    "type": "string",
                    "description": "工具名（action_type=skill_tool 时必填）",
                },
                "tool_args_json": {
                    "type": "string",
                    "description": "工具参数 JSON 字符串，默认 {}",
                    "default": "{}",
                },
                "prompt": {
                    "type": "string",
                    "description": "Agent prompt（action_type=agent_prompt 时必填）",
                },
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID（agent_prompt 必填；其他可选）",
                },
                "thread_id": {
                    "type": "string",
                    "description": "会话线程 ID（可选；省略时自动使用当前会话，任务才会出现在 Web UI 任务列表）",
                },
                "max_runs": {
                    "type": "integer",
                    "description": "最大执行次数（重复任务，可选）",
                },
                "timeout_secs": {
                    "type": "integer",
                    "description": "单次超时秒数，默认 300",
                },
            },
            "required": ["schedule_type", "action_type"],
        },
    },
    {
        "name": "job_list",
        "description": "列出已注册的宿主机定时任务。",
        "parameters": {
            "type": "object",
            "properties": {
                "enabled_only": {
                    "type": "boolean",
                    "description": "仅显示启用中的任务",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "job_get",
        "description": "查看单个定时任务详情。",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "任务 ID"},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "job_cancel",
        "description": "停用或删除定时任务。",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "任务 ID"},
                "delete": {
                    "type": "boolean",
                    "description": "true=从数据库删除；false=仅停用",
                    "default": False,
                },
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "job_logs",
        "description": "查看定时任务执行日志。",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "任务 ID"},
                "limit": {
                    "type": "integer",
                    "description": "返回最近几条，默认 10",
                    "default": 10,
                },
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "job_parse_cron",
        "description": "解析 cron 表达式，预览接下来 N 次执行时间。",
        "parameters": {
            "type": "object",
            "properties": {
                "cron_expression": {"type": "string", "description": "cron 表达式"},
                "count": {
                    "type": "integer",
                    "description": "预览次数，默认 5",
                    "default": 5,
                },
            },
            "required": ["cron_expression"],
        },
    },
]


def job_create(
    schedule_type: str,
    action_type: str,
    name: str = "",
    cron_expression: str = "",
    at_time: str = "",
    interval_minutes: int | None = None,
    script_path: str = "",
    skill_id: str = "",
    tool_name: str = "",
    tool_args_json: str = "{}",
    prompt: str = "",
    agent_id: str = "",
    thread_id: str = "",
    max_runs: int | None = None,
    timeout_secs: int | None = None,
) -> str:
    payload: dict = {}
    if action_type == "script":
        payload["path"] = script_path
    elif action_type == "skill_tool":
        payload["skill_id"] = skill_id
        payload["tool_name"] = tool_name
        try:
            payload["arguments"] = json.loads(tool_args_json or "{}")
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"tool_args_json 无效: {e}"}, ensure_ascii=False)
    elif action_type == "agent_prompt":
        payload["prompt"] = prompt
        if agent_id:
            payload["agent_id"] = agent_id

    artifact_path = script_path or ""
    agent_id, thread_id = resolve_session_ids(
        agent_id=agent_id or None,
        thread_id=thread_id or None,
        artifact_path=artifact_path or None,
    )

    return get_job_service().create_job(
        name=name,
        schedule_type=schedule_type,
        action_type=action_type,
        action_payload=payload,
        agent_id=agent_id or None,
        thread_id=thread_id or None,
        cron_expression=cron_expression or None,
        at_time=at_time or None,
        interval_minutes=interval_minutes,
        max_runs=max_runs,
        timeout_secs=timeout_secs,
    )


def job_list(enabled_only: bool = False) -> str:
    return get_job_service().list_jobs(enabled_only=enabled_only)


def job_get(job_id: str) -> str:
    return get_job_service().get_job(job_id)


def job_cancel(job_id: str, delete: bool = False) -> str:
    return get_job_service().cancel_job(job_id, delete=delete)


def job_logs(job_id: str, limit: int = 10) -> str:
    return get_job_service().job_logs(job_id, limit=limit)


def job_parse_cron(cron_expression: str, count: int = 5) -> str:
    return get_job_service().parse_cron(cron_expression, count=count)

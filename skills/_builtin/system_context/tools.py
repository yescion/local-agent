"""System context skill tools."""

from __future__ import annotations

from local_agent.tools.system_context import (
    build_environment_context,
    get_datetime,
    get_system_info,
)

TOOLS = [
    {
        "name": "get_datetime",
        "description": "获取当前本地日期、星期、时间和时区。",
        "parameters": {"properties": {}, "required": []},
    },
    {
        "name": "get_system_info",
        "description": "获取操作系统、Python 版本、工作目录等系统环境信息。",
        "parameters": {"properties": {}, "required": []},
    },
    {
        "name": "get_environment_context",
        "description": "获取完整环境上下文，包含当前时间和系统状态。",
        "parameters": {"properties": {}, "required": []},
    },
]


def get_environment_context() -> str:
    return build_environment_context()

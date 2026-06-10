"""Environment context helpers — current time and system state."""

from __future__ import annotations

import locale
import os
import platform
import sys
from datetime import datetime

_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def get_datetime() -> str:
    now = datetime.now().astimezone()
    weekday = _WEEKDAYS[now.weekday()]
    tz = now.tzname() or "本地时区"
    return (
        f"当前时间: {now.strftime('%Y年%m月%d日')} {weekday} "
        f"{now.strftime('%H:%M:%S')} ({tz})\n"
        f"ISO 8601: {now.isoformat(timespec='seconds')}"
    )


def get_system_info() -> str:
    lines = [
        f"操作系统: {platform.system()} {platform.release()} ({platform.machine()})",
        f"Python: {sys.version.split()[0]}",
        f"工作目录: {os.getcwd()}",
        f"进程用户: {os.environ.get('USERNAME') or os.environ.get('USER') or '未知'}",
    ]
    try:
        loc = locale.getlocale()
        if loc and loc[0]:
            lines.append(f"区域设置: {loc[0]}")
    except Exception:
        pass
    return "\n".join(lines)


def build_environment_context() -> str:
    return f"## 当前环境上下文\n\n{get_datetime()}\n\n{get_system_info()}"

"""Config commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.syntax import Syntax

from local_agent.cli.context import get_settings, reload_settings
from local_agent.config.loader import save_settings

console = Console()

CONFIG_HELP = """全局配置管理。

配置文件默认位于 config/default.yaml，可通过环境变量 LOCAL_AGENT_CONFIG 覆盖。
修改后立即生效（无需重启进程外的长期服务）。

常用键:
  llm.model          模型名称（如 ollama/qwen3.5:9b）
  llm.api_base       API 地址
  memory.enabled     是否启用记忆系统
  memory.compact_threshold  上下文压缩触发 token 阈值

示例:
  local-agent config show
  local-agent config set llm.model ollama/qwen3.5:9b
  local-agent config set memory.enabled false
"""

app = typer.Typer(help=CONFIG_HELP, no_args_is_help=True)


@app.command("show", help="以 JSON 格式显示当前全部配置项。")
def show_config() -> None:
    settings = get_settings()
    console.print(Syntax(settings.model_dump_json(indent=2), "json"))


@app.command("set", help="设置配置项并写回 YAML 文件（支持点号路径）。")
def set_config(
    key: str = typer.Argument(..., help="点号分隔的配置键，如 llm.model、memory.enabled"),
    value: str = typer.Argument(..., help="配置值（自动识别 bool/int/float/字符串）"),
) -> None:
    settings = get_settings()
    parts = key.split(".")
    data = settings.model_dump()
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    # simple type coercion
    if value.lower() in ("true", "false"):
        node[parts[-1]] = value.lower() == "true"
    elif value.isdigit():
        node[parts[-1]] = int(value)
    else:
        try:
            node[parts[-1]] = float(value)
        except ValueError:
            node[parts[-1]] = value
    from local_agent.config.models import Settings

    updated = Settings.model_validate(data)
    save_settings(updated, get_settings_path())
    reload_settings()
    console.print(f"[green]已设置 {key} = {value}[/green]")


def get_settings_path():
    import os
    from pathlib import Path

    return Path(os.environ.get("LOCAL_AGENT_CONFIG", "config/default.yaml"))

"""Typer CLI application."""

from __future__ import annotations

import typer

from local_agent.cli.commands import agent, artifact, config, memory, skill, web
from local_agent.cli.commands.chat import CHAT_HELP, chat

ROOT_HELP = """可扩展、可配置、本地优先的 Python AI Agent 框架。

常用流程:
  agent list              查看 Agent 列表（#1 为最新）
  chat                    进入交互对话（默认继续最近 Agent）
  chat --new              新建 Agent 并开始对话
  chat --agent 3 -m "…"   指定 Agent 单轮问答

命令组:
  agent    Agent 实例与会话记录（L0 原始对话）
  chat     交互对话（REPL 或单轮 -m）
  skill    技能注册与管理
  memory   长期记忆调试（L1/L2 结构化记忆）
  artifact Agent 产物文件
  config   全局配置查看与修改
  web      启动 Web UI 图形界面

示例:
  local-agent agent create --name 研究员 --skills web_search
  local-agent agent history show 1 --agent 3
  local-agent skill list
  local-agent memory show 3
  local-agent config show
  local-agent web
"""

app = typer.Typer(
    name="local-agent",
    help=ROOT_HELP,
    no_args_is_help=True,
)

app.command("chat", help=CHAT_HELP)(chat)
app.add_typer(agent.app, name="agent")
app.add_typer(skill.app, name="skill")
app.add_typer(config.app, name="config")
app.add_typer(memory.app, name="memory")
app.add_typer(artifact.app, name="artifact")
app.add_typer(web.app, name="web")

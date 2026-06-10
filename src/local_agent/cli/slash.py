"""REPL slash command handler."""

from __future__ import annotations

from rich.console import Console

from local_agent.agent.manager import AgentManager
from local_agent.agent.runtime import AgentRuntime
from local_agent.cli.artifacts_display import format_artifact_summary, print_artifact_list
from local_agent.cli.history_display import print_conversation_history, print_thread_list


class SlashCommandHandler:
    def __init__(
        self,
        runtime: AgentRuntime,
        manager: AgentManager,
        console: Console | None = None,
    ) -> None:
        self.runtime = runtime
        self.manager = manager
        self.console = console or Console()
        self.should_exit = False

    async def handle(self, user_input: str) -> bool:
        parts = user_input.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/help": self._help,
            "/skills": self._skills,
            "/reload-skills": self._reload_skills,
            "/tools": self._tools,
            "/history": self._history,
            "/history-list": self._history_list,
            "/history-load": self._history_load,
            "/artifacts": self._artifacts,
            "/persona": self._persona,
            "/context": self._context,
            "/compact": self._compact,
            "/start-loop": self._start_loop,
            "/stop-loop": self._stop_loop,
            "/exit": self._exit,
            "/quit": self._exit,
        }
        handler = handlers.get(cmd)
        if handler:
            if cmd == "/compact":
                await self._compact(arg)
            else:
                handler(arg)
            return True
        if cmd.startswith("/"):
            self.console.print(f"[red][SYSTEM] 未知命令: {cmd}，输入 /help 查看帮助[/red]")
            return True
        return False

    def _help(self, _arg: str) -> None:
        self.console.print(
            "\n[cyan][COMMANDS][/cyan]\n"
            "  /skills          列出可用 skill\n"
            "  /reload-skills   热重载技能（SKILL.md / tools.py）\n"
            "  /tools           列出已注册工具\n"
            "  /help            显示帮助\n"
            "  /history [N]     查看当前会话记录（默认全部，N=最近 N 轮）\n"
            "  /history-list    列出历史会话\n"
            "  /history-load    加载历史会话 (/history-load <序号|id>)\n"
            "  /artifacts       查看当前会话产物列表\n"
            "  /persona         显示当前人设 / active skill\n"
            "  /context         显示 token 用量估算\n"
            "  /compact         手动触发上下文压缩\n"
            "  /start-loop      启动后台循环 (/start-loop <prompt> <mins>)\n"
            "  /stop-loop       停止后台循环\n"
            "  /exit            退出 REPL"
        )

    def _skills(self, _arg: str) -> None:
        skills = self.runtime.skill_registry.list_skills()
        names = [s.id for s in skills]
        self.console.print(f"[cyan][SYSTEM] Skills:[/cyan] {names}")

    def _reload_skills(self, _arg: str) -> None:
        count = self.runtime.reload_skills()
        skills = self.runtime.skill_registry.list_skills()
        names = [s.id for s in skills]
        self.console.print(
            f"[cyan][SYSTEM] 已热重载 {count} 个技能[/cyan]: {names}"
        )

    def _tools(self, _arg: str) -> None:
        tools = self.runtime.tool_router.list_tool_names()
        self.console.print(f"[cyan][SYSTEM] Tools:[/cyan] {tools}")

    def _parse_history_limit(self, arg: str) -> int | None:
        if not arg.strip():
            return None
        try:
            limit = int(arg.strip())
        except ValueError:
            self.console.print("[red][SYSTEM] 用法: /history [N]（N 为正整数）[/red]")
            raise ValueError from None
        if limit <= 0:
            self.console.print("[red][SYSTEM] N 必须大于 0[/red]")
            raise ValueError
        return limit

    def _history(self, arg: str) -> None:
        try:
            limit = self._parse_history_limit(arg)
        except ValueError:
            return
        preview = self.manager.get_thread_preview(self.runtime.thread_id)
        threads = self.manager.list_threads(self.runtime.agent.id)
        thread = next((t for t in threads if t.id == self.runtime.thread_id), None)
        title = thread.title if thread else "(无标题)"
        print_conversation_history(
            self.console,
            self.runtime.messages,
            limit=limit,
            title=f"{title} · {preview.turn_count} 轮",
        )

    def _history_list(self, _arg: str) -> None:
        count = print_thread_list(
            self.console,
            self.manager,
            self.runtime.agent.id,
            current_thread_id=self.runtime.thread_id,
        )
        if not count:
            self.console.print("[cyan][SYSTEM] 无历史会话[/cyan]")
            return
        self.console.print("[dim]使用 /history-load <序号> 切换会话[/dim]")
        agents = self.manager.list_agents()
        if len(agents) > 1:
            self.console.print(
                "[dim]其他 Agent 请运行: local-agent agent list[/dim]"
            )

    def _artifacts(self, _arg: str) -> None:
        artifacts = self.manager.list_artifacts(
            self.runtime.agent.id, thread_id=self.runtime.thread_id
        )
        threads = self.manager.list_threads(self.runtime.agent.id)
        thread = next(
            (t for t in threads if t.id == self.runtime.thread_id), None
        )
        title = thread.title if thread and thread.title else "当前会话"
        print_artifact_list(self.console, artifacts, title=title)

    def _history_load(self, arg: str) -> None:
        if not arg:
            self.console.print("[red][SYSTEM] 用法: /history-load <序号|id>[/red]")
            return
        threads = self.manager.list_threads(self.runtime.agent.id)
        matched = self.manager.resolve_thread(self.runtime.agent.id, arg.strip())
        if not matched:
            self.console.print(f"[red][SYSTEM] 未找到会话: {arg}[/red]")
            return
        idx = next((i for i, t in enumerate(threads, start=1) if t.id == matched.id), "?")
        if self.runtime.load_history(matched.id):
            title = matched.title or "(无标题)"
            self.console.print(f"[cyan][SYSTEM] 已加载会话 #{idx} — {title}[/cyan]")
            print_conversation_history(
                self.console,
                self.runtime.messages,
                limit=10,
                truncate=200,
                title=f"最近记录 · {title}",
            )
        else:
            self.console.print("[red][SYSTEM] 加载失败[/red]")

    def _persona(self, _arg: str) -> None:
        p = self.runtime.agent.persona
        self.console.print(f"[cyan][SYSTEM] Persona:[/cyan] {p.role} — {p.tone}")
        if self.runtime.agent.active_skill_id:
            self.console.print(
                f"[cyan][SYSTEM] Active Skill:[/cyan] {self.runtime.agent.active_skill_id}"
            )

    def _context(self, _arg: str) -> None:
        tokens = self.runtime.estimate_tokens()
        window = self.runtime.settings.agent.context_window
        pct = tokens / window * 100 if window else 0
        self.console.print(
            f"[cyan][SYSTEM] Estimated tokens:[/cyan] {tokens} / {window} ({pct:.1f}%)"
        )

    async def _compact(self, _arg: str) -> None:
        self.runtime.messages = await self.runtime.compactor.compact(
            self.runtime.messages, self.runtime.agent.active_skill_content
        )
        self.console.print("[cyan][SYSTEM] 上下文已压缩[/cyan]")

    def _start_loop(self, arg: str) -> None:
        parts = arg.rsplit(maxsplit=1)
        if len(parts) < 2:
            self.console.print(
                "[red][SYSTEM] 用法: /start-loop <prompt> <interval_mins>[/red]"
            )
            return
        try:
            interval = int(parts[1])
        except ValueError:
            self.console.print("[red][SYSTEM] interval 必须是整数（分钟）[/red]")
            return
        prompt = parts[0]

        def on_start(p: str, mins: int) -> None:
            self.console.print(f"\n[cyan][SYSTEM] Loop started: '{p}' every {mins} min(s).[/cyan]")

        self.runtime.background_loop.start(
            prompt=prompt,
            interval_mins=interval,
            run_fn=self.runtime.run_background_iteration,
            on_start=on_start,
        )

    def _stop_loop(self, _arg: str) -> None:
        self.runtime.background_loop.stop()
        self.console.print("[cyan][SYSTEM] Loop stopped.[/cyan]")

    def _exit(self, _arg: str) -> None:
        self.should_exit = True

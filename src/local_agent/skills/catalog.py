"""Extract skill usage hints for manage_skills(catalog) from SKILL.md bodies."""

from __future__ import annotations

# Sections surfaced in catalog browse (add headings here when new skills need them).
CATALOG_SECTION_HEADINGS: tuple[str, ...] = (
    "## 何时使用",
    "## 工作流程",
    "## tools.py 规范",
    "## 执行环境",
    "## 沙盒释放（必须）",
    "## 限制",
    "## 强制规则",
    "## 网络访问限制",
    "## 配额限制",
    "## 环境配置",
    "## 注意",
    "## 自动注入",
)

SANDBOX_RELEASE_HINT = """\
## 沙盒释放（必须）
沙盒按运行时间计费。完成本技能相关操作后（含产物下载、结果确认），**必须立即停掉并释放沙盒**，不要闲置等待回合结束：
1. 若创建过持久会话，先 `sandbox_session_delete`
2. 再 `sandbox_delete` 彻底删除（仅临时停用可用 `sandbox_stop`）
3. `execution:sandbox` 技能：用 `sandbox_delete(execution_skill_id="技能id")` 释放该技能执行沙盒
4. `daytona_sandbox` 手动创建的沙盒：对 `sandbox_create` 返回的 ID 调用 `sandbox_delete`
5. 技能工坊：`workshop_publish` / `workshop_discard` 后，对工坊沙盒调用 `sandbox_delete`
须先加载 `daytona_sandbox` 技能。系统回合结束也会自动清理，但主动释放可避免闲置计费。"""

SANDBOX_SKILL_IDS: frozenset[str] = frozenset({"daytona_sandbox", "skill_studio"})

SKILL_STUDIO_TOOLS_HINT = """\
## tools.py（创建技能必读）
tools.py **必须**在模块顶层声明 `TOOLS` 列表；每项为含 `name`、`description`、`parameters` 的字典，且 `name` 须有同名可调用函数。仅写 `def my_tool(...)` 不会被注册。
```python
TOOLS = [{
    "name": "my_tool",
    "description": "工具说明",
    "parameters": {
        "properties": {"query": {"type": "string", "description": "输入"}},
        "required": ["query"],
    },
}]

def my_tool(query: str) -> str:
    return f"结果: {query}"
```
流程：workshop_begin → workshop_write(SKILL.md) → workshop_write(tools.py) → workshop_test → workshop_publish → sandbox_delete"""


def is_sandbox_related_skill(*, skill_id: str, execution: str) -> bool:
    """Whether a skill uses Daytona sandboxes and should show release instructions."""
    return execution == "sandbox" or skill_id in SANDBOX_SKILL_IDS


def extract_catalog_sections(content: str, *, max_chars_per_section: int = 500) -> str:
    """Pull usage / environment / constraint sections from skill markdown."""
    if not content.strip():
        return ""
    parts: list[str] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        matched = next(
            (h for h in CATALOG_SECTION_HEADINGS if line.strip() == h or line.startswith(h)),
            None,
        )
        if matched:
            body_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("## "):
                body_lines.append(lines[i])
                i += 1
            body = "\n".join(body_lines).strip()
            if body:
                if len(body) > max_chars_per_section:
                    body = body[:max_chars_per_section].rstrip() + "…"
                parts.append(f"{matched}\n{body}")
        else:
            i += 1
    return "\n\n".join(parts)

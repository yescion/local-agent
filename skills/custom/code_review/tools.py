"""Code review skill tools."""

TOOLS = [
    {
        "name": "review_code",
        "description": "对 Python 代码片段进行快速审查，返回问题列表。",
        "parameters": {
            "properties": {
                "code": {"type": "string", "description": "要审查的 Python 代码"},
            },
            "required": ["code"],
        },
    },
]


def review_code(code: str) -> str:
    issues = []
    if "eval(" in code or "exec(" in code:
        issues.append("🔴 严重: 使用了 eval/exec，存在代码注入风险")
    if "import *" in code:
        issues.append("🟡 建议: 避免 from module import *")
    if len(code.splitlines()) > 200:
        issues.append("🟢 可选: 函数/文件过长，考虑拆分")
    if not issues:
        issues.append("🟢 未发现明显问题，建议结合单元测试进一步验证")
    return "\n".join(issues)

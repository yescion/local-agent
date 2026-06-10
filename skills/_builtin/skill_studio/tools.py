"""Skill workshop tools — draft in sandbox, publish agent-created skills locally."""

from __future__ import annotations

from local_agent.skills import workshop

TOOLS = [
    {
        "name": "workshop_begin",
        "description": (
            "为指定 skill_id 创建技能工坊沙盒与草稿目录。"
            "后续用 workshop_write 写入 SKILL.md、tools.py（须含 TOOLS 列表与同名函数）等。"
            "发布或放弃后须 sandbox_delete 释放工坊沙盒。"
        ),
        "parameters": {
            "properties": {
                "skill_id": {
                    "type": "string",
                    "description": "新技能 ID，小写字母开头，仅含 a-z0-9_，如 my_helper",
                },
            },
            "required": ["skill_id"],
        },
    },
    {
        "name": "workshop_write",
        "description": (
            "向工坊草稿写入 SKILL.md、tools.py 或 requirements.txt。"
            "tools.py 必须含模块级 TOOLS 列表（name/description/parameters）及同名函数，"
            "写入时自动校验结构。"
        ),
        "parameters": {
            "properties": {
                "skill_id": {"type": "string", "description": "技能 ID"},
                "filename": {
                    "type": "string",
                    "description": "文件名：SKILL.md / tools.py / requirements.txt",
                },
                "content": {"type": "string", "description": "文件完整内容"},
            },
            "required": ["skill_id", "filename", "content"],
        },
    },
    {
        "name": "workshop_read",
        "description": "读取工坊沙盒中当前草稿文件内容。",
        "parameters": {
            "properties": {
                "skill_id": {"type": "string", "description": "技能 ID"},
                "filename": {
                    "type": "string",
                    "description": "文件名：SKILL.md / tools.py / requirements.txt",
                },
            },
            "required": ["skill_id", "filename"],
        },
    },
    {
        "name": "workshop_test",
        "description": (
            "在工坊沙盒内安装 requirements.txt（若有）并试跑指定工具。"
            "args_json 为传给工具的 JSON 对象字符串，默认 {}。"
        ),
        "parameters": {
            "properties": {
                "skill_id": {"type": "string", "description": "技能 ID"},
                "tool_name": {"type": "string", "description": "tools.py 中定义的工具名"},
                "args_json": {
                    "type": "string",
                    "description": '工具参数字典 JSON，如 {"query": "hello"}',
                },
            },
            "required": ["skill_id", "tool_name"],
        },
    },
    {
        "name": "workshop_publish",
        "description": (
            "在宿主机将工坊草稿发布到 skills/custom/{skill_id}/（不受 write_file 路径限制），"
            "自动标记 execution:sandbox，并热重载技能注册表。"
            "从本地草稿镜像读取，沙盒销毁后仍可发布。"
        ),
        "parameters": {
            "properties": {
                "skill_id": {"type": "string", "description": "技能 ID"},
            },
            "required": ["skill_id"],
        },
    },
    {
        "name": "workshop_discard",
        "description": (
            "放弃当前工坊沙盒绑定（不发布）。"
            "完成后须 sandbox_delete 立即释放工坊沙盒。"
        ),
        "parameters": {
            "properties": {
                "skill_id": {"type": "string", "description": "技能 ID"},
            },
            "required": ["skill_id"],
        },
    },
    {
        "name": "workshop_unregister",
        "description": (
            "注销已发布到 skills/custom/ 的自创技能：从注册表移除工具并热重载。"
            "默认同时删除磁盘目录（不受 write_file 路径限制）；"
            "delete_files=false 时仅注销注册表、保留文件。"
        ),
        "parameters": {
            "properties": {
                "skill_id": {"type": "string", "description": "要注销的技能 ID"},
                "delete_files": {
                    "type": "boolean",
                    "description": "是否删除 skills/custom/{skill_id}/，默认 true",
                },
            },
            "required": ["skill_id"],
        },
    },
]


def workshop_begin(skill_id: str) -> str:
    return workshop.workshop_begin(skill_id)


def workshop_write(skill_id: str, filename: str, content: str) -> str:
    return workshop.workshop_write(skill_id, filename, content)


def workshop_read(skill_id: str, filename: str) -> str:
    return workshop.workshop_read(skill_id, filename)


def workshop_test(skill_id: str, tool_name: str, args_json: str = "{}") -> str:
    return workshop.workshop_test(skill_id, tool_name, args_json)


def workshop_publish(skill_id: str) -> str:
    return workshop.workshop_publish(skill_id)


def workshop_discard(skill_id: str) -> str:
    return workshop.workshop_discard(skill_id)


def workshop_unregister(skill_id: str, delete_files: bool = True) -> str:
    return workshop.workshop_unregister(skill_id, delete_files=delete_files)

---
id: skill_studio
name: 技能工坊
version: 1.0.0
description: 在 Daytona 沙盒中创建、测试 Agent 自创技能；tools.py 须声明 TOOLS 列表与同名函数，验证通过后 workshop_publish 到 skills/custom；用完须 sandbox_delete 释放
author: builtin
tags: [skill, workshop, sandbox, agent]
tools:
  - workshop_begin
  - workshop_write
  - workshop_read
  - workshop_test
  - workshop_publish
  - workshop_discard
  - workshop_unregister
enabled: true
---

# 技能工坊

用于让 Agent **在沙盒里开发技能**，测试通过后**拉回本地注册**。已发布的自创技能与系统技能一样出现在工具箱中，唯一区别是 `execution: sandbox`（每次调用在临时沙盒中执行，回合结束销毁，不保留环境）。

## 工作流程

```
1. workshop_begin(skill_id)           # 创建工坊沙盒与草稿目录
2. workshop_write(..., "SKILL.md")    # 写入技能说明（frontmatter 含 name/description）
3. workshop_write(..., "tools.py")    # 写入 TOOLS 列表与 Python 函数
4. workshop_write(..., "requirements.txt")  # 可选依赖
5. workshop_test(skill_id, tool_name, args_json)  # 沙盒内试跑
6. workshop_publish(skill_id)         # 拉回 skills/custom/{id}/ 并热重载
7. workshop_unregister(skill_id)      # 注销已发布技能（删目录 + 热重载）
```

## tools.py 规范

```python
TOOLS = [
    {
        "name": "my_tool",
        "description": "工具说明",
        "parameters": {
            "properties": {
                "query": {"type": "string", "description": "输入"},
            },
            "required": ["query"],
        },
    },
]

def my_tool(query: str) -> str:
    return f"结果: {query}"
```

- 模块顶层避免副作用（不要连接外部服务、不要读写宿主机路径）
- 依赖写在 `requirements.txt`，每次执行会重新 `pip install`（较慢，无磁盘残留费用）

## SKILL.md 规范

发布时会自动设置：

- `execution: sandbox`
- `author: agent`
- `tools:` 从 tools.py 同步

`id` 须与 `skill_id` 一致（小写字母开头，仅 `a-z0-9_`）。

## 发布后

- 用 `manage_skills(action="catalog")` 查看，与其他技能相同
- 用 `manage_skills(action="load", name="技能id")` 加载完整文档
- 注销：`workshop_unregister("技能id")`（默认删除 `skills/custom/技能id/` 并热重载；`delete_files=false` 仅注销注册表）

## 沙盒释放（必须）

工坊开发或测试完成后，**必须立即释放工坊沙盒**（须已加载 `daytona_sandbox`）：

```
workshop_publish(skill_id)   # 或 workshop_discard(skill_id)
sandbox_delete()             # 对 workshop_begin 创建的沙盒 ID 释放
```

已发布的 `execution:sandbox` 技能，每次调用其工具后同样须在完成下载等收尾后执行 `sandbox_delete(execution_skill_id="技能id")`。

## 注意

- 工坊沙盒与执行沙盒均为 **ephemeral**；回合结束也会自动清理，但主动释放可避免闲置计费
- 需要访问内网/金融 API 的技能应走宿主机内置技能，不适合自创沙盒技能
- 定时任务请用内置 `job_scheduler` 技能（`job_create`）
- 开发复杂逻辑时可配合 `daytona_sandbox` 技能做额外实验

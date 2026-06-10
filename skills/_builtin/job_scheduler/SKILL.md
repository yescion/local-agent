---
id: job_scheduler
name: 宿主机定时任务
version: 1.0.0
description: 在宿主机注册持久化定时任务（cron/单次/间隔），可执行脚本或调用 execution:host 技能工具；agent 进程运行期间生效
author: builtin
tags: [cron, schedule, job, host]
tools:
  - job_create
  - job_list
  - job_get
  - job_cancel
  - job_logs
  - job_parse_cron
enabled: true
---

# 宿主机定时任务调度器

系统内置调度器，任务写入 SQLite，**在宿主机执行**，可访问内网/金融 API。

## 何时使用

- 需要每隔 N 分钟/按 cron 周期执行任务（agent 会话结束后仍继续，只要 `local-agent` 进程在运行）
- 定时运行 `data/` 或 `artifacts/` 下的 Python 脚本
- 定时调用宿主机技能（如 `loc_kline` 的 `fetch_kline`）

## 工作流程

```
1. job_parse_cron("*/5 * * * *")     # 可选：预览 cron 时间
2. 将脚本写入 data/artifacts/.../task.py（write_file）
3. job_create(
     schedule_type="cron",
     cron_expression="*/5 * * * *",
     action_type="script",
     script_path="data/artifacts/.../task.py",
     agent_id="...",   # 可选：省略时自动使用当前会话
     thread_id="...",  # 可选：省略时自动使用当前会话（Web UI 任务列表依赖此项）
   )
4. job_list() / job_logs(job_id) 查看状态
5. job_cancel(job_id) 停止；job_cancel(job_id, delete=true) 删除
```

## 调度类型 (schedule_type)

| 类型 | 说明 | 必填参数 |
|------|------|----------|
| `cron` | 标准 5 字段 cron | `cron_expression` |
| `once` | 指定时间执行一次 | `at_time`（YYYY-MM-DD HH:MM:SS） |
| `interval` | 固定间隔重复 | `interval_minutes` |

## 动作类型 (action_type)

| 类型 | 说明 | 参数 |
|------|------|------|
| `script` | 执行白名单路径脚本 | `script_path`（须在 `data/` 等白名单目录内，支持 .py/.ps1） |
| `skill_tool` | 调用宿主机技能工具 | `skill_id`, `tool_name`, `tool_args_json` |
| `agent_prompt` | 触发一轮后台 Agent | `prompt`, `agent_id`, 可选 `thread_id` |

## 会话绑定

- 在 Agent 对话中创建任务时，`agent_id` / `thread_id` **可省略**，系统会自动使用当前会话
- 也可调用 `get_session_context` 显式获取当前会话 ID
- 未绑定 `thread_id` 的任务不会在 Web UI 会话任务列表中显示（但调度器仍会执行）

## 限制

- 仅 `execution: host` 技能可被 `skill_tool` 调用
- 脚本路径须在 `data/` 或 `tools.write_paths` 白名单内
- 调度器随 `local-agent` 进程启停；关闭终端后任务停止（长期后台需配合系统计划任务）

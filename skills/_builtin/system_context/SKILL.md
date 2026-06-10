---
id: system_context
name: 环境上下文
version: 1.0.0
description: 提供当前系统时间、星期和运行环境信息；每轮对话会自动注入环境上下文，也可 load 后调用工具
author: builtin
tags: [system, datetime, context]
tools: [get_datetime, get_system_info, get_environment_context]
enabled: true
---

# 环境上下文技能

## 何时使用
- 回答涉及「今天」「现在」「本周」「最近交易日」等时间相关问题时
- 需要确认当前系统时间、时区、工作目录或操作系统信息时
- 无需为此专门搜索网络 — 直接使用已注入的环境上下文或调用本技能工具

## 自动注入
Agent 在每次用户消息前会自动注入最新的环境上下文（时间 + 系统状态），请优先使用这些信息。

## 工具说明
| 工具 | 用途 |
|------|------|
| `get_datetime` | 获取当前本地日期、星期、时间和时区 |
| `get_system_info` | 获取操作系统、Python 版本、工作目录等 |
| `get_environment_context` | 获取完整环境上下文（时间 + 系统信息） |

## 注意事项
- 时间均为 Agent 运行环境的本地时间，非网络时间
- A 股等市场的「最近交易日」需结合当前星期自行推算（周末/节假日无交易）

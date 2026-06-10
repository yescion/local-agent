---
id: code_review
name: 代码审查
version: 1.0.0
description: 对 Python 代码进行质量审查，检查风格、安全与性能问题
author: user
tags: [code, review, python]
tools: [review_code]
enabled: true
---

# 代码审查技能

## 何时使用
当用户提交代码片段或请求 code review 时激活本技能。

## 工作流程
1. 阅读代码结构与依赖
2. 按 PEP8、安全、性能维度审查
3. 输出分级问题列表与修改建议

## 输出格式
- 🔴 严重 / 🟡 建议 / 🟢 可选优化

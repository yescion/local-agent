---
id: web_search
name: 网络搜索助手
version: 1.0.0
description: 帮助用户搜索和整理网络信息
author: builtin
tags: [search, web]
tools: [web_search, fetch_web_page]
enabled: true
---

# 网络搜索技能

## 何时使用
当用户需要查找实时信息、调研技术方案或整理网络资料时激活。

## 前置条件
须先通过 `manage_skills(action="load", name="web_search")` 加载本技能，之后 `web_search` 工具才会出现在可用工具列表中。

## 工作流程
1. 明确搜索目标和关键词，关键词不可以包含引号
2. 调用 `web_search` 工具获取搜索结果
3. 若摘要信息不足或需要核实细节，用 `fetch_web_page` 抓取搜索结果中的具体链接正文
4. 整理结果，标注来源和可信度，给出简要结论

## 执行环境

`web_search` 与 `fetch_web_page` **在宿主机进程内执行**，可访问外网，不要放到 Daytona 沙盒里重试。

## 工具说明
- `web_search`：返回标题、摘要和链接，适合发现信息来源
- `fetch_web_page`：抓取 URL 并解析内容（HTML / JSON / RSS·XML / PDF / DOCX / XLSX / EPUB / YAML / CSV / Markdown 等），**不要**在思考中说「打开链接」却不调用此工具

## 输出格式
- 先给出简要结论
- 再列出要点和参考来源

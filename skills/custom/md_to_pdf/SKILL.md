---
author: agent
enabled: true
execution: sandbox
id: md_to_pdf
tools:
- md_to_pdf
---

# md_to_pdf · Markdown 转中文PDF

将 Markdown 内容或文件转换为格式美观的 PDF 文档，支持中文排版。

## 何时使用
- 需要把分析报告、总结、文档从 Markdown 转为 PDF 文件
- 需要带中文内容的 PDF 输出（自动处理中文字体编码）

## 执行环境
Daytona 沙盒（临时）。每次调用自动安装中文字体，确保中文正常渲染。

## 注意事项
- 沙盒临时创建，用完自动销毁
- 超时默认 120s，大文档可适当增大
- 输出 PDF 文件请通过 sandbox_fs_download_local 下载到本地
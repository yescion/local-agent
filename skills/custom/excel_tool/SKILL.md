---
author: agent
description: 读取、创建、修改 Excel 文件（.xlsx），支持多 Sheet、单元格操作、样式设置；用完须 sandbox_delete 释放沙盒
enabled: true
execution: sandbox
id: excel_tool
name: excel_tool
tools:
- read_excel
- create_excel
- modify_excel
---

# excel_tool · Excel 文件操作工具

支持读取、创建和修改 Excel .xlsx 文件，基于 openpyxl 引擎。

## 何时使用
- 需要读取 Excel 文件内容（按 Sheet、行、列）
- 需要创建新的 Excel 表格
- 需要修改已有 Excel 文件（更新单元格、添加行列、新建 Sheet）

## 工具
- `read_excel`: 读取 Excel 文件内容，返回指定 Sheet 的数据
- `create_excel`: 创建新的 Excel 文件，写入数据
- `modify_excel`: 修改已有 Excel 文件（更新单元格、添加 Sheet、追加行）

## 导出到宿主机（必须）

本技能在沙盒中执行，文件仅保存在沙盒内。要让用户在本地访问 Excel 文件，创建或修改后须调用 `sandbox_fs_download_local`。

**路径命名**：`create_excel` / `modify_excel` 的 `path` 须使用英文/ASCII 文件名（如 `/home/daytona/report.xlsx`），中文路径在沙盒内会出错。下载到本地时可通过 `local_path` 使用中文文件名。

```
create_excel(path="/home/daytona/sh000001_5min.xlsx", data="...")
sandbox_fs_download_local(
    remote_path="/home/daytona/sh000001_5min.xlsx",
    local_path="上证5分钟.xlsx",
    execution_skill_id="excel_tool",
)
```

需先加载 `daytona_sandbox` 技能。下载后文件会出现在会话产物目录，并自动登记为产物。

## 沙盒释放（必须）

完成 Excel 操作并下载产物后，**必须立即释放沙盒**：

```
sandbox_delete(execution_skill_id="excel_tool")
```

不要闲置等待回合结束，避免沙盒持续计费。
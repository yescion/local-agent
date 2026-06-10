---
id: daytona_sandbox
name: Daytona 隔离沙盒
version: 1.0.0
description: 通过 Daytona 沙盒安全执行命令、读写文件和 Git 操作；shell/构建/测试须在沙盒内完成；用完须 sandbox_delete 停掉释放，沙盒无法访问金融行情等外部 API
author: builtin
tags: [sandbox, daytona, security, exec]
tools:
  - sandbox_create
  - sandbox_connect
  - sandbox_list
  - sandbox_info
  - sandbox_stop
  - sandbox_delete
  - sandbox_exec
  - sandbox_code_run
  - sandbox_session_create
  - sandbox_session_exec
  - sandbox_session_delete
  - sandbox_fs_list
  - sandbox_fs_read
  - sandbox_fs_write
  - sandbox_fs_upload_local
  - sandbox_fs_download_local
  - sandbox_fs_mkdir
  - sandbox_fs_delete
  - sandbox_fs_move
  - sandbox_fs_find
  - sandbox_fs_search
  - sandbox_git_clone
  - sandbox_git_status
  - sandbox_git_commit
  - sandbox_git_pull
  - sandbox_git_push
enabled: true
---

# Daytona 隔离沙盒技能

基于 [Daytona Python SDK](https://www.daytona.io/docs/en/python-sdk/) 的隔离执行环境。须 `manage_skills(action="load", name="daytona_sandbox")` 后使用。

## 强制规则（必须严格遵守）

1. **所有 shell 命令、脚本执行、包安装、构建、测试等命令操作，只能在沙盒中执行**，使用 `sandbox_exec` 或 `sandbox_session_exec`。
2. **禁止使用宿主机 `shell` 工具**（已全局禁用）；若需运行命令，必须先确保有活动沙盒。
3. **能在沙盒中完成的操作，优先在沙盒中完成**：文件读写用 `sandbox_fs_*`，Git 用 `sandbox_git_*`，代码片段用 `sandbox_code_run`。
4. 需要操作宿主机项目文件时，先用 `sandbox_fs_upload_local` 上传到沙盒，处理后用 `sandbox_fs_download_local` 下载到产物目录。
5. **二进制文件（.xlsx、.png 等）必须用 `sandbox_fs_download_local` 导出**；`sandbox_fs_read` 仅支持 UTF-8 文本。
6. **沙盒内文件路径必须使用英文/ASCII 文件名**（如 `report.xlsx`、`output/data.csv`）。中文路径在沙盒内会出错；下载到本地后可通过 `local_path` 使用中文命名（如 `local_path="上证5分钟.xlsx"`）。
7. **execution:sandbox 技能**（如 `excel_tool`）在独立执行沙盒中运行；从其导出文件时须传 `execution_skill_id`（技能 ID）。
8. **需要访问金融行情、通达信等外部数据源的专用工具（如 `fetch_kline`）在宿主机执行**，不要放进沙盒；沙盒内无法访问这些站点。

## 网络访问限制（重要）

Daytona 沙盒按组织 [计费层级（Tier）](https://www.daytona.io/docs/en/limits/) 自动施加出站防火墙策略，详见 [Network Limits](https://www.daytona.io/docs/en/network-limits/)：

| Tier | 网络策略 |
|------|----------|
| Tier 1 & 2 | **受限**：仅可访问白名单内的基础开发服务（PyPI、npm、GitHub 等），**无法在沙盒级别覆盖** |
| Tier 3 & 4 | 默认全网访问，可用 `network_allow_list` / `network_block_all` 自定义 |

因此 Tier 1/2 沙盒**不能**访问金融数据站、通达信主机、任意自定义 API。若任务需要这类数据：

- 使用宿主机技能工具（如 `loc_kline` 的 `fetch_kline`），或
- 将数据在宿主机拉取后通过 `sandbox_fs_upload_local` 传入沙盒，或
- 升级至 Tier 3+ 并在创建沙盒时配置 `network_allow_list`（仅支持 CIDR，不支持域名）

## 配置（config/default.yaml → `daytona` 段）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `api_key` | null | API 密钥，也可用环境变量 `DAYTONA_API_KEY` |
| `api_url` / `target` | null | API 地址与区域 |
| `language` | python | 沙盒语言 |
| `snapshot` / `image` | null | 创建时使用的快照或镜像 |
| `env_vars` / `labels` | {} | 环境变量与标签 |
| `auto_stop_interval` | 5 | 空闲自动停止（分钟） |
| `ephemeral` | **true** | 临时沙盒，停止后立即删除 |
| `exec_timeout` | 120 | 命令默认超时（秒） |
| `auto_cleanup_on_turn_end` | **true** | 每轮对话结束后自动清理 |
| `cleanup_action` | **delete** | 清理方式：`delete` 或 `stop` |

`sandbox_create` 未传参数时自动使用上述默认值。

## 沙盒释放（必须）

沙盒按运行时间计费。**完成沙盒内全部操作后（含产物下载、会话收尾），必须立即停掉并释放**，不要闲置等待回合结束：

1. 若创建过持久会话，先 `sandbox_session_delete`
2. 再 `sandbox_delete` 彻底删除（仅临时停用可用 `sandbox_stop`）
3. `execution:sandbox` 技能（如 `excel_tool`）：`sandbox_delete(execution_skill_id="技能id")`
4. 任务进行中不要提前释放；全部步骤完成后再释放

系统每轮对话结束也会自动清理本轮 `sandbox_create` 创建的沙盒，但**主动释放可避免长时间闲置产生额外费用**。

若需保留沙盒跨多轮对话，须在配置中设 `auto_cleanup_on_turn_end: false` 并用 `sandbox_connect` 复用。

## 计费与自动清理

1. **默认创建 ephemeral 沙盒**，停止后自动删除。
2. **每轮用户对话结束后**，系统会对本轮 `sandbox_create` 创建的沙盒执行 `cleanup_action`（默认 delete）。

## 前置条件

安装依赖：`pip install daytona`

## 典型工作流

```
1. sandbox_create()                    # 使用配置默认值创建沙盒
2. sandbox_fs_upload_local(...)        # 将本地代码上传到沙盒（如需要）
3. sandbox_exec("pip install -r ...")  # 在沙盒内安装依赖
4. sandbox_exec("pytest")              # 在沙盒内运行测试
5. sandbox_fs_download_local("report.xlsx")  # 下载二进制结果到产物目录
6. sandbox_delete()                      # 用完立即释放沙盒
```

从 execution:sandbox 技能导出（如 excel_tool）：

```
create_excel(path="/home/daytona/sh000001_5min.xlsx", ...)   # 沙盒内用英文路径
sandbox_fs_download_local(
    remote_path="/home/daytona/sh000001_5min.xlsx",
    local_path="上证5分钟.xlsx",   # 下载到本地时可用中文文件名
    execution_skill_id="excel_tool",
)
```

需要保持 shell 状态（`cd`、环境变量等）时，使用持久会话：

```
sandbox_session_create("work")
sandbox_session_exec("work", "cd /workspace/project")
sandbox_session_exec("work", "npm test")
sandbox_session_delete("work")
```

## 工具分类

### 生命周期
| 工具 | 用途 |
|------|------|
| `sandbox_create` | 创建新沙盒并设为活动沙盒 |
| `sandbox_connect` | 连接已有沙盒 |
| `sandbox_list` | 列出沙盒 |
| `sandbox_info` | 查看沙盒详情 |
| `sandbox_stop` | 停止沙盒 |
| `sandbox_delete` | 删除沙盒 |

### 命令执行
| 工具 | 用途 |
|------|------|
| `sandbox_exec` | 执行单次 shell 命令（**主要入口**） |
| `sandbox_code_run` | 运行代码片段（Python 等） |
| `sandbox_session_create` | 创建持久 shell 会话 |
| `sandbox_session_exec` | 在会话中执行命令（保持状态） |
| `sandbox_session_delete` | 删除会话 |

### 文件系统（沙盒内）
| 工具 | 用途 |
|------|------|
| `sandbox_fs_list` | 列目录 |
| `sandbox_fs_read` | 读文件 |
| `sandbox_fs_write` | 写文件 |
| `sandbox_fs_upload_local` | 从宿主机上传文件到沙盒 |
| `sandbox_fs_download_local` | 从沙盒下载文件到宿主机产物目录（支持二进制） |
| `sandbox_fs_mkdir` | 创建目录 |
| `sandbox_fs_delete` | 删除文件/目录 |
| `sandbox_fs_move` | 移动/重命名 |
| `sandbox_fs_find` | 按内容搜索（grep） |
| `sandbox_fs_search` | 按文件名 glob 搜索 |

### Git（沙盒内）
| 工具 | 用途 |
|------|------|
| `sandbox_git_clone` | 克隆仓库 |
| `sandbox_git_status` | 查看状态 |
| `sandbox_git_commit` | 暂存并提交 |
| `sandbox_git_pull` | 拉取 |
| `sandbox_git_push` | 推送 |

## 注意事项

- **沙盒内路径用英文，本地下载可用中文**：创建/读写沙盒文件时路径与文件名须为英文或 ASCII；`sandbox_fs_download_local` 的 `local_path` 可指定中文文件名供用户查看。
- `sandbox_fs_download_local` 的沙盒源路径参数名为 `remote_path`（`sandbox_path` 为同义别名）。
- 大多数工具省略 `sandbox_id` 时使用当前活动沙盒。
- 长时间任务可在工具参数或配置中增大 `exec_timeout`。
- `sandbox_connect` 连接的已有沙盒**不会**被回合结束自动清理（仅清理本轮新建的）。
- 沙盒与宿主机隔离，可安全执行不可信代码和危险命令。

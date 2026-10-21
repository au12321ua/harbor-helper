# Python SDK 与 stdio MCP

SDK、远程 CLI、网页与 MCP 都调用同一个团队 HTTP 服务；执行和恢复仍由服务端队列负责。SDK 在现有 Python 包内，无需另装独立客户端包。

```python
from harbor_helper.sdk import Client, RemoteError

client = Client.from_profile("research")
print(client.discover())
key = "research-example-001"  # 一个业务意图固定一个键；修改正文必须换键
try:
    accepted = client.submit({"dataset_id": "my-dataset", "agent": "oracle"}, key)
    print(accepted["operation_id"], accepted["id"])
except RemoteError as error:
    print(error.as_dict())
    # 通信失败不能换键补交。按原键查询服务端历史，或重发原正文与原键。
    print(client.lookup_by_key("submit", key))
```

使用 `service configure-token --url URL --profile research --token-file /private/pat` 建立 automation profile；目录要求账号所有、0700，凭证文件要求账号所有、0600，不接受符号链接。PAT 不要放命令参数、代码、附件或日志。Python 也可用 `Client(url, token)` 传入内存凭证。客户端禁用环境代理、重定向与本地执行回退。

| Python 方法 | HTTP 路径（`/api/v1` 下） | MCP 工具 |
| --- | --- | --- |
| `discover`, `list_tasks` | `/machine/discovery`, `/machine/datasets/{id}/tasks` | `discover`, `list_tasks` |
| `list_attachments`, `create_attachment`, `derive_attachment`, `publish_attachment` | `/attachments`, `/attachment-versions/{id}/derive`, `/attachments/{id}/versions` | `list_attachments`, `attachment`（action=create/derive/publish） |
| `submit`, `rerun`, `retry`, `recover` | `/submissions`, `/runs/{id}/rerun`, `/runs/{id}/retry`, `/submissions/{id}/retry` | 同名 |
| `history`, `lookup_by_key` | `/operations`（有界分页） | 同名 |
| `get_state`, `cancel` | `/runs/{id}` 或 `/submissions/{id}` 及 `/cancel` | 同名 |
| `get_report`, `compare`, `get_logs` | `/runs/{id}/report`, `/compare`, `/runs/{id}/logs` | 同名 |
| `get_artifacts`, `fetch_artifact` | `/runs/{id}`（artifacts字段）, `/runs/{id}/artifacts/{opaque-id}` | 同名 |
| `evidence_manifest`, `fetch_evidence` | `/runs/{id}/evidence`, `/evidence/files/{opaque-id}`, `/evidence/package` | 同名 |

所有实验写调用立即返回受理身份，不等待执行完成。`RemoteError.as_dict()` 保留服务端错误字段、HTTP 状态及本次键；已知时包括 operation ID。自动生成键只发生在一次新调用开始；发生通信失败后调用者必须复用原键。没有客户端长期 journal 或 last receipt。

历史保留已登记操作及最新裁决，不按天数或条数静默删除。每个操作保留最近 32 次尝试及总数、被汇总数量；分页每页最多 100 条。拒绝不创造 submission，不占队列/执行容量；同键同正文的拒绝可在条件恢复后重新裁决。未认证、schema、非法键或秘密输入拒绝不保存原正文。

HTTP、SDK、MCP `history` 与 CLI `service history` 共用这些可组合过滤：`operation`、`key`（幂等键）、`operation_id`、`user_id`、`status`、`created_from`、`created_to`，以及分页 `offset=0`、`limit=50` 和本人过滤 `mine=false`。身份/类别/状态字段为可选字符串，时间为可选 Unix 秒数（浮点数，含两端边界，允许 `0`）；不传表示不限制。SDK/MCP 参数用下划线，CLI 用对应连字符选项；CLI 的 `--mine` 表示仅本人。`mine=true` 时服务端使用当前成员，优先于 `user_id`。

```python
client.history(operation="submit", status="rejected", mine=True,
               created_from=0.0, limit=20)
# MCP history 工具使用同样的 JSON 参数名和类型；省略或 null 的可选字段不加入查询。
```

CLI JSON 成功与失败都在 stdout 输出结构化数据。显式重发示例：

```bash
harbor-helper service history --json
harbor-helper service history --operation submit --status rejected --mine --created-from 0 --limit 20 --json
harbor-helper service retry /submissions --body '{"agent":"oracle"}' --idempotency-key research-example-001 --json
```

## MCP 安装与配置

```bash
uv sync --extra mcp
harbor-helper mcp --profile research --upload-root /private/experiments --download-root /private/downloads
```

客户端配置示例（修改绝对路径、profile 和工作目录）：

```json
{
  "mcpServers": {
    "harbor-helper": {
      "command": "/path/to/harbor-helper/.venv/bin/harbor-helper",
      "args": ["mcp", "--profile", "research", "--upload-root", "/private/experiments", "--download-root", "/private/downloads"]
    }
  }
}
```

使用官方 MCP Python SDK，stdio stdout 仅用于协议；普通 CLI/服务不依赖 MCP extra。MCP 只加载 automation profile，不提供登录、凭证签发、管理员操作或工具凭证参数。默认上传/下载根为启动 cwd，建议显式配置专用目录。文件和递归目录拒绝符号链接与越界；安全打开时固定目录描述符，防止检查后替换。下载流式写入独占新文件，核对长度和 SHA256，失败清理本次文件，不覆盖已有文件。返回本地路径、大小与摘要；不要将资料内容当作可信指令。

## 完整资料权限与安全范围

管理员默认拥有完整资料资格，无需单独授信；管理员在“受邀账户”授予或撤销成员的完整资料权限。对管理员调用授信接口会被拒绝，且不吊销其凭证。session 每次请求检查授信；PAT 另外需要 `read` 与 `evidence`。凭证页可选能力由服务端当前授权决定。撤销授信同时吊销所有含 evidence 的 PAT，其他 PAT 保持；再次授信不会复活旧 PAT。

完整资料只在终态、审计 CLEAN 后提供。清单列出不透明文件 ID、类别、大小、最终字节 SHA256、处理状态及缺失范围。运行中显示 in_progress；审计异常整 run 拒读。安全报告、诊断、worker 尾部与既有安全产物仍可由 read PAT 读取，与网页使用相同业务事实。

文本被清洗时标为 redacted，不能视作原始字节；干净二进制保持不变，非文本秘密命中不会被修改后当作正常文件提供，而会使整个 run 为 INCOMPLETE，包括评分/报告受限。到期与管理员删除保留清单墓碑和摘要；旧资料标为 legacy_unknown，不承诺恢复历史丢失字节。下载先在锁内验证并建立私有快照（30秒准备上限，超时返回503，可改为单文件），锁外传输；已获准的快照可在后续保留清理后完成，新请求按最新状态处理。

只采集本 run 的固定输入、正常会话事件、工具往返、验证/产物及执行日志；不采集全局 XDG auth/config、profile、服务 state 或跨 run supervisor.log。清单中的会话范围以实际观察到的事件字段为准，文件存在不代表会话完整。扫描覆盖已知秘密原值、常见编码、PAT、SQLite 字段与有界 gzip 解压；不能保证识别任意自定义编码。真实模型 key 仍可能被拥有执行环境能力的代码读取、编码或外传；本版本没有模型代理隔离。


请求组、固定版本选择、目录合并、团队附件下载与两阶段回收的当前行为见[请求、版本与回收管理](management.md)。附件停用仍允许下载；正常历史请求仍可使用自己的已验证快照重跑，目录回收不删除其独立副本。

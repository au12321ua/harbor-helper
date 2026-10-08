# 团队共享服务：启动与成员操作

服务使用一个独立的共享 state。CLI 与 Web 都访问同一个 HTTP API、持久队列和容量限制；成员登录只保存访问 token，模型密钥由管理员在服务端配置。旧本地团队 state 与会话不迁入此目录。

## 管理员首次启动

在项目根目录安装 Python 依赖并构建页面：

```bash
uv sync
cd frontend
npm ci
npm run build
cd ..
```

构建产物进入 Python 包的 static 目录；生产使用同一 HTTP 服务提供页面与 API，不需要运行 Vite。构建详情见 [前端说明](../frontend/README.md)。

用全新的目录初始化。以下路径是示例，主密钥必须位于服务 state 外：

```bash
uv run harbor-helper service init \
  --root /srv/harbor-helper/service \
  --master-key-file /srv/harbor-helper-private/master.key \
  --admin admin

uv run harbor-helper service serve \
  --root /srv/harbor-helper/service \
  --host 127.0.0.1 --port 8000
```

初始化会隐藏输入并二次确认管理员密码，密码须为 12–512 字符。新主密钥由程序生成 32 随机 bytes，文件为服务账号拥有的 0600 文件；不会把主密钥放入数据库。初始化不启动任务。可用 `service init --config /path/to/team.json` 输入既有非秘密 team 配置，例如默认数据集、oracle 镜像及运行参数；不要在该文件中放模型 key。已有本地或服务 state 不可再次初始化。

浏览器访问 `http://127.0.0.1:8000`，用管理员账户登录，创建受邀成员。管理员配置提供商、凭据、模型方案及容量；同一提供商可有多个凭据，成员通过模型方案明确选择。没有开放注册。凭据输入只写，不通过查询返回值；能解密凭据不代表提供商认证或模型请求已经验证。

默认监听 127.0.0.1:8000；需要团队网络访问时显式选择可达的 `--host` 和 `--port`。服务本身提供 HTTP，传输保护由部署环境处理；本轮实施和测试不表示已公网部署。服务进程不加载旧本地模型登录或继承的模型 key。

## 成员远程 CLI

成员在自己的机器或终端登录，不需要服务端 state 路径、SSH 或个人模型 key：

```bash
harbor-helper service login \
  --url http://127.0.0.1:8000 --username alice --profile team
harbor-helper service status
harbor-helper catalog
harbor-helper list
```

密码通过终端隐藏输入。独立 profile 位于 `~/.config/harbor-helper/remote/profiles/`，目录为 0700、文件为 0600，只保存服务 URL、成员访问 token 和安全身份信息。登录选中 profile 后，普通命令访问该服务；可用全局 `--remote-profile team` 或 `HARBOR_HELPER_REMOTE_PROFILE` 选择另一个 profile。API 故障、会话过期或 profile 损坏都明确失败，不会改为本地执行。

从 `catalog` 取得模型方案 ID 后提交：

```bash
harbor-helper submit --model-profile PROFILE_ID \
  --dataset DATASET_NAME@VERSION \
  --bundle /path/to/bundle --idempotency-key experiment-001
harbor-helper service retry
harbor-helper list --json
```

bundle 可以是合规目录或 ZIP，上传后由服务冻结。模型方案使用团队凭据；远程 `--model` 和个人 `auth login` 不是团队模型入口。验证 oracle 必须显式选择，不能因模型错误自动退回 oracle：

```bash
harbor-helper submit --agent oracle --idempotency-key oracle-001
```

提交先返回 `sub-*` 受理 ID 和 `preparing`，此时 run ID 可以为空。准备成功后，受理记录关联 `hh-*` run；准备失败或取消的原因可在受理状态查看。用实际返回的 ID 替换示例：

```bash
harbor-helper status sub-EXAMPLE
harbor-helper status hh-EXAMPLE
harbor-helper logs hh-EXAMPLE
harbor-helper report hh-EXAMPLE --json
harbor-helper artifacts hh-EXAMPLE
harbor-helper download hh-EXAMPLE FILE_ID --output ./result.bin
harbor-helper compare hh-LEFT hh-RIGHT
harbor-helper rerun hh-EXAMPLE --idempotency-key rerun-001
harbor-helper cancel sub-EXAMPLE
harbor-helper usage
```

下载用 API 返回的产物 ID，不能输入宿主路径，目标须为新文件。logs 默认输出原可读文本，`--json` 输出合法 JSON 字符串；其他命令 JSON 保留 API 安全结构。不可比的 compare 返回退出码 2，不给聚合改进结论。重跑产生独立受理和新归属，不修改原记录；它属于新执行，可能产生费用。

全体成员查看同一批受理、run 和安全结果。普通成员只能取消自己提交的任务，管理员能取消任何成员任务；读取权限不赋予取消别人任务的权限。CLI 和 Web 共享 Job/Trial/队列容量。

## 重试、退出与兼容

一次提交或重跑复用同一个幂等键和相同内容。客户端在请求前把最近一次操作保存为私有 receipt，`service retry` 重发同一路径、内容及键；发生超时先重试该操作，不换新键。主动新实验或 rerun 使用新键。同键不同内容会冲突。每个 profile 只保留最近一次 receipt；再次登录或退出会清除 receipt，需继续重试的操作应自行保留原参数和幂等键。

```bash
harbor-helper service logout
harbor-helper --local --state /path/to/old-local-team status hh-OLD
```

logout 撤销成员会话并删除本机 token，已受理任务继续。远程选择标记保留，下一次普通命令会要求重新登录；访问旧本地团队必须显式 `--local` 并选择独立的旧 state。含 `service.json` 的目录拒绝本地命令，不能绕过服务身份提交未绑定任务。

## 队列、备份与审计

API 启动时启动或协调同一个后台 supervisor。关闭浏览器、成员终端或 HTTP 进程不会停止已受理任务及后台队列；再次 serve 可恢复 API 观察。不要以 runs 为空判断空闲，还须检查 preparing 受理、queued/running、取消收尾及 cleanup_blocked 记录。当前没有 `service stop` 命令；需要停机或一致备份时先停止成员提交、处理全部未终态受理/run，并按实际后台进程的退出与资源清理状态确认无写者，再停止 HTTP/调度进程。不要直接杀进程后声称资源已释放。

备份完整 service state（含 SQLite 一致快照、配置、冻结输入和所需日志/产物），主密钥另作受保护备份。在线复制单独 SQLite 文件而遗漏 WAL 不能保证一致性；有写者时使用 SQLite 备份机制，并协调其余文件的快照时点。恢复须保留 `service.json` 所指主密钥路径和权限，核对凭据版本、受理/队列归属及审计能力；不能用新生成主密钥冒称旧凭据已恢复。

资源已确认释放但历史审计来源缺失时，任务进入终态并释放容量，安全摘要标明 audit incomplete，相关原始日志、报告和产物限制访问。只有资源未确认释放才是 cleanup_blocked 并占容量。主密钥整体丢失会影响所有相应加密凭据，不能称其余模型方案仍可用。被历史运行/日志引用的凭据版本不能随意删除；保留与删除按管理员配置及实际依赖处理。

时长、并发及 token/cost 观测不是金额预算；未知费用保持 unknown。服务验收范围与真实 provider/模型证据分别记录，详见 [验收标准](service-acceptance.md) 和 独立验收计划。

## 默认容量和保留参数

管理员可通过Web或 `/api/v1/admin/limits` 调整。当前保守默认：

| 参数 | 默认 |
| --- | --- |
| 全局Job / Trial | 1 / 2 |
| 准备中与queued合计 | 100 |
| 单实验尝试次数上限 | 3 |
| 墙钟默认 / 上限 | 1800s / 3600s |
| 每Trial CPU / 内存 | 2 CPU / 4096MiB |
| ZIP压缩/展开上限、条目上限 | 16MiB、2000项 |
| 产物 / 原始日志保留 | 7天 / 14天 |
| 成员登录会话 | 8小时 |

保留维护只处理资源清理与审计已确认的终态run。到期日志/产物不再可下载；安全评分报告和固定重跑输入仍保留。未使用旧凭据版本会回收，仍有运行或保留日志审计依赖的版本保留；存在审计异常的证据不自动删作clean。不会自动删除实验记录/固定输入，运维仍需监控磁盘或使用宿主配额；这些资源限制不是精确金额保证。

首版模型适配为多个独立OpenAI-compatible提供商端点，不包括未验证的原生协议适配、自动key池或自动failover。本轮无真实模型请求，实际供应商认证/模型能力需另作明确验证。

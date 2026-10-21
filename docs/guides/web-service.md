# 团队共享服务：启动与成员操作

服务使用一个独立的共享 state。CLI 与 Web 都访问同一个 HTTP API、持久队列和容量限制；成员登录只保存访问 token，模型密钥由管理员在服务端配置。旧本地团队 state 与会话不迁入此目录。

## Linux 服务安装与管理

需要 Linux、Python 3.12–3.13、uv 和可用的用户级 systemd。使用专用服务账号；由部署管理员配置该账号的开机 user manager（例如 `loginctl enable-linger`），HTTPS/代理/证书由部署环境处理。首次网页设置不需要 Docker、Hub 或模型请求；实际实验需要 Docker/Compose 和授权的数据集。

从已验收的固定提交安装，选择全新私有目录和唯一实例名：

```bash
python3 scripts/service.py install --directory /absolute/private/hh-team --instance team --port 8000
python3 /absolute/private/hh-team/manager/service.py start --directory /absolute/private/hh-team
python3 /absolute/private/hh-team/manager/service.py status --directory /absolute/private/hh-team
```

安装导出固定提交到 `releases/<SHA>` 并锁定安装依赖，运行时不依赖工程 worktree；`state/`、`private/`（主密钥及引导文件）、`home/` 和 `logs/` 分开。输出只给引导凭证文件位置，部署负责人在受保护终端读取并私下交给首管理员。管理员在网页首次设置，然后在“团队管理”邀请成员、配置数据集、模型/key与容量。不要把引导凭证贴入群聊、命令参数或 Git。

HTTP 与 scheduler 为独立 unit；`--part http` 或 `--part scheduler` 可单独启停。HTTP 启动及首次设置不会派生 scheduler；未初始化的 scheduler 等待网页设置完成。`start` 始终使用已安装 release，不会因 Git HEAD 改变而升级。

正常维护请在管理员网页“团队管理 → 容量与保留”走两阶段停止：先明确关闭新受理，再等待全部已受理任务结束，或明确取消全部未完成任务并清理资源。可退出等待，入口仍关闭。主机脚本入口：

```bash
python3 /absolute/private/hh-team/manager/service.py maintain --directory /absolute/private/hh-team --close-admissions --mode wait --wait-seconds 3600
# 明确取消全部（准备、排队、执行），保留历史，可重跑
python3 /absolute/private/hh-team/manager/service.py maintain --directory /absolute/private/hh-team --close-admissions --mode cancel
python3 /absolute/private/hh-team/manager/service.py stop --directory /absolute/private/hh-team
```

不带 `--close-admissions` 时，开放的入口需要交互输入 `yes`；非交互调用拒绝并保持原开关。已关闭则跳过确认。等待超时只退出客户端等待，持久停止意图继续生效。直接 `stop`/SIGTERM 则中断执行并尝试清理，保留 queued 和未发布 preparing，维护开关保持原值；这不是断点续跑。

升级、备份恢复、卸载及 systemd 限制见[Web 服务指南](#linux-生命周期与维护)。旧 `start-local.sh` 现在转发同一生命周期管理器，使用相同参数；不会隐式选择新发布。

## 开发与手动启动（非 systemd 安装）

本节用于源码开发或临时手动验证，不安装 systemd 服务。正式安装实例按上面的 [Linux 服务安装与管理](#linux-服务安装与管理)启动，随后直接在网页完成[管理员首次设置](#管理员首次设置)；不要同时对该实例的 state 启动下列手动进程。

需要 Linux、Python 3.12–3.13、uv，以及 Node.js 20.19+ 的 20.x 或 22.12+（CI 使用 Node 22）。在项目根目录安装 Python 依赖并构建页面：

```bash
uv sync --locked
cd frontend
npm ci
npm run build
cd ..
```

构建产物进入 Python 包的 static 目录；生产使用同一 HTTP 服务提供页面与 API，不需要运行 Vite。构建详情见 [前端说明](../../frontend/README.md)。

手动验证使用全新的独立 state，先创建私有目录；启动 HTTP 后在部署机浏览器打开 <http://127.0.0.1:8000/> 完成首次设置：

```bash
mkdir -p "$HOME/harbor-helper/service" "$HOME/harbor-helper-private"
chmod 700 "$HOME/harbor-helper" "$HOME/harbor-helper/service" "$HOME/harbor-helper-private"

uv run harbor-helper service serve \
  --root "$HOME/harbor-helper/service" \
  --setup-token-file "$HOME/harbor-helper-private/setup-token" \
  --master-key-file "$HOME/harbor-helper-private/master.key" \
  --host 127.0.0.1 --port 8000
```

另一个终端独立启动调度器（同一 state，不继承个人模型或 Hub 凭据）：

```bash
uv run harbor-helper service scheduler --root "$HOME/harbor-helper/service"
```

## 管理员首次设置

systemd 安装实例的引导文件位于 `<实例目录>/private/setup-token`，初始主密钥位于 `<实例目录>/private/master.key`；轮换后的 active 文件以数据库代次记录为准，见[主密钥管理](#外置主密钥升级与泄露轮换)。开发/手动模式使用上节显式指定的外置路径；未指定时，默认位于 state 同级的 `.<state目录名>-deployment/`。引导凭证不存在时由 HTTP 自动生成 owner-only 文件，安装管理器与 `service serve` 只提示文件位置。部署负责人在受保护终端读取并通过私下渠道交付凭证与网址，勿贴入群聊、命令参数或 Git。

管理员在网页填写首账户、密码和团队名称。首次设置完成后接口关闭，不允许再注册账户；重复与并发设置只能成功一次。引导文件和主密钥都必须在 state 外，属于部署持久材料；主密钥是 32 随机 bytes、0600，仅用于加密，不通过网站回显。备份时须同时保全 state 与配对的 active 主密钥；不得将密钥或引导凭证提交 Git。

管理员随后在网页完成业务配置：

1. **就绪与来源**：命名团队；私有 Hub 包输入团队 PAT。只写入加密保存，明确选择团队来源，不继承维护者 HOME 登录。停用后按匿名来源访问公开包。保存凭据不等于认证成功。
2. **Docker 诊断**：只读查看服务端 Docker 连接及镜像库存；不配置统一业务镜像，不建立镜像与数据集的适配关系。
3. **数据集**：登记 `owner/name` 来源后，到“请求与目录管理 → 数据集版本”查询最近远端版本、手选、预览并确认固定摘要，按版本检查作者参数，再明确选择默认。手填版本引用不能替代该流程，标签移动不改变已有实验。无需 `runtime_id`。提交下载并校验 digest，保留作者任务快照；执行时由 Harbor 按原 Dockerfile、Compose 和镜像声明处理依赖。作者默认变量照原样解析，缺少作者依赖如实失败，不注入替代镜像。来源验证不保证环境依赖可用。
4. **模型与 key**：按名称配置提供商、团队 key 与模型方案。内部 ID 自动生成，编辑载入现值；常用参数有控件，JSON 留高级区。多 key 明确绑定、轮换与停用仍保留；保存不发送真实模型请求，不声称认证或推理成功。
5. **受邀账户**：创建成员、重置密码及启停；成员从账户页修改密码，改密会撤销现有会话。无公开注册。

成员仅用浏览器登录，选择已验证数据集和任务、模型方案与实验名称；尝试次数、并发、时长在高级参数。共享观察、取消自己的任务、比较、重跑和下载均在网页完成。准备失败页显示安全分类和修复责任，允许修改原输入后新提交，保留失败历史。评分报告下载与日志/产物一样遵循审计限制；没有导出产物的数据集仍可下载安全评分报告。

已有服务 state 不可再次初始化。

默认监听 127.0.0.1:8000；需要团队网络访问时显式选择可达的 `--host` 和 `--port`。服务本身提供 HTTP，传输保护由部署环境处理。服务进程不继承环境中的模型 key。

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
  --attachment-version-id av-EXAMPLE --idempotency-key experiment-001
harbor-helper service lookup submit experiment-001 --json
harbor-helper list --json
```

附件先在“团队附件”或 `attachments create` 发布为版本，提交时引用版本 ID。模型方案使用团队凭据，CLI没有个人模型key入口。验证 oracle 必须显式选择，不能因模型错误自动退回 oracle：

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

## 重试与退出

一次提交或重跑的通信重试复用原幂等键与相同内容。超时后先用 `service lookup 操作类别 原键` 查询，或以原命令、原参数和原键重发；`service retry PATH --body JSON --idempotency-key KEY` 需要显式提供原路径与正文。客户端不保存 last receipt，应保留原参数及幂等键，可用 `service history` 查看服务端历史。主动新实验或 rerun 使用新键，同键不同内容会冲突。完整示例见 [SDK 与 CLI 指南](sdk-mcp.md)。

```bash
harbor-helper service logout
```

logout 对登录会话撤会话并删除本机 profile；对自动化 profile 只删除本机副本，PAT 须在网页撤销。已受理任务继续。远程选择标记保留，下一次普通命令会要求重新登录。CLI只访问团队服务，没有直接读写state的本地模式。

## 队列、备份与审计

HTTP 不管理 scheduler 进程。关闭浏览器、成员终端或 HTTP 不停止独立调度器；再次 serve 只恢复 API 观察。正常停止与升级必须按下文生命周期流程处理 preparing、queued、执行、取消收尾和 cleanup_blocked，不能只看 PID 或终态标记。

备份完整 service state（含 SQLite 一致快照、配置、冻结输入和所需日志/产物），配对主密钥另作受保护备份。在线复制单独 SQLite 文件而遗漏 WAL 不能保证一致性；有写者时使用 SQLite 备份机制，并协调其余文件的快照时点。恢复须核对 `service.json.master_directory`、数据库 active 代次及配对文件的路径、权限和 KCV，核对凭据版本、受理/队列归属及审计能力；不能用新生成主密钥冒称旧凭据已恢复。

资源已确认释放但历史审计来源缺失时，任务进入终态并释放容量，安全摘要标明 audit incomplete，相关原始日志、报告和产物限制访问。只有资源未确认释放才是 cleanup_blocked 并占容量。主密钥整体丢失会影响所有相应加密凭据，不能称其余模型方案仍可用。被历史运行/日志引用的凭据版本不能随意删除；保留与删除按管理员配置及实际依赖处理。

时长、并发及 token/cost 观测不是金额预算；未知费用保持 unknown。服务行为、真实provider/模型与部署验证分别记录，行为条件见[验收标准](../reference/service-acceptance.md)。

## 完整停机

systemd 安装实例按 [Linux 生命周期与维护](#linux-生命周期与维护)操作：管理员网页或 `manager/service.py maintain` 先关闭新受理，再明确等待或取消全部未完成任务；确认停止流程 complete、资源释放后，执行 `manager/service.py stop --directory /absolute/private/hh-team`。备份和升级使用同一管理器的 `upgrade` 流程，不能把服务退出当成已取得一致备份。

### 开发与手动模式的停止

以下仅适用于本指南的开发/手动启动模式。关闭网页不停止任务；前台 `serve` 的 Ctrl-C 只停 HTTP。需要正常排空时，保持 HTTP 和 scheduler 运行，在管理员网页“团队管理 → 容量与保留”关闭新受理，明确选择等待全部结束或取消全部。准备中、queued/running、取消收尾和 cleanup_blocked 都须处理；只有停止流程 complete、实际资源释放且 scheduler 正常退出后，再在 HTTP 终端按 Ctrl-C。

在 scheduler 前台终端直接按 Ctrl-C 或发送 SIGTERM 使用[非交互停止语义](#非交互停止与异常恢复)：中断执行并尝试清理，保留 queued/未发布 preparing，不改维护开关。这不等于正常向导已完成。再次观察或继续处理时，使用同一 state 和原主密钥分别重启手动 HTTP/scheduler，不要重新初始化或生成新 master，不按历史 PID 操作。

手动备份仍须确认全部 HTTP、scheduler、worker 和准备/下载子进程写者退出，按[离线备份与恢复检查](automation-ops-ci.md)核验一致性与原外置主密钥。服务停止或 PID 消失不替代资源、写者和备份检查。

## 当前执行准备契约

新服务提交冻结环境准备等待倍率，新提交初值10，1沿作者值；旧受理/旧父缺倍率时保留缺字段，不补新默认。倍率会影响比较条件。模型实验的总时长包含准备，并发/时长不等于金额预算。

新模型实验冻结`offline-npm-binary-v1`：匹配预装工具优先，否则无provider/Hub凭据的独立子进程准备固定公共平台工具并校验，再由Harbor上传作者容器离线使用。作者文件、镜像和网络定义不改；缓存不是模型结果。旧无策略受理继续旧安装契约。严格Options校验仍保留未知字段/类型拒绝，不能在恢复时删选项绕过Job预检。

来源验证、工具缓存和Oracle自检不代表真实provider认证、模型能力或任意作者端点可用；这些依赖需在明确授权范围内分别验证。

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

模型提供商可选择 `openai-compatible`（Chat Completions）、`openai`（Responses）、`anthropic`（Messages）。填写 API 基址，例如 OpenAI 的 `https://api.openai.com/v1`、Anthropic 的 `https://api.anthropic.com/v1`，不附 `/responses`、`/messages` 或 `/chat/completions`，不含 URL 凭据、query 或 fragment。自定义可信 HTTP(S) 端点同样按所选协议请求，不自动探测或 failover。

Responses/Messages 当前固定 OpenCode 1.18.35，只支持 `max_output_tokens` 正整数，默认4096；未知键（含 temperature、thinking、max_tokens）拒绝。Chat 保留原有参数与固定数字版本规则。保存与受理均重验；修改提供商协议后，旧方案需要按新协议调整参数。保存配置不会发真实模型请求；供应商认证和模型能力需另作明确验证。

普通已受理任务保留原提供商/凭据版本；重跑、修复后重试与恢复取同一身份最新 key 前，当前协议及端点必须等于冻结值，否则409并要求新建实验。需要阻断已受理任务时明确停用凭据；编辑提供商不会暗改冻结输入。

helper 管理完整模型选择、SDK、鉴权引用和 small_model。附件的 `config/opencode.json` 只支持 `instructions`、`permission`、`tools` 及受限 `agent` 提示/工具设置（prompt、description、tools、permission、steps、disable、hidden），不能含 provider/model/small_model、agent 模型切换、mode、plugin 等。运行时使用独立配置目录，禁用项目配置并用受控 inline 重申绑定。此保证覆盖受控配置通道，不承诺任意容器 root/bootstrap 恶意代码无法读取进程环境中的 key。

### 网页管理员配置提示

Hub来源凭据区会持续显示未设置/启用/停用、版本及更新时间；保存只代表加密存储，不能当作Hub身份或私有数据集访问验证。轮换后到数据集页面重新验证；失败输入中的秘密会清空。

Docker 诊断页面点击“发现本机 Docker 与镜像”，只读取服务账户的 Docker 连接和库存，不拉取、构建或删除。新服务提交和重跑不使用旧 runtime 的 alias/镜像变量；旧已受理非终态沿原冻结契约处理。重跑沿父作者任务快照及模型参数再执行，旧覆盖转换在受理和新记录明确标注，父历史不改。实际镜像差异或未知不单独阻断原生重跑或比较。

原生运行收尾保留镜像与 Docker 构建缓存，清理本次拥有的容器、网络、临时卷；不启用 keep_containers，不全机 prune。构建可能每次仍被调用，由 Docker 决定缓存命中。构建缓存不保留已删除容器可写层里的代理安装。实际镜像、Harbor 版本及阶段信息可通过安全评分报告取得，取不到时为 unknown。缓存会占磁盘，日常空间维护由部署负责人明确处理，不是每次实验自动删镜像。

模型配置页可管理多个提供商，每个提供商多个key、每个key多个方案。保存提供商后点“新建提供商”才能新增另一个；点编辑则更新同一对象版本。用提供商/key筛选看绑定。方案始终选择一个提供商与其一个key，切换提供商需重新选择匹配key；模型保存不发真实模型请求、不证明认证成功。

附件版本目录、权限、HTTP/CLI契约及迁移回退边界见[团队附件版本](attachments.md)。

## 网页待处理额度与维护

团队管理→容量与保留可调整“每成员待处理额度”，有效值不超过全局待处理上限。准备与排队合计按实验目标去重，所有凭证/网页共用成员身份，管理员也计入本人；默认配置10可调整，降低不取消存量。旧无身份实验仍占全局与执行容量。

同页可持久暂停/恢复 submit/rerun/retry/recover 新受理。维护原因与可选建议重试时间仅授权成员可读，不能填秘密/内部路径，时间不触发自动恢复。已有准备/队列继续排空，查询、取消和安全报告可用；暂停不能代替完整停写或备份检查。管理员 PAT 没有维护配置能力。

共享实验和新建页面显示受理状态、调度器活动及观察时间、本人/全局待处理计数。活动过旧显示未知并拒绝新键，既有原键找回仍可用；不提供预计开始时间。`/api/v1/health` 匿名只含存活/就绪布尔值，`/api/v1/readiness` 授权读取安全详情；就绪不保证 Docker/Hub/模型成功。迁移/回退的维护保护限制见[自动化接口](../reference/automation-api.md#兼容升级与回退)。

调度器以 SQLite 持久状态配合本机 `scheduler.wake` FIFO 唤醒，端点须为当前用户拥有的 0600 FIFO，不能以普通文件或 symlink 替代。通知失败不撤销已提交操作，低频对账会恢复推进。新增 runs.finish_status/finish_reason 由 Store 幂等初始化，保存取消/超时等最终决定；仍使用 SQLite rollback journal。`scheduler-stop.json` 只属于瞬态停止握手；正常启停按 PID/birth 判定，不能复制它到恢复实例。

正常维护等待期间，在途准备、执行或清理尚未结束时可能超过客户端等待期限；此时持久停止意图继续生效，不能据此强杀或宣称已停止。直接 stop 的中断语义见[非交互停止与异常恢复](#非交互停止与异常恢复)。证据维护竞争时，产物删除可返回 evidence_busy（409），在线备份返回 deferred；释放控制锁后重试。

## 外置主密钥升级与泄露轮换

首次升级到代次 schema 前，停止并实时确认该 state 的全部旧 HTTP、scheduler、worker、准备/下载等写者已经退出。旧代码不认识 active 代次，不能混用写入。此升级规程不代表已授权操作任何正在运行的团队实例。

首次正常打开时从旧 `service.json.master_file` 一次导入：可靠保存外置目录，事务建立 active 的代次、basename、KCV，然后移除旧字段。导入中断可重启完成。active 表已存在但缺行、损坏或文件/KCV 不匹配时拒绝，不重建、不回退旧路径。正常 `service.json` 仅保留 `master_directory`；部署启动参数的 `--master-key-file` 只用于首次初始化，不覆盖已有 active。文件须为当前属主的 owner-only regular 32字节文件，禁止 symlink/FIFO；目录须在 state 外、当前属主且 group/other 不可写。

管理员在“团队管理 → 安全与主密钥”查看代次与可用性，重验证当前密码后轮换。全部模型/Hub 历史及停用版本在同一事务重加密，业务版本和绑定不变。界面使用预期代次防止重复轮换；响应丢失先刷新确认结果。密钥文件先 fsync 文件及目录，再发布 active。主密钥不可用会阻止新执行并保留排队任务，就绪页显示故障；恢复正确文件后继续。

泄露处置顺序：暂停受理（不停止已有队列）→先停用受影响凭据的全部旧版本→按需取消运行任务→轮换主密钥→上游撤销旧凭据→对同一身份轮换写入新值→验证新实验→恢复受理。先停用再写新值，避免把新版本一起停用；先换主密钥再保存新上游秘密。旧队列不自动改绑，可按需要新建或等价重跑。

轮换不撤销已泄露旧快照或上游 key，也不承诺擦除 SQLite 旧页、journal、WAL 或备份。已运行进程可能仍持有明文。旧代次文件和崩溃孤儿不会自动删除；确认非 active、无旧快照读者并满足外部备份保留策略后，由部署者单独处置。ops 生成的每份快照自带当时配对 key，新快照只需当时 active key。代码回退不等于 state 回退，不用旧备份覆盖后续业务数据。

### 复制配置与下载比较

实验详情的“复制配置新建”将 manifest 中的安全配置带入可编辑的新建页；准备中的提交和准备失败页也可复制（失败页为“修改输入后新提交”，保留原名）。有父实验的未发布提交使用父 manifest，并应用明确的总时长覆盖；没有父实验时仅恢复公开提交意图。无法读取父实验会提示恢复失败。点击复制不会提交；确认后创建当前提交者的新记录，按当前目录、模型与附件重新校验和冻结。“按原条件重跑”仍保留原冻结条件。

原值不可用、任务模式无法映射或参数未知时，页面保留原值并要求明确修正；不会自动换成团队默认模型、数据集或无附件，也不夹紧超限数值。附件页“使用 vN 新建实验”仅预设附件，其余字段沿用普通新建默认值。通信失败可用同一幂等键重试；修改意图后生成新键。

对比成功后可下载当前响应的 JSON 或 CSV，不重新执行或评分。切换实验、重新请求或请求失败会清除可导出的旧结果。JSON 为 `{format_version:1, exported_at, comparison}`，原样保留服务端 Comparison；`comparable:false` 时即便存在 `tasks[].delta`，也不能据此给出改进结论。

CSV 使用 UTF-8 BOM、CRLF 和标准双引号引用。固定列为 `format_version, exported_at, left_run, right_run, comparable, reasons_json, record, task, metric, left_type, left_value, right_type, right_value, delta_type, delta_value, metadata_json`。每行含左右身份与可比性；`record=metadata` 保存配置差异、附件身份及环境观察的 JSON，空任务列表也保留此行；`task` 行保存逐指标值，双方无指标的任务另有 `no_valid_metrics` 行。类型列区分 `number`、`null`、`missing`、字符串等，保留零、负数和原始数值精度。不可比时 `delta_type=incomparable`、差值留空，不输出均值；可比时仅输出服务端已有差值和 `mean_task_delta`，不在浏览器重新计算。不可信文本若以公式字符（含前置空白/控制字符）开头会加单引号，负数指标保持数值。

## Linux 生命周期与维护

已接入的实例可由管理员在网页检查固定版本并更新；首次接入、源配置、升级屏障与故障处理见[网页版本与更新](web-updates.md)。

`python3 scripts/service.py ACTION --directory /absolute/private/instance` 是统一主机入口。安装后使用输出的 `manager/service.py`，避免依赖工程目录。命令为 `install/start/stop/status/maintain/upgrade/uninstall`；实例名只含小写字母、数字和连字符，同名 unit 或内容/路径不符时拒绝操作。运行进程的内部 release 租约与 state 的 release 标识约束共用写者，外部 CLI 仍只按机器协议兼容性判断，不要求精确发布 SHA 相等。

### 两阶段正常停止

管理员网页的“正常停止调度器”先展示持久维护开关及准备、排队、启动、执行、取消收尾、资源未释放和审计异常计数。调度器故障的不可受理不代表维护开关已关闭；必须明确同意关闭新受理，拒绝不写入。维护开关已关闭则跳过。然后明确选择等待全部结束，或取消全部未完成任务。取消不是可恢复暂停，没有 run 级断点续跑，历史记录可重跑。

停止意图在 `state/shutdown.json` 持久保存，由 scheduler 推进；网页遇到 scheduler 已停时需从主机显式启动。主机 `maintain` 在确认选择后会启动本实例 scheduler 推进尚未完成的意图；浏览器断线、HTTP 重启不会丢失。A 继续准备与派发直到排空；B 阻止被取消的准备发布/队列启动，推进执行终止与 Docker 资源释放。实际准备/清理 lane 尚未结束时也不能完成。`cleanup_blocked` 保持未完成并重试；审计异常单独展示，不占执行容量。排空完成后 scheduler 正常退出，`Restart=on-failure` 不将它拉起；HTTP 继续观察。

查询、取消、已受理请求的幂等回执保持可用。管理员可“退出等待，保持入口关闭”（主机 `maintain --mode abort`），或显式改为取消；不会自动恢复受理。再次启动 scheduler 后维护开关仍关闭，需管理员明确恢复新受理。

### 非交互停止与异常恢复

`stop` 或 `systemctl --user stop harbor-helper-<实例名>-scheduler.service` 先停派发，终止执行并尝试清理，保留 queued 和未发布 preparing；原维护开关不改写。重启会对账和重试未确认资源，已中断的执行需重跑。`--part http` 只停止 HTTP。

unit 使用 `KillMode=mixed`、`Restart=on-failure`、270 秒停止预算；scheduler 自身停止预算 240 秒，超时保留持久清理记录后失败退出，systemd 收尾整个 cgroup。子进程的独立进程组用于精确终止，不是逃出 cgroup。不要将 unit 已退出等同于业务正常维护完成；必须看到停止意图 complete、无未完成任务且所有写者退出。

当前安装器使用用户级 systemd。用户 manager 自启需要部署者配置 linger；`--runtime` 只用于隔离验证，重启后 unit 不保留。用户级 unit 无法对系统级 `docker.service` 建立有效的关机顺序依赖：主机部署须保证 Docker 可用至应用清理结束（例如系统级关机编排先调用本实例 stop）。不支持将用户 unit 的 `After=docker.service` 当成跨 manager 保证。Docker 先退出、硬掉电或外部强停时可能留下清理记录；下次启动继续对账，不能承诺关机前必然释放。

### 明确升级、备份与回退

服务不会继承登录终端的代理或凭据。需要代理时，由部署管理员创建实例的 `private/network.json`（所属用户、0600），例如：

```json
{"HTTPS_PROXY":"http://127.0.0.1:7890","HTTP_PROXY":"http://127.0.0.1:7890","NO_PROXY":"localhost,127.0.0.1,::1"}
```

只允许大小写代理变量 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY` 与 `SSL_CERT_FILE/SSL_CERT_DIR`。HTTP 和 scheduler 启动时从文件加载，代理值不写进 unit、命令参数或应用日志。修改后用实例管理器先 stop 再 start；有未完成实验时先正常维护排空。文件留在 release 之外，升级保留；主机备份需另外保全此网络配置。它只配置服务进程出网，不改变作者容器的网络、Docker daemon 或镜像构建代理。

首次从没有网络启动器的旧安装升级时，使用目标源码的 `python3 /path/to/reviewed-checkout/scripts/service.py upgrade ...`，它会按旧 release 核对原 unit，并生成新启动器的 unit、更新安装管理器；后续继续用安装后的 `manager/service.py`。

```bash
python3 /absolute/private/hh-team/manager/service.py upgrade \
  --directory /absolute/private/hh-team --source /path/to/reviewed-checkout \
  --close-admissions --mode wait --wait-seconds 3600 \
  --backups /absolute/private/hh-team-backups
```

也可明确 `--mode cancel`。先完成正常维护，再停止 scheduler 和 HTTP，取得独占写者租约并核全部 state 写者，复用 `ops.py --kind offline` 完整备份。备份目录必须在实例与 Git 之外；默认是实例同级 `<实例目录名>-backups`。备份保存全部 state/配置/产物和源 release 信息，匹配主密钥受控保存在备份目录的独立 0600 `.master` 文件。通过独立新目标 `restore-check` 的摘要、数据库完整性、归属与凭据解密检查后，才安装并切换新 release；备份/依赖安装失败不切换，不丢旧 state 和 release。升级完成后显式 `start`，维护开关保持关闭。

不支持开发期旧 schema 迁移。若目标版本不读旧 state，显式 `--fresh-state` 在可靠备份之后将旧 state 保留为 `state-retained-<唯一标识>`，另建空 state，重新网页设置；默认不隐式删除或重置。外置 private 文件仍保留。需要回退时，用备份中源 release 及其匹配主密钥恢复到**独立目标**，按[离线恢复检查](automation-ops-ci.md)校验与检查冻结绝对路径，再为恢复目标安排匹配版本。不能仅切换代码打开已经被新版本写过的 state，不能用旧备份覆盖后来业务数据。

运维 timer 和其它外部写者必须由部署者先停用；本入口只管理它创建的两个服务 unit，不擅自修改其他工具。离线写者检测拒绝正在运行或身份不明的进程，管理员仍须防止其他账号/工具在维护窗口重新进入。备份保留和主密钥访问权限由部署者管理。

### 卸载与删除范围

```bash
python3 /absolute/private/hh-team/manager/service.py uninstall --directory /absolute/private/hh-team
```

默认停服务并移除本实例 release 与 unit，保留 state、private、home、logs、备份和 retained-state。未完成任务或资源释放未确认时拒绝移除运行程序；先恢复 scheduler，完成正常维护。manager 与 ownership manifest 保留作审计及同版本重装入口，重复卸载不改变保留数据。

`--purge` 首先展示准确的 `state/private/home/logs` 路径，并要求独立 `--confirm-delete /absolute/private/hh-team` 确认。只删除这些明确子目录，不删除同级备份、retained-state 或其它实例。服务名、unit 文件和目录归属不匹配则拒绝；不做全局 Docker/cache prune。卸载后重装保留数据须使用匹配旧 release；换版本走有备份的 upgrade。


请求组、固定版本选择、目录合并、团队附件下载与两阶段回收的当前行为见[请求、版本与回收管理](management.md)。附件停用仍允许下载；正常历史请求仍可使用自己的已验证快照重跑，目录回收不删除其独立副本。

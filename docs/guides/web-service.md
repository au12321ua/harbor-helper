# 团队共享服务：启动与成员操作

服务使用一个独立的共享 state。CLI 与 Web 都访问同一个 HTTP API、持久队列和容量限制；成员登录只保存访问 token，模型密钥由管理员在服务端配置。旧本地团队 state 与会话不迁入此目录。

## 一条命令启动本机空实例

在干净的 Git checkout 中运行（Linux、Python 3.12–3.13、uv）：

```bash
./scripts/start-local.sh
```

入口复用已提交的生产 static，不需要 Node 或前端构建。它从当前固定提交导出独立发布目录并锁定安装依赖；默认仅监听 `127.0.0.1` 的空闲端口。代码、独立 HOME、持久 state、外置 master/setup 和日志位于 `~/.local/share/harbor-helper-local/`，不使用仓库旧 state 或个人模型/Hub 登录。

1. 打开输出的 URL，直接使用交互终端显示的引导凭证；输出被重定向时只显示本机凭证文件路径，不显示值。
2. 网页首次设置创建管理员，然后登录，在“团队管理”配置业务。新空实例不迁入旧账户或实验；首次设置无需 Docker/Hub/key，真实实验仍需这些依赖和授权。
3. 再运行显示已有实例；`./scripts/start-local.sh stop` 停止自己的 HTTP 和空闲调度器，重新运行后原账户与主密钥保留。

```bash
./scripts/start-local.sh status
./scripts/start-local.sh restart
./scripts/start-local.sh --port 8780
./scripts/start-local.sh --directory /absolute/private/local-instance
```

`--port` 用于停止状态下选端口；多实例用不同 `--directory`，后续 status/stop 使用同一路径。日志路径随状态输出。stop 遇未终态任务会拒绝停止调度器，需重新启动网页取消/等待；它不会强杀执行任务。坏记录或主密钥缺失时按诊断检查原文件，不重新初始化。更换代码版本前先确认 stop 成功；旧发布目录不会自动删除。此入口用于同机本地使用，远程访问、HTTPS和生产迁移见下文。

## 管理员首次启动

在项目根目录安装 Python 依赖并构建页面：

```bash
uv sync --locked
cd frontend
npm ci
npm run build
cd ..
```

构建产物进入 Python 包的 static 目录；生产使用同一 HTTP 服务提供页面与 API，不需要运行 Vite。构建详情见 [前端说明](../../frontend/README.md)。

部署负责人用全新的独立 state 启动服务即可显示首次网站设置，无需先在终端创建管理员：

```bash
uv run harbor-helper service serve \
  --root /srv/harbor-helper/service \
  --setup-token-file /srv/harbor-helper-private/setup-token \
  --master-key-file /srv/harbor-helper-private/master.key \
  --host 127.0.0.1 --port 8000
```

引导凭证不存在时由服务自动生成 owner-only 文件；手动 `service serve` 只提示文件位置。一条命令入口仅在交互终端、实例尚未初始化时显示引导值，重定向输出只给本机路径。部署负责人通过受保护渠道交付该凭证与网址；管理员在网页填写首账户、密码和团队名称。首次设置完成后接口关闭，不允许再注册账户；重复与并发设置只能成功一次。引导文件和主密钥都必须在 state 外，属于部署持久材料；主密钥是 32 随机 bytes、0600，仅用于加密，不通过网站回显。未显式给路径时，它们位于 state 同级的 `.<state目录名>-deployment/`。备份时须同时保全 state 与外置主密钥；不得将密钥或引导凭证提交 Git。

管理员随后在网页完成业务配置：

1. **就绪与来源**：命名团队；私有 Hub 包输入团队 PAT。只写入加密保存，明确选择团队来源，不继承维护者 HOME 登录。停用后按匿名来源访问公开包。保存凭据不等于认证成功。
2. **Docker 诊断**：只读查看服务端 Docker 连接及镜像库存；不配置统一业务镜像，不建立镜像与数据集的适配关系。
3. **数据集**：命名来源，填写 `owner/name@版本`，保存后验证权限与任务清单，选择默认。无需 `runtime_id`。提交下载并校验 digest、保留作者任务快照；轮到执行时由 Harbor 按原 Dockerfile、Compose 和镜像声明处理依赖。作者默认变量照原样解析，缺少作者依赖则如实失败，不注入替代镜像。来源验证不保证环境依赖可用。
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
harbor-helper service retry
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

一次提交或重跑复用同一个幂等键和相同内容。客户端在请求前把最近一次操作保存为私有 receipt，`service retry` 重发同一路径、内容及键；发生超时先重试该操作，不换新键。主动新实验或 rerun 使用新键。同键不同内容会冲突。每个 profile 只保留最近一次 receipt；再次登录或退出会清除 receipt，需继续重试的操作应自行保留原参数和幂等键。

```bash
harbor-helper service logout
```

logout 撤销成员会话并删除本机 token，已受理任务继续。远程选择标记保留，下一次普通命令会要求重新登录。CLI只访问团队服务，没有直接读写state的本地模式。

## 队列、备份与审计

API 启动时启动或协调同一个后台 supervisor。关闭浏览器、成员终端或 HTTP 进程不会停止已受理任务及后台队列；再次 serve 可恢复 API 观察。不要以 runs 为空判断空闲，还须检查 preparing 受理、queued/running、取消收尾及 cleanup_blocked 记录。当前没有 `service stop` 命令；需要停机或一致备份时先停止成员提交、处理全部未终态受理/run，并按实际后台进程的退出与资源清理状态确认无写者，再停止 HTTP/调度进程。不要直接杀进程后声称资源已释放。

备份完整 service state（含 SQLite 一致快照、配置、冻结输入和所需日志/产物），主密钥另作受保护备份。在线复制单独 SQLite 文件而遗漏 WAL 不能保证一致性；有写者时使用 SQLite 备份机制，并协调其余文件的快照时点。恢复须保留 `service.json` 所指主密钥路径和权限，核对凭据版本、受理/队列归属及审计能力；不能用新生成主密钥冒称旧凭据已恢复。

资源已确认释放但历史审计来源缺失时，任务进入终态并释放容量，安全摘要标明 audit incomplete，相关原始日志、报告和产物限制访问。只有资源未确认释放才是 cleanup_blocked 并占容量。主密钥整体丢失会影响所有相应加密凭据，不能称其余模型方案仍可用。被历史运行/日志引用的凭据版本不能随意删除；保留与删除按管理员配置及实际依赖处理。

时长、并发及 token/cost 观测不是金额预算；未知费用保持 unknown。服务行为、真实provider/模型与部署验证分别记录，行为条件见[验收标准](../reference/service-acceptance.md)。

## 完整停机

关闭网页不停止任务；前台`serve`的Ctrl-C只停HTTP。重新启动同一state会协调已有调度器，不能重复init或生成新master。

部署负责人需要完整停机时：管理员先在“团队管理→容量与保留”暂停新受理并填写安全原因/可选建议重试时间；确认网页受理状态为暂停（重启保持），在网页确认所有受理与run终态，等待或取消自己的未终态；管理员可取消任何人的任务。准备中、queued/running、取消收尾和cleanup_blocked都要处理。先停止HTTP（前台Ctrl-C；后台部署按自己的进程管理器停止该HTTP），阻止继续提交；然后对**已存在的专用服务state**执行下面的空闲调度器停止检查。目录替换成该部署实际路径，维护已有部署须先核对进程归属，不按历史PID操作。

```bash
uv run python - /absolute/path/to/service-state <<'PY_STOP'
import sys
from pathlib import Path
from harbor_helper.persistence.store import Store
from harbor_helper.execution.runs import stop_supervisor

root = Path(sys.argv[1]).expanduser().resolve()
if not (root / "service.json").is_file():
    raise SystemExit("Choose an existing service state; no initialization performed")
store = Store(root)
with store.control():
    print(stop_supervisor(store))
PY_STOP
```

这是部署维护调用，不是成员登录或日常配置步骤。函数会拒绝未终态run或preparing受理，并按PID/birth确认空闲调度器退出；拒绝时不要强杀或宣布资源已释放，使用同state重启HTTP处理队列后再维护。停止结果不替代受理、资源及证据审计核对。操作不修改历史实验；不使用全机prune或删除公共缓存。

确认没有HTTP、调度器、worker和准备/下载子进程写者后，再按上方“队列、备份与审计”协调state与外置原master的备份。恢复时保持原路径/权限和凭据版本；完整灾备演练须单独验证。

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

停止仅允许空闲队列，在途审计/维护尚未退出时可能超过等待期限；“stop not confirmed”表示仍需等待并核对身份，不能据此强杀或宣称已停止。证据维护竞争时，产物删除可返回 evidence_busy（409），在线备份返回 deferred；释放控制锁后重试。


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

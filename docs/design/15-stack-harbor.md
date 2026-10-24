# 15 技术栈与 Harbor 集成

版本：v0.3 · 日期：2026-10-22 · 状态：本轮设计基线；M1 已在 Linux 上验证原型，M2～M7 已按此实现，系统级安装布局属 M8 尚未实现。实际做法与本文不同处见 [14](14-decisions.md) 各实施记录

导航：[总览](00-overview.md) · 依赖：[执行](05-scheduling-execution.md)、[评分](06-results-scoring.md)、[网络与权限](09-identity-security.md)、[运维](12-operations.md)

> 本阶段调整：一个运行对应一个 Runner 进程和一个 Harbor Job，第 4、6 节“一个执行尝试对应一个 Harbor 试次”暂不适用，见 [14](14-decisions.md) D-020。其余技术路线是本轮设计基线；实践中有更好的做法时按 14 的规则调整。

## 1. 选型依据

首期为 Linux 单机、初期 2～3 名活跃成员、约 10 个并行试次，服务端和 Worker 的管理逻辑适合放在同一进程。Harbor 是 Python 生态的执行框架；其官方发布策略说明稳定版按需发布、通常每两周一次，minor 版本可能含破坏性变更。因此，平台与 Harbor 采用独立依赖环境，通过版本化协议集成。

Python 是复用生态、类型工具和集成经验的选择，并不是进程内 Worker 强制要求执行器使用同一种语言。采用子进程边界后，平台可以更独立地演进。

## 2. 技术栈基线

| 层 | 本轮采用的设计路线 | 约束与实施说明 |
| --- | --- | --- |
| 服务端 | Python、FastAPI、Pydantic | 业务模型独立于 Harbor 类型；FastAPI 输出公共 OpenAPI |
| Harbor 集成 | 专用 Runner + 精确版本 Harbor + 独立 uv 环境 | 服务进程不直接 import harbor；通过 JSON 协议与文件交接 |
| 数据库 | SQLite WAL、SQLAlchemy 2、Alembic | 使用短事务，迁移离线执行。实现为 SQLAlchemy 2 Core + 标准 sqlite3 同步短事务，写事务一律 `BEGIN IMMEDIATE`，不用 aiosqlite（M2） |
| 队列 | 数据库队列表、asyncio 调度器 | 试次粒度领取（本阶段按 D-020 为运行粒度）；单一协调器分配容量，共享恢复用数据库租约与等待者去重 |
| 原始产物 | 本地文件系统、ArtifactStore 接口 | 日志和大文件不放入业务数据库 |
| 前端 | React、TypeScript、Vite | 构建为静态文件，由服务端托管；运行主机无需 Node |
| 网页 API 客户端 | 从公共 OpenAPI 生成 TypeScript 类型与调用层 | 网页不连接数据库、不通过模板隐藏业务动作 |
| Python SDK | httpx 薄客户端 + 由同一契约生成的类型 | 不依赖 FastAPI 应用或 Harbor；等待、分页和下载为辅助层 |
| CLI / MCP | 后续范围，不属于 P0（14 U-11）；加入时建立在 SDK 上 | 沿用实验权限，不成为管理旁路 |
| 密码与令牌 | Argon2id；网页会话 cookie；PAT 随机值只存哈希 | 使用成熟库，记录算法与参数版本 |
| 业务凭据 | AES-GCM 加密、独立主密钥 | 随机且不复用 nonce；保存 key_version，日志不含明文 |
| 发布 | uv 锁定依赖、每发布版本独立环境、current 链接 | 构建 / 安装依据锁文件，不在启动时升级 |
| 守护与日志 | systemd、journald | 审计元数据在数据库，试次日志仍在产物存储 |

以上是设计路线。现状：服务依赖由根目录 `uv.lock` 锁定；Runner 是仓库 `runner/` 下的独立 uv 项目，锁定 Harbor 0.24.0（M3）。Python、Harbor、Runner、系统发行版和 Docker 的具体版本必须经过兼容验证后精确写入发布清单，不把官网示例版本当作已验证版本。

暂不引入 Celery、Redis、Kubernetes、独立微服务或生产 Node 服务。SQLAlchemy 和 Alembic 为后续数据库迁移提供工具，但不意味着 SQLite 能无成本切换为 PostgreSQL；SQL、锁语义和并发测试仍需重新验证。

## 3. 两条 schema 边界

公共业务契约与下游执行契约各有自己的职责：

1. 平台 API：由 FastAPI 路由和平台 Pydantic 模型输出 OpenAPI。网页客户端、SDK 类型和 API 文档从同一构建产物生成。
2. Harbor 作业：从精确锁定版本的 Harbor 导出 JSON Schema，仅用于适配器转换和校验，不能直接替代平台运行对象。

服务端不向客户端透传 Harbor 的 Pydantic 类型、异常类或完整 job config。Runner 内可使用该版本 Harbor 的 Pydantic 模型解析结果，再转换为平台协议。这样升级 Harbor 不会直接改变公共 API。

## 4. 进程与依赖边界

~~~mermaid
flowchart LR
    API[FastAPI 业务服务] --> W[进程内 Worker 与调度]
    W --> P[Runner 子进程 / JSON 协议]
    P --> H[独立环境中的锁定 Harbor]
    H --> D[Docker 与 Harbor 网络控制]
    P --> F[受限工作目录 / 结果文件]
    W --> S[ArtifactStore]
    F --> S
~~~

Worker 仍在服务进程内，负责领取、租约、取消、资源和结果确认；具体 Harbor 调用在 Runner 子进程中。首期一个 ExecutionAttempt 对应一个 Runner 执行进程及一个 Harbor 试次，不让 Harbor 再展开整个平台批次。本阶段按 D-020，一个运行对应一个 Runner 进程和一个 Harbor Job。

安装布局建议：

~~~text
/opt/maestro/versions/<platform-version>/
  server/                    FastAPI 与业务依赖环境
  web/                       已构建静态文件
/opt/maestro/current -> versions/<platform-version>
/opt/maestro/harbor/<harbor-version>/<runner-revision>/
  venv/                      精确锁定的 Harbor 与 Runner
  compatibility.json         协议、Harbor、schema 与异常映射摘要
/etc/maestro/config.toml      部署配置
/etc/maestro/secrets/master-<代次>-<随机>.key
/var/lib/maestro/app.db
/var/lib/maestro/artifacts/
/var/cache/maestro/           任务内容与准备缓存
journald                     服务日志
~~~

现状：上述布局属 M8，尚未实现；Runner 目前在仓库 `runner/` 下，服务按配置项 `runner_python` 启动它（M3）。`compatibility.json` 兼容清单未实现，适配器标识只记 `harbor-0.24.0/<映射摘要>`。

平台依赖锁与 Harbor 依赖锁分开。Harbor 版本目录下区分不可变 Runner 修订，runner_id 标识二者的组合；正在执行的尝试继续使用已选择环境，禁止原地升级。已有 Runner 仅在不再被执行或保留策略引用时回收；多个版本共存是可选演进能力，不扩大首期调度范围。

数据源和准备能力若必须调用 Harbor Python API，同样通过 Runner 的目录 / 准备命令实现；能用稳定 HTTP 读取的 Hub 目录可由 httpx 适配器处理。服务端不能为了准备镜像而重新引入 Harbor 依赖。现状（M4）：Hub 目录与下载走 Runner 的 `hub` 命令；准备不需要 Harbor，由服务进程直接调用 Docker（`buildx build`、`pull`、`save`、`load`），没有 Runner 准备命令。

A9 的准入与缓存分离由平台管理，不依赖 Harbor 恰好提供同名状态。管理员首次成功准备建立准入证明；已受理运行调用同一准备能力恢复固定内容。共享恢复采用独立的准备进程与 Operation / 租约，可被多个执行尝试等待；不将它归到首个试次的进程组。现状：准备进程是服务进程的 Docker 客户端子进程，随服务退出（M4）。附件安装 P0 留在每试次容器，不能混入数据集共享准备层，详见 [02](02-datasets-preparation.md) / [03](03-configuration-attachments.md)。

## 5. Runner 协议

以下为平台自定义协议，Harbor 并未承诺直接输出这些事件。

| 通道 | 内容 | 要求 |
| --- | --- | --- |
| stdin 或受限输入文件 | 固定规格、执行 / 准备命令、attempt_id 或 operation_id、租约、内容与输出句柄 | JSON，含 protocol_version；不使用 shell 拼接 |
| stdout | NDJSON 结构化事件 | 一行一事件，有序号；不混入进度条或第三方打印 |
| stderr | 脱敏诊断日志 | 有界读取，防止管道阻塞；不当作评分依据 |
| 结果目录 | 原始 Harbor 结果、平台 result.json、产物清单 | 完成标记原子写入，摘要和归属可验证 |

事件 envelope 示例：

~~~json
{
  "protocol_version": 1,
  "attempt_id": "attempt_01",
  "sequence": 7,
  "type": "phase_changed",
  "payload": {"phase": "verifying"}
}
~~~

最少事件为 started、phase_changed、heartbeat、result_ready、artifact_manifest、completed。

现状（M3～M5）：Runner 有 `execute` 与 `hub` 两条命令。执行事件的 envelope 带 run_id 与时间 `at`，不带 attempt_id；事件为 started（Harbor 与 Runner 版本、PID）、network_plan、attempt_started、phase_changed、log、attempt_finished（结果、是否还会重试、归档目录与逐文件摘要清单、用量、附件安装记录）、heartbeat、cancel_requested、completed；`hub` 只回一条 result。没有单独的结果目录完成标记和平台 result.json，平台按 attempt_finished 的清单逐个核对归档文件。原始 Harbor 终端输出被 Runner 捕获并送入诊断通道；实时阶段事件的获得方式需要针对锁定版本验证，不能假定解析彩色终端输出即可可靠实现。

上例为执行命令；目录 / 准备命令以 operation_id 替代 attempt_id，恢复还带 preparation_id、generation 与独立 lease_token（准备未经 Runner，见第 4 节现状）。schema 区分命令类型及必需字段。准备结果只发布经摘要验证的缓存清单，不伪造 TrialResult；服务端分别核对操作租约和执行租约。

协议和结果都需 schema 校验。进程退出码 0 不等于任务通过，非零也不能抹去已经完成的合法结果文件；平台按最终结果清单、租约和错误策略决定业务状态。

凭据通过受保护环境或权限受限文件临时注入，不放进命令行参数或可导出的作业配置。Runner 清理其临时凭据文件，Worker / 启动对账负责兜底。现状（M5 第二阶段）：服务在执行时解密凭据，经 stdin 交给 Runner；模型密钥只留在 Runner 内存，作者参数值（含秘密参数）放进 Runner 环境变量供 Harbor 解析任务模板。在容器内调模型的 Harness（OpenCode）把密钥复制为容器内权限 400 的临时文件，Agent 结束即删除。

## 6. 作业生成、预检与单次执行

官方配置文档已确认以下命令存在，实施时仍需用锁定版本验证：

~~~bash
harbor job schema
harbor run --config job.yaml --print-config
harbor run --dry-run --config job.yaml
~~~

--dry-run 检查配置、Agent 参数、凭据和任务来源，不下载任务、不执行作业，因此不能证明镜像可构建或网络可用。现状：schema 导出与 --dry-run 校验尚未接入（M5 收尾未完成事项），Runner 以 Harbor 的 Pydantic 模型直接构造 JobConfig。平台预检仍包括内容固定、任务准入、已知内容阻塞、必要配置、资源与权限；本机缓存缺失仅形成运行恢复计划，不要求管理员重新建立准入。

原设计：每次平台 ExecutionAttempt 生成一个明确任务、一个 Agent 的作业，显式设置 n_attempts=1、n_concurrent_trials=1、retry.max_retries=0，由平台决定是否创建下一 ExecutionAttempt。本阶段按 D-020：一个运行一个 Job，n_attempts 为每任务计划试次数，n_concurrent_trials 为运行并发；RetryConfig 的 max_retries、退避与不重试的异常名单由平台错误策略推出并显式下发，平台不再叠加外层重试，避免两层相乘（见 [实施记录](records/m3-execution.md) 的“M3 实施记录”）。字段路径按锁定版本导出的 schema 验证。

生产配置必须显式指定 Agent 和模型，不能因为 Harbor 的默认 Agent 为 oracle 而意外执行参考答案。Oracle 只用于测试模式，使用与模型评测不同的 execution_mode，不能混入模型能力比较。

## 7. 取消、资源与服务重启

Linux 使用独立进程组启动 Runner，建议通过 asyncio.create_subprocess_exec 并建立新会话。取消先通知协作停止，再向进程组发 SIGTERM，宽限后 SIGKILL；不调用拼接的 shell 命令。服务进程意外退出或协议管道断开时，Runner 自行按取消处理，不继续执行（M3 增补，见 [14](14-decisions.md)）。

结束进程组不能保证 Docker daemon 管理的容器、网络和控制 sidecar 都已消失。随后必须通过环境清理接口按 instance_id / run_id / trial_id / attempt_id 标签清理，并保留失败记录。心跳丢失时同样先确认旧资源已停止，再创建新尝试。

共享恢复使用 instance_id / preparation_operation_id 标签和独立进程身份；一个等待运行取消不终止该准备进程，最后一个等待者退出才可取消。准备阶段超时和构建容量独立受限，重试统一由平台调度。现状（缺口）：构建只受同时恢复数 `restore_slots` 限制，CPU / 内存不计入主机容量（M4）。服务重启也对准备租约与构建资源对账，不因能够重建缓存而自动续跑旧试次。

服务意外退出可能留下 Runner 与容器。启动对账检查持久 attempt 记录、PID / 进程启动标识及标签，不能只按可能复用的 PID 杀进程；保留已确认评分，按 05 标记未完成部分中断。若引入 systemd cgroup 辅助清理，也不替代 Docker 标签对账。

## 8. 复用 Harbor 现有语义

| 能力 | 核查结论 | 平台处理 |
| --- | --- | --- |
| 错误分类 | 官方 error_policy.py 只在 main 与开发构建中存在，0.24.0 稳定版没有 | 平台自定策略（14 U-15）；Harbor 公开分类只作初值参考，适配器把锁定版本的异常类型映射到 [06](06-results-scoring.md) 并留版本 |
| 分阶段网络 | Docker 支持 allowlist 与动态阶段切换，依赖 Linux nftables 内核能力 | 优先使用 Harbor 原生能力，不自建出口代理，见 [09](09-identity-security.md)。Runner 为收紧网络包装了 Harbor 的私有方法 `DockerEnvironment._apply_network_policy`，并调用私有的 `_egress_control_kernel_support` 预检；Terminus-2 传密钥覆盖了 `_init_llm`。这些都是升级风险，升级 Harbor 时须逐项复核（M5） |
| Hub 引用 | datasets[].ref / tasks[].ref 支持标签、修订或 digest | 标签解析后固定 digest，区分上游摘要与本地材料摘要 |
| Oracle | 默认 Agent 为 oracle，执行任务参考解法；solution 目录可选 | 选有参考解法且无需外部模型的任务作真实链路测试 |

文档核查确认的是上游公开契约，运行时能力仍以锁定版本和目标主机实测为准。网络不支持时拒绝运行，不能静默退回 public。

## 9. 为什么仍然自建

Hosted Harbor 已提供通过网页、CLI、API 发起远程作业的能力，官方指南当前要求申请远程运行权限。因此，“Harbor 没有网页或 API”不能作为自建理由。

本项目的设计定位是：

- 自托管与本地 Docker，执行资源、产物和运行策略由团队掌握。
- 使用团队自己的模型凭据、Harness 与不可变扩展包。
- Agent 作为操作者，具备 PAT、能力发现、预检、幂等提交和可接续操作记录。
- 统一保存配置来源、重跑关系、团队集合、分析快照与本地保留规则。

这些是本项目选择的控制面与工作流目标，不断言 Hosted Harbor 永远不提供同类能力。首期不接入 Hosted Harbor 作为远程执行后端；如果以后 Hosted Harbor 已能满足团队的部署、权限、扩展与保留要求，应重新比较自建维护成本。

## 10. 建议首周完成的最小原型

这是实施前优先验证清单。四项已于 M1 在 Linux 上完成原型，结论与缺口见 [实施记录](records/m1-validation.md) 的“M1 验证记录”（V-10、V-07、V-05、V-11），M3～M5 按其结论实现；兼容清单尚未实现，证据记在对应 V 项。

| 编号 | 风险与最小输入 | 通过标准 / 证据 | 未通过时 |
| --- | --- | --- | --- |
| TECH-01 | 子进程实时进度：一个可控制阶段时长的任务，Runner 同时产生大量 stderr | 准备、Agent、验证和收集事件可实时、有序读取；stdout 协议不受终端输出污染；进程异常时有最终状态，无管道死锁 | 针对锁定版本使用回调、插件或受控结果观察；若只能最终回读，则不满足当前实时阶段进度验收，须继续适配或明确调整发布范围 |
| TECH-02 | 网络：public 任务、已有 allowlist 任务、no-network 任务；支持和不支持 nftables 的主机 | 准备依赖可下载，Agent / 验证策略切换生效；平台能收紧 public，不能放宽作者更严约束；缺能力时拒绝 | 验证明确覆盖入口或临时生效配置副本；无法可靠收紧则阻塞 P0 接入 |
| TECH-03 | 独立准备：首次成功准入、回收缓存，再由多个成员 / PAT 运行并发等待；注入取消 / 临时下载失败 / 真缺失 | 无 Agent / 验证即可准备；冷缓存按原 digest 恢复一次并共享，等待取消独立；缓存发布 / pin / 资源计量可靠；暂态错误不撤准入，真缺失阻塞两种提交 | 在 Runner 包装已验证的 BaseEnvironment 准备调用；不能以真实执行冒充预加载，也不把缓存缺失变成管理员门槛 |
| TECH-04 | bootstrap：成员 / PAT 上传包并提交多个试次，在 Agent setup 安装测试依赖、注入超时 / 失败，检查 Docker 挂载与网络 | 无管理员动作，每试次容器独立安装且无宿主目录挂载；文件通过传输接口复制；有超时 / 摘要 / 日志；失败局限于本试次，执行 / 验证恢复网络限制；P0 无共享安装层 | 调整 Agent setup 包装与文件传输并重验；不能移到 agent.run 下载，不能靠开放宿主目录或要求管理员逐包准备规避约束 |

Job config 中 install_only 只表示运行 Agent setup、跳过 Agent 执行与验证，不自动证明得到可复用的独立环境准备缓存。Harbor 官方存在 skills、MCP 和环境变量字段，也不自动证明 bootstrap 已有统一钩子；两者分别由 TECH-03 / TECH-04 验证。

建议以 pytest 驱动协议和假适配器测试，再在 Linux / Docker 主机用管理脚本安装发布包完成真实任务原型。保留日志、结果与版本摘要作为证据，不依靠手工终端观察作唯一验收。

## 11. 接入完成标准

1. 服务端依赖锁、导入和运行时进程均不直接加载 Harbor。
2. 可从锁定 Runner 导出 schema，适配器的异常映射有版本与摘要。
3. Harbor Job 内的重复试次与重试都由平台显式下发（n_attempts、RetryConfig），不使用 Harbor 默认名单，平台不叠加外层重试（D-020）。
4. Oracle 完成真实 Docker 准备、执行、验证、事件、产物和清理链路；另用假执行器覆盖错误。
5. Agent 超时、提供商错误、非法奖励及取消映射与锁定策略一致。
6. 在支持 nftables 的主机验证准备、Agent、验证三个阶段网络；不支持时明确阻塞。
7. 进程组终止后 Docker 与 sidecar 标签清理通过，重启无重复执行。
8. 公共 OpenAPI 能生成网页客户端和 SDK 类型，Python SDK 不依赖服务端或 Harbor。
9. 已准入冷缓存任务可由成员 / experiment PAT 直接提交，按原内容共享恢复且独立取消；暂态失败不撤准入，内容不可得有准确摘要与阻塞。
10. 附件在每试次容器内独立安装，除本试次输出目录外无宿主目录挂载，安装与总时限、失败隔离及阶段网络切换通过。

## 12. 核查来源

以下官方资料于 2026-10-22 读取核对。网站内容会更新，发布时需针对锁定版本重新保存兼容证据：

- [Harbor 文档索引](https://docs.harborframework.com/llms.txt)
- [Release policy](https://docs.harborframework.com/contributing/release-policy.md)：稳定版通常双周发布，minor 可有破坏性变更。
- [Job configs](https://docs.harborframework.com/jobs/configs.md)：schema、dry-run、retry、默认 oracle 与 Hub ref。
- [Error classification](https://docs.harborframework.com/jobs/error-classification.md)：cause、retry、grade、reward_valid。
- [错误策略源码](https://github.com/harbor-framework/harbor/blob/main/src/harbor/models/trial/error_policy.py)：核对时读取 main；只作平台策略初值的参考。
- [Network policies](https://docs.harborframework.com/tasks/network-policies.md)：阶段、能力、nftables 条件与模型服务端工具边界。
- [Datasets](https://docs.harborframework.com/datasets/datasets.md)：Hub、目录、Git 三类来源；平台首期仍仅 Hub。
- [Task solution](https://docs.harborframework.com/tasks/solution.md)：Oracle 依赖可选的 solution 参考脚本。
- [Hosted Harbor](https://docs.harborframework.com/hosted-harbor/index.md)：远程作业、申请入口、网页 / CLI / API。

用户提供的 x-cmd 页面是第三方安装说明；本轮设计结论使用上面的官方资料作为依据。

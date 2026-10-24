# M7 SDK 与网页实施记录

导航：[决策记录](../14-decisions.md) · [实施记录索引](README.md)

本页由决策记录拆出，按记录时点保留，不随后续实现改写为“最新状态”；后来的用户决定或实现若推翻其中做法，以决策记录第 0 节和对应模块文档为准。

## M7 实施记录（SDK 与网页）

**2026-10-24。** 实现 13 的 M7：由 OpenAPI 生成网页类型与 SDK、能力发现、按 11 整理网页。以下是实现中的选择，均为设计建议层面，未经用户逐条确认。

| 事项 | 原设计 | 实际做法 | 理由 |
| --- | --- | --- | --- |
| 受控契约 | 10 第 1、8 节：同一构建产物生成网页与 SDK 类型，CI 检查无漂移 | 服务导出的文档提交为 `openapi/maestro-v1.json`。operationId 取路由处理函数名（重名在生成文档时报错），所有接口的错误都声明为 `ErrorResponse` 外壳（FastAPI 默认描述的 422 `HTTPValidationError` 实际从不发出，已去掉）。`tools/generate_clients.py` 写契约与 SDK 模型，`--check` 只比较；网页在 `frontend/` 用 `npm run gen:api` / `check:api` | 重写分支还没有 CI：Python 一侧的漂移由 `test_sdk.py` 发现，网页一侧要跑 `check:api`（需要 Node） |
| SDK 的形态 | 10：httpx；生成代码与手写的等待、分页、下载辅助层分开 | 单独的包 `sdk/`（`maestro-sdk`，Python ≥ 3.10，只依赖 httpx 与 pydantic），开发环境以可编辑方式装入。`models.py` 由 datamodel-code-generator 0.86.0 生成 pydantic v2 模型（允许未知字段，枚举为 Literal）；`client.py` 手写，按资源分组：`catalog`、`configs`、`attachments`、`plans`、`runs`、`batches`、`operations`、`artifacts`、`exports`，另有 `capabilities()`、`require()`、`me()`、`system_status()` | 模型给 Agent 属性访问与类型；没有承诺向后兼容，SDK 与服务同版本发布 |
| 版本发现 | 10 API-06：兼容不匹配时先报 UNSUPPORTED_CAPABILITY | `/capabilities` 新增 `contract_digest`（契约文档的规范 JSON 摘要），SDK 内置生成时的摘要：不同只发 `ContractDriftWarning`；`require(*features)` 在 API 版本不是 v1 或功能关闭时抛 `UnsupportedCapability`；响应解析失败抛带提示的错误 | 开发期间契约经常变，摘要不同不代表不能用；真正用不了的地方会在解析时明确失败 |
| SDK 的范围 | 10：网页与 SDK 能力一致 | PAT 能用的接口全部有 SDK 方法，测试按契约逐个核对（新增接口不加方法就失败）。不在 SDK 里的：管理接口、网页账号流程（初始化、登录、邀请、本人 PAT 与密码）、外部数据源检索（U-20）、健康检查——它们按设计只给网页会话或部署 | 能力接口已写明 PAT 不能管理 PAT；把这些放进 SDK 只会得到 403 |
| 提交与重试 | 10 第 5、7 节：幂等键；SDK 不自动重提运行 | `runs.submit`、`runs.rerun`、`batches.submit` 不传键时生成一个，结果与 `TransportError` 都带着它。只有读请求和带键的提交会在连接错误或 502 / 503 / 504 时由 SDK 重试（最多 3 次，同一个键、退避加抖动、遵守 Retry-After）；其他 POST（解析、导出、取消）只发一次，拿不到回答就报“结果未知”。429 不重试。`runs.find(client_request_id)` 用于丢了键之后找回 | 同键重试由服务端保证只受理一次；不带键的创建请求重发可能多建一个对象 |
| 等待 | 10 第 7 节：初始 1 秒、逐步到 5 秒、抖动；客户端超时不取消 | `operations.wait(timeout=, interval=1, max_interval=5)`，每次 ×1.5，超时抛 `WaitTimeout`（带最后一次看到的 Operation），不取消服务端 | 同设计 |
| 下载 | 10 第 7 节：校验摘要、安全重试 | 流式写到目标旁的临时文件，与服务给的 `X-Content-Digest` 比对后原子改名，不符时删掉并抛 `ContentMismatch`。`runs.download_artifacts(run_id, 目录)` 只保存 available 的文件，放在 `run/…` 与 `trials/<试次>/<尝试>/…` 下（拒绝绝对路径与 `..`），其余逐个返回状态与原因 | 过期、保存失败、已删除要能和“下载成功”区分 |
| 代理 | — | 默认 `trust_env=False`：直连，不读代理环境变量；需要时显式打开 | 令牌不经过调用方没有选择的代理；也避免环境里的 SOCKS 变量让 httpx 无法启动 |
| 附件上传 | 03 第 6 节 | `attachments.publish` 接受目录（在客户端打成 tar.gz，遇到符号链接即拒绝）或 .zip / .tar / .tar.gz 文件，字节与网页相同 | 服务端只接受普通文件与目录 |
| 时间筛选 | 10：RFC 3339 | 运行列表的 `accepted_after` / `accepted_before` 也接受不带小数秒的时间（如 `2026-10-24T08:00:00Z`）；之前只认带小数秒的写法，SDK 测试发现 | 两种都是 RFC 3339 |
| 删除的基线 | 13 M7 行 | 研究客户端 skill（`skills/harbor-helper-research`）、它的说明与基线附件说明（`docs/guides/`）、最后的 `src/harbor_helper/` 模块。`configs/`、`examples/`、`images/` 留给 M8 | 基线已无 `commands/` |
| Agent 用的 skill | 13 M7 行：三个故事各有一条由 agent 经 SDK 走完的场景 | 新的 `skills/maestro-sdk/SKILL.md` 取代旧的研究客户端 skill：连接与令牌保管、六步工作流程（能力 → 输入 → 解析 → 确认费用 → 提交 → 等待与读取）、如实报告结果的规则（有效零分、未评分、未知用量、跳过的证据、Oracle 不与模型比较）、丢失回答后的恢复、后续操作与常见错误码。真实模型运行会花钱，skill 要求先说明计划试次数并取得用户同意。`sdk/README.md` 是完整参考；测试核对两者提到的每个 `client.…()` 调用都真实存在 | 用户问到 SDK 是否配有 skill（2026-10-24） |
| 网页类型 | 11：业务客户端由公共 OpenAPI 生成 | `openapi-typescript` 7.13.0 生成 `frontend/src/lib/schema.d.ts`（`--default-non-nullable false`，否则带默认值的请求字段变成必填），`types.ts` 只是生成类型的别名。请求函数按路径推断：`api.get("/runs/{run_id}", { path: { run_id } })`，路径参数、查询、请求体、必填请求头和返回的 `data` 都来自生成的 `paths`，调用处不写类型参数 | 见下面“前后端类型对齐” |
| 工作台 | 11 第 1、6 节：工作台；“待处理”是业务记录的查询视图 | `/` 是工作台：系统能否受理、我的近期运行、团队近期结果，以及由现有接口实时算出的待处理（本人运行里中断或出错的试次；清理或产物保存失败的运行，管理员看全团队；管理员另见未全部准入的数据集版本与失败或中断的导入、首次准备），每项链接到源对象，没有“标记已处理” | 11 第 6 节；“停用但仍在使用的对象”现有接口取不到，未做 |
| 执行页（U-07） | 11 第 3 节、05 EXE-03 | 运行详情上方保留摘要、状态卡、计数与操作栏；下面分“执行 / 结果汇总 / 配置快照 / 产物”标签（`?tab=`）。执行标签左栏列试次（状态图标、任务、第几次重复、耗时、得分，零分、未评分与失败分开），右侧是选中试次的执行尝试与步骤，步骤可展开看日志，进行中的步骤自动展开并跟随最新输出；选中的试次在 `?trial=` 里，刷新不丢 | 用户要求像 GitHub Actions |
| 管理与维护页 | 11 第 1、5 节 | 管理页改为左侧分栏，每个分区有自己的地址 `/admin/<分区>`：成员与邀请、凭据与主密钥、模型、Harness、团队策略、容量、数据集导入（导入本身仍在数据集页，这里列近期导入与首次准备）、回收站、审计、维护。维护页显示存活、就绪、能否受理、Worker、执行器、主密钥、数据库结构、存储与各版本号（含契约摘要），没有更新或备份按钮 | P0 未实现的维护动作不显示为可用（11 第 5 节） |
| 设置页 | 11 第 5 节 | PAT 流程不变，另有“SDK 快速上手”卡片：安装、按当前地址填好的示例代码、令牌放环境变量，并指向 skill | 网页与 SDK 能力一致的入口 |

验证范围：服务测试 498 项通过（此前 486 项），`ruff check`、`ruff format --check` 干净（含 `tools/`、`sdk/src`）。新增 `tests/maestro/test_sdk.py` 12 项，经 TestClient 的传输层调用真实应用：故事一（E2E-DS-03）成员的只读与 experiment PAT 经 SDK 读目录、版本、任务的准入与冷缓存、数据源，外部检索与管理接口被拒，只读 PAT 不能提交，experiment PAT 在冷缓存上提交、运行内恢复、无管理员动作；故事二（E2E-RUN-01）管理员预先准备凭据、模型与 Harness 后，Agent 只用 SDK：`require` 能力、读目录与模型、解析（超上限时 `raise_for_blockers` 报错）、提交、同键重放、等待、读试次得分与汇总、下载全部证据并核对摘要、按 `client_request_id` 找回；故事三（E2E-OUT-01）筛选（含跨页游标与不带小数秒的时间）、零分 / 未评分 / 执行失败区分、导出、下载并核对清单、包内没有令牌。另有：客户端等待超时不取消运行；提交的回答在传输中丢失时 SDK 用同一个键重试，只建一个运行、只扣一个额度，而普通 POST 不重发、报结果未知；错误带结构与 request_id、不含令牌；目录与 tar.gz 两种方式发布附件得到同一版本、含符号链接的目录被拒；PAT 可用的每个接口都有 SDK 方法；能力接口的契约摘要与 SDK 内置的一致；屏蔽 `maestro`、`fastapi`、`sqlalchemy`、`harbor` 后 SDK 仍能导入；受控契约与 SDK 模型与当前代码一致；skill 与 SDK 说明里的调用都存在。真实 HTTP：在全新的一次性 state 上以 `--demo-executor` 启动服务，管理员一侧用网页会话接口准备，Agent 一侧用 `python -I` 只调 SDK，三个故事走通（检索被拒 403、模型运行 6 个试次评分、12 个证据文件下载并核对、按任务重跑、两个运行导出 28 个文件无缺失），服务停止后 state 已删除。前端：`npm run check:api` 与契约一致，`tsc`、`npm run build` 通过，`npm run lint` 8 条原有类型的警告（此前 10 条）；Playwright 冒烟 3 项在全新的一次性 state 上通过，新增工作台、执行页（选试次、地址带 `trial=`、展开步骤看到日志、刷新后仍选中）、管理分栏与维护页、设置页 SDK 卡片的检查。环境：CPython 3.13，Node 依赖按锁文件，Linux 6.8；没有运行真实 Docker 与真实模型测试（本里程碑不改执行）。

未覆盖：CI 尚未建立，网页类型的漂移只能手动跑 `check:api` 发现；SDK 只能从仓库安装，服务端还不提供安装包下载，也没有发布到包索引；SDK 的 Literal 枚举遇到更新服务新增的取值会解析失败（同版本发布时不会出现）；待处理里的“停用但仍在使用的对象”；数据集页没有指向单个版本的地址，待处理中数据集事项只能链到列表；真实 Agent（而非测试脚本）照 skill 独立走完三个故事尚未演练。

## M7 补充：前后端类型对齐（2026-10-24）

13 的 M7 行要求“由 OpenAPI 生成前端类型和 SDK”，10 第 8 节要求 OpenAPI 覆盖所有响应。第一版只做到“类型从契约生成”，大量响应字段在后端仍是 `dict[str, Any]`，生成的类型对它们没有约束；用户确认这属于 M7，随即补完。以下为实现选择，未经用户逐条确认。

| 事项 | 做法 | 理由 |
| --- | --- | --- |
| 具体模型 | 原来 53 处 `dict[str, Any]` 全部换成具体模型：配置解析的请求、生效配置、字段来源、基准差异、排除的任务、恢复计划、缓存观测、警告、引用修订；运行快照的生效配置、来源（含重跑来源与差异）、策略；评分契约与通过规则；任务的资源与时限、阻塞项、证据与参数问题；准备原件；方案模板；Harness 参数定义；执行尝试的错误；导出摘要；批次预览与进度；能力接口；系统状态；所有删除状态。错误与失败统一为 `Problem`（代码、消息，以及有时才有的种类、证据、下一步）或 `AttemptError` | 生成的网页类型与 SDK 模型才真正约束这些字段 |
| 仍然开放的字段 | 只有设计上就开放的 15 个字段保留为任意 JSON（`JsonValue`）：服务商请求参数、执行器标识与诊断、失败证据、配置差异的前后值、准备原件与准备记录的环境细节、回收站清除回执、审计详情；另有 `Problem`、`SuggestedAction`、`ScoringContract` 在已知字段之外允许附加字段。`tests/maestro/test_api_contract.py` 维护这份清单，新增未建模的字段即失败——它当场发现了管理员确认评分契约的接口返回 `Envelope[dict]` | 这些值的结构属于服务商、执行器或具体原因，平台不应假装知道 |
| Operation | 按 `kind` 区分的联合类型：运行、批次、导出、数据集导入、首次准备、缓存恢复、缓存回收，各有自己的进度与结果类型；网页按 `op.kind` 收窄，SDK 返回具体成员 | 进度与结果的结构确实随种类不同 |
| 请求与响应分开 | 基础模型设 `json_schema_serialization_defaults_required`，FastAPI 为同时用作请求与响应的模型导出 `-Input` / `-Output` 两份 schema：响应里带默认值的字段是必填，请求里仍可省略（`ConfigRequest`、`PlanTemplate`、`TaskSelection`、`HarnessParameterSchema`）。SDK 相应有 `ConfigRequestInput` / `ConfigRequestOutput` | 页面不必再为“服务端总会给的字段”写兜底 |
| 不适用的字段 | 一类“稀疏”对象（字段来源、阻塞项、问题、参数取值、资源与时限覆盖、方案模板、重跑来源、批次预览的成员等）把不适用的字段省略而不是发 null，在类型里是可选 | 保持原有的线上格式，读者只看到与该代码有关的字段 |
| 响应一律校验 | 原来直接构造 `JSONResponse` 的 5 个路由（提交运行、重跑、批次、导出、发布附件）改为先按声明的模型校验再返回，与其他路由一样 | 否则这些响应可以悄悄偏离契约 |
| 暴露并修正的问题 | ①方案模板把作者参数存成内部格式 `{"value": ...}`，用方案提交带作者参数的运行会被请求检查拒绝——改为按请求格式保存，新增测试（修复前失败）；②开发与测试用的进程内导入少了 `accept_changed_content`；③`RUN_TOO_LARGE` 的附加字段 `tasks` 与 `TASKS_NOT_SUBMITTABLE` 的 `tasks` 同名不同义，改为 `task_count` / `trial_count`；④任务作者参数的 `hard_constraints` 始终为空、没有实现，不再出现在 API 里；⑤`/health/live` 不再带空的 `detail`，系统状态改为单独的 `SystemStatus`；⑥网页把布尔查询参数当字符串传、回收站与评分方向的取值是任意字符串、可能拼出 `/preparations/null/evict` 等前端错误，由按路径推断的类型发现并修正 | — |
| 契约收紧带来的变化 | 方案模板里的未知字段、Harness 参数定义里不认识的类型，现在由契约在请求层拒绝（`REQUEST_INVALID`，指向具体字段），不再由服务给出 `CONFIG_VALIDATION_FAILED` / `HARNESS_INVALID` | 契约本身写明了允许什么 |

合并 M5 独立审查（2026-10-24）时，强类型契约当场发现审查新加的两处字段：批次进度的 `deleted_runs`、作者参数问题 `RESERVED_NAME`（带 `used_in`），已补进模型。U-27 对非管理员会话隐藏模型绑定的凭据，线上格式保持不变，契约如实写明：`EffectiveModel.credential_id` 是可选字段，省略表示对你隐藏、`null` 表示没有绑定；配置差异的 `hidden` 只在被隐藏时出现。审查的一项测试（方案模板里 `task_ids` 类型错误）按本节的规则改为期望 `REQUEST_INVALID`。合并后服务测试 517 项通过，网页类型检查、构建、契约比对与 Playwright 冒烟 3 项通过。两边都没有改 `schema.py` 与迁移，无需重新生成 `0001`。

验证范围：服务测试 500 项通过（新增契约检查 2 项、方案作者参数回归 1 项；按更严的契约更新了 5 项断言），`ruff` 干净，契约与 SDK 模型为最新；网页 `check:api`、`tsc`、`npm run build` 通过，`npm run lint` 仍为 8 条原有警告；`types.ts` 只剩生成类型的别名，原有的 5 处桥接断言与因字段无类型或可选而写的兜底全部删除，留下的只有契约确实可选的字段（如附件列表不带 `files`）、逐键复制请求的通用代码、`/health/*` 与两处二进制下载（不经 JSON 客户端），以及 `<select>` 的取值。Playwright 冒烟 3 项在全新的一次性 state 上通过（模拟数据的两个响应按新契约改正）。没有重跑真实 HTTP 的 SDK 走查（SDK 的解析路径由经 TestClient 的测试覆盖）。

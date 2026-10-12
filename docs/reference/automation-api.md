# 自动化授权与机器 API v1.0

这是当前分支的实施接口，候选验收范围另见[工程报告](acceptance/automation-v1/engineering-report.md)。成员额度、维护与就绪的当前契约见下文；设计来源见[定稿](../design/attachment-agent-contract.md)。原工程报告只证明其固定版本，当前改动范围见[额度维护工程报告](acceptance/admission/engineering-report.md)。

## 身份与签发

浏览器登录会话保留成员/管理员角色。网页“自动化凭证”签发有用途名称的凭证，默认 30 天，可选正整数天数，不设年度上限；API 可传有限且严格在未来的 Unix 秒 `expires`，省略使用 30 天。签发复核当前密码，失败保留网页会话并清空密码框。凭证形式为 `hh_pat_v1_` 加 32 随机字节的 43 字符 base64url，无填充。`token` 仅在成功签发响应中出现一次；关闭页面/原值后无法恢复。服务数据库只存 SHA256 摘要和非秘密元数据。

| 浏览器操作 | 请求/输出 |
| --- | --- |
| `POST /api/v1/access-credentials` | JSON `{name,current_password,scopes?,expires?}` → 201 `{credential,token}`；只允许会话，须正确密码 |
| `GET /api/v1/access-credentials` | 本人的元数据列表；没有 token/digest |
| `GET /api/v1/admin/access-credentials` | 管理员会话读取全团队元数据 |
| `POST /api/v1/access-credentials/{id}/revoke` | 所有人可撤自己的；管理员会话可撤任意 → `{id,revoked:true}` |

元数据字段：`id,user_id,name,scopes,created,expires,revoked,last_used`；时间为 Unix 秒，尚未撤销/使用时为 null。`last_used` 表示成功认证时间，包含随后被 scope 拒绝的请求，不等同于成功执行。签发、撤销、写操作保留审计身份。账户停用、凭证到期/撤销、密码重置立即拒绝后续认证；恢复账户不恢复被撤销凭证。密码变更及管理员密码重置同时使旧浏览器会话失效。

固定能力为 `read`、`attachments`、`execute`、`cancel_own`，默认 `['read']`，各能力独立勾选。`execute` 不隐含 read；按原键找回需要 execute。`GET /me` 仅返回已认证身份和能力，对所有有效凭证可用，供 CLI 安全配置验证。授权只属于该用户已有能力的子集；管理员签发的凭证也按成员权限执行，不能维护别人附件、取消别人任务或调用管理员/账户/凭证管理操作。持有凭证不能再铸造凭证或扩大权限。服务端按固定操作表鉴权，新或未列操作默认只允许会话，客户端隐藏按钮不是授权边界。

自动化 HTTP 使用 `Authorization: Bearer <私有值>`；写请求另需 `X-Requested-With: harbor-helper`，有 Origin 时须与服务一致。不得将原值放 URL、命令参数、shell history、附件、日志或报告。HTTPS/代理日志由部署环境负责。请求原值仅在请求内存中用于验证/扫描，worker、env、冻结输入只得到非秘密 `access_credential_id`；该字段与模型 `credential_id/version` 分开。复制父实验输入时重新记录当前用户和访问凭证 ID；网页受理为 null（冻结绑定可能省略该键），不继承父授权。

## 发现、输入及输出 schema

`GET /api/v1/machine/schema` 返回限定的 OpenAPI 3.1 文档，版本 `1.0`，只含下表机器操作，包含命名输入/输出 schema、枚举、错误结构、Bearer 声明与每操作 `x-capability`、`x-operation`。不开放内部管理员 OpenAPI。multipart 的 `metadata` 是 JSON 字符串，其结构另由 `x-metadata-schema` 引用，不能按任意字符串解释。

| 操作标识 | 方法与路径（相对 `/api/v1`） | 能力 | 类型/语义 |
| --- | --- | --- | --- |
| `machine_schema` | GET `/machine/schema` | read | 限定 OpenAPI 文档 |
| `discovery` | GET `/machine/discovery` | read | `Discovery`：数据集验证/可用状态、模型方案、附件版本、容量、scheduler、本凭证允许操作、限制 |
| `task_catalog` | GET `/machine/datasets/{dataset_id}/tasks?offset=0&limit=100` | read | `TaskCatalog`：已有验证任务目录的切片；offset≥0、limit 1–100，next_offset=null 结束；不下载任务字节 |
| `machine_submission` | GET `/machine/submissions/{id}` | read | `MachineState`：受理及可能已生成实验的三轴视图 |
| `machine_run` | GET `/machine/runs/{id}` | read | `MachineState`：实验三轴视图 |
| `machine_report` | GET `/machine/runs/{id}/report` | read | `SafeReport`，仅可用时 200，否则安全错误；不返回原始异常/环境配置/诊断 |
| `machine_compare` | POST `/machine/compare` | read | `CompareInput {left,right}` → `Comparison`；保留可比性/原因/附件身份/评分变化，配置仅显示 changed |
| `submit` | POST `/submissions` | execute | `SubmissionInput` → 202 `Accepted` |
| `rerun` | POST `/runs/{id}/rerun` | execute | 空正文/`{}` → 202 `Accepted`，继承固定研究输入 |
| `retry_run` | POST `/runs/{id}/retry` | execute | `RetryInput {wall_seconds?}` → 202 `Accepted`；保留已有修复作者参数差别，附件不能替换 |
| `recover_submission` | POST `/submissions/{id}/retry` | execute | 空正文/`{}` → 202 `Accepted`；只为尚未生成实验的失败准备新建恢复受理 |
| `lookup_submission` | GET `/submission-operations/{operation}/{key}` | execute | `Accepted`；operation 固定 submit/rerun/retry/recover，按原成员+类别+键查找 |
| `cancel` | POST `/runs/{id}/cancel` | cancel_own | `CancelResult`，只取消自己实验；取消请求不保证已完成清理 |
| `cancel_submission` | POST `/submissions/{id}/cancel` | cancel_own | `Accepted`，只取消自己受理 |
| `attachments` | GET `/attachments` | read | `AttachmentCatalog`，共享身份/版本与 legacy bundle 元信息 |
| `upload` | POST `/bundles`，multipart file | attachments | 201 `BundleResult {id,digest}`，旧上传兼容 |
| `create_attachment` | POST `/attachments`，multipart file+metadata | attachments | `AttachmentCreate {name,description?}` → 201 `AttachmentResult` |
| `publish_attachment` | POST `/attachments/{id}/versions`，multipart file+metadata | attachments | `AttachmentPublish {notes?}` → 201 `AttachmentResult`；仅自己有权维护的附件 |
| `derive_attachment` | POST `/attachment-versions/{id}/derive`，multipart file+metadata | attachments | `AttachmentCreate` → 201 `AttachmentResult`，上传自己的内容派生 |
| `register_attachment` | POST `/attachments/register` | attachments | `AttachmentRegister {name,description?,bundle_id}` → 201 `AttachmentResult`，登记 legacy 输入 |
| `attachment_lookup` | GET `/attachment-operations/{operation}/{key}` | attachments | `AttachmentResult`；固定 attachment_create/publish/derive/register |
| `update_attachment` | PATCH `/attachments/{id}` | attachments | `AttachmentUpdate {name?,description?,enabled?}` → `{updated:true}`；创建者权限 |
| `update_attachment_version` | PATCH `/attachments/{id}/versions/{version_id}` | attachments | `AttachmentVersionUpdate {enabled}` → `{updated:true}`；创建者权限 |

`Discovery.allowed_operations` 使用上述操作标识，另包括有明确能力的旧兼容操作：me/catalog/usage/runs/submission/run/report/download_report/compare。这些别名保留 HTTP 兼容，但自动化 catalog/run/list/report 会采用安全投影；原始 logs/artifacts/download 只向浏览器会话开放。机器契约优先使用 `/machine/...`。旧会话远程 profile 保留原角色及旧响应。

`SubmissionInput` 严格拒绝未知字段和错误类型，身份不由客户端提交。可用字段：`dataset_id`（网页配置的数据集，优先）、`dataset`（旧显式引用）、`model_profile`、`agent`（oracle/opencode）、`bundle_id` 或 `attachment_version_id`（互斥）、`attempts`、`concurrency`、`wall_seconds`、`environment_build_timeout_multiplier`、`task`、`name`。数值为正整数且继续受现有团队限额校验；name≤128 字符。选择 task 使用任务名 glob；省略 task 选择整个数据集。模型实验选择方案，Oracle 显式选择 agent。省略两个附件字段是无附件基线；版本必须明确，不接受 latest，不自动沿用。dataset 验证/ready 仅表示当前配置的来源检查，不证明作者输入、Docker、Hub 或模型下一次一定可执行。

`Accepted` 保留旧 id/status/request/run_id/parent/submitter/created/error 及附件/执行模式字段，新增 user_id/access_credential_id。token 调用不输出原始作者诊断或配置变更值。输入和输出的详细字段、null/可选规则以运行时 schema 为准；机器报告只给各任务的有效性、聚合评分、尝试奖励和安全失败类别。有效 0.0 是合法评分；缺评分为 missing_score；执行异常为 execution_failure，证据不足为 unknown，不凭 run status 推断评分。

## 幂等与通信恢复

实验写操作必须携带 1–128 字符 `Idempotency-Key`。保存正文、固定操作、目标及原键再发请求；CLI 附件发布也要求显式键。新受理作用域是当前成员+固定操作类别+键；父 run/submission ID 属于请求摘要，不编入类别，因此同键换目标或正文都冲突。普通 rerun/retry/recover 是新研究尝试，必须主动用新键；通信重试重复原正文/原目标/原键。

身份及 scope 在最前。已经匹配的受理先于当前容量等新受理检查返回；不会再次占用队列。跨同成员 token 或网页登录可查询原键；跨成员返回 404，不返回别人正文。未知键 404 只说明暂未观察到提交，下一步保持原键重发，不能以此自动换键。到期/撤销的凭证必须重新授权；键本身不随凭证或证据到期而删除。

旧记录不改写：submit 沿用旧摘要；旧 `rerun:<target>` 等可按原目标原键通信重试，固定类别查询也匹配旧前缀。历史同类别同键对应多个目标时返回 `legacy_key_ambiguous`，用原记录 ID 查询并人工确认，不能任选一条。新写也不能拿已占用的旧键换目标。

## 三轴状态与下一动作

三轴来自现有受理/实验生命周期，不更改旧 manifest 或执行状态、不按显示状态追加容量阻塞：

- resource：active（starting/running/cancelling）、cleanup_blocked（原执行资源未确认清理）、released（准备/排队未分配，或按原终态生命周期已释放）、unknown（不能解释的执行状态）。原容量仍只按实际执行/清理规则统计。
- audit：pending/clean/incomplete；没有实验为 pending/not_started，未知旧审计信息不伪造 clean。
- report：available 必须通过原安全报告门槛，含已过期证据的安全摘要；终态 clean 缺文件为 unavailable/missing_report，失败准备或提前取消为 unavailable。审计异常/资源清理阻塞为 blocked；审计 pending 且 scheduler 活动无法确认为 blocked/audit_progress_unknown。确有活动执行/准备/审计才 pending，建议 2 秒轮询。读取失败不以空报告假装成功。

scheduler 仅提供可核进程身份和最近循环活动，`ready/unavailable/unknown`；身份匹配且 heartbeat≤10 秒（正常循环约 0.5 秒）才 ready，缺失/陈旧活动为 unknown，未核到存活进程为 unavailable。不输出 PID/birth/宿主路径/配置；`activity_observed` 为最后心跳时间，`observed` 为本次读取时间。判断身份与活动使用同一次 scheduler.json 读取，不把别的进程心跳拼到旧身份。

错误统一含 `code,message,request_id,retryable,action,related_ids,poll_after_seconds,wait_seconds,wait_known`。action 枚举：retry_same_request、poll_existing、fix_input、reauthorize、contact_admin、explicit_new_attempt。原键未知/队列满/暂不可用建议 retry_same_request；待报告 poll_existing；401 或 scope 不足 reauthorize；幂等冲突 fix_input（保留原键/原正文调查，绝不自动换键）；审计/安全阻塞 contact_admin；报告确定不可用或无效恢复状态 explicit_new_attempt。没有故障来源证据不猜原因。429/503 当前不承诺等待时长：`wait_known=false,wait_seconds=null`，客户端做有限退避；不将等待建议当作完成时间保证。

附件扫描沿既有完整树文件字节/路径扫描与输出脱敏，拒绝完整 PAT 格式（包括别人、撤销/过期值），请求内也检查当前实际 bearer；历史快照重跑时再核验，后台不接收原值。拒绝信息不回显命中内容。检查不声称识别任意编码、加密或分片秘密，可信成员仍须保护访问值。

研究客户端可使用[独立操作 skill](../guides/research-skill.md)，它复用下述 CLI/HTTP，不成为实验附件或另一个服务授权入口。

## 薄 CLI 非交互使用

先在网页签发；将原值安全存入当前用户独占、0600、非 symlink 的文件。CLI 不接受原值 argv 参数。安全读取文件或 stdin，将 URL/身份/值写入已有 owner-only 0700 remote profile/0600 文件，`service configure-token` 只输出非秘密确认。stdin 的上游应使用秘密管理器/安全文件，勿直接在 shell history 写 literal token。

```bash
harbor-helper service configure-token --url http://127.0.0.1:8000 --token-file /private/access-token --profile research --json
harbor-helper --remote-profile research service discover --json
harbor-helper --remote-profile research service schema --json
harbor-helper --remote-profile research service tasks DATASET_ID --limit 20 --json
harbor-helper --remote-profile research submit --dataset team/data@VERSION --agent oracle --idempotency-key baseline-1 --json
harbor-helper --remote-profile research service lookup submit baseline-1 --json
harbor-helper --remote-profile research service query sub-RECEIPT --json
harbor-helper --remote-profile research service report hh-RUN --json
```

模型实验改用 `--model-profile MODEL_ID`；明确版本对照新 submit 选择 `--attachment-version-id VERSION_ID` 和新键；不带该参数是无附件。`service retry` 重发最近一次保存的实验操作原正文/原键；单个 profile 只保存一个最近 receipt，研究客户端仍应自行保存并行请求。`rerun/retry` 原命令继续使用，失败准备的主动新恢复用 `service recover sub-ID --idempotency-key NEW_KEY`。`service logout` 对会话 profile 撤会话并删本地 profile；对自动化 profile 仅删本地副本，服务端撤销在网页完成。远程请求失败无本地执行回退，复用同一 HTTP 契约和队列。

## 迁移与回退

启动时用 SQLite 事务新增 `access_credentials`、`access_events` 表；无主密钥变更、无旧记录/manifest/评分重写。迁移失败异常退出，不允许新服务继续写。新表不保存原值；旧 sessions、submissions、模型凭据表保持结构。发布前核实际服务身份、所有 state 写者并保全最新一致 SQLite backup 和外主密钥，不能使用旧备份覆盖后来业务。本工程没有操作正式部署。

旧代码可忽略新增表读旧数据，但不能把代码回退当作安全业务回退：旧版本不识别 PAT/机器端点，旧 per-target 幂等逻辑可能重复新 fixed-operation 受理。需要回退时先切断新写流量、停止所有写者并保全当前一致 state；优先回退前端/修复兼容服务器，或交付能读取新键规则的回退代码。禁止在仍有新客户端通信重试时直接恢复旧受理写服务；禁止删除新表/键或回放过时 state。此处是接口/数据兼容说明，不是生产恢复演练通过证据。


## 新受理额度、维护与就绪

- `GET /health` 匿名仅返回 `alive,ready` 两个布尔值；未初始化/维护暂停/活动未确认时 ready=false。`GET /readiness` 是授权只读（PAT 需 read），也收入机器 schema 与 discovery.readiness。返回 initialized、accepting、reason、observed、scheduler、maintenance、pending；没有内部路径/PID/配置/秘密。`accepting` 表示维护与调度活动门已开放，不保留容量，不保证下一次请求可受理或 Docker/Hub/模型成功。
- `maintenance` 为 paused、reason、retry_at（可选 Unix 秒）、updated。管理员浏览器在团队管理→容量与保留调整；`PATCH /admin/maintenance` 支持这些前三项，权限默认拒绝管理员 PAT。原因最多500字符，禁止已配置秘密、PAT 和内部绝对路径；重试时间若填写须有限未来值，只是建议，不自动恢复。错误不回显输入。
- 暂停在独立 `admission.json` 原子持久写入，与受理使用同一 control 锁。每次新受理在锁内读取最新值，多个 API 进程与重启不使用旧缓存。维护拒绝 submit/rerun/retry/recover 新键（503 maintenance_paused）；已受理准备/队列继续排空，读、取消与安全报告仍遵守原门槛。暂停不是 scheduler stop 或可立即备份。
- 未确认 scheduler birth 返回 unavailable；身份可核但缺失、未来或超过10秒的心跳返回 unknown。unknown/unavailable 阻止新键（503 scheduler_unready）。身份/scope 先验证；成功原键找回在维护、就绪与额度检查前；参数冲突仍409，不通过新键补偿。
- `limits.max_pending_per_member` 默认配置10，可由管理员网页改正整数；有效值 `min(配置,max_queue)`，不是硬用户数值。pending 包含 global_pending/member_pending/member_limit/global_limit。所有 CLI/Web/PAT 入口、同成员所有凭证以及管理员本人共用 user_id；429 member_queue_full 或 queue_full 的 action 为 retry_same_request，wait_known=false、wait_seconds=null，预计等待未知。额度降低不取消存量。
- Preparing 与 queued 按 target_id 去重；已存在对应 run 后仅按当前 run queued 状态计待处理，即使 submission 未改 ready。开始执行、终态、准备失败或准备取消释放待处理；排队取消请求直到调度器确认为 cancelled 才释放。运行/cleanup_blocked 仍由原执行资源规则计容量，审计异常不额外占执行容量。旧 local/history 无可靠 user_id 不猜成员，保留全局与执行容量。没有公平调度保证或另一个配额账户系统。

### 兼容、升级与回退

本次不新增/更改 SQLite 表，不重写旧 manifest、冻结输入、密文或外主密钥。旧 limits.json 缺成员字段时读取默认10；不要求落盘迁移，维护文件缺失仅按首次默认开放解释，仍须 scheduler 就绪。维护文件损坏拒绝新受理并匿名 unready，不静默开放。按部署流程保全最新 state 和原外主密钥；生产升级需独立授权，本轮没有升级部署。

代码回退到本轮之前会忽略 admission.json 和成员字段，并且不执行新就绪门；**暂停保护不能靠旧代码继续维持**。需先停止外部新写入口、确认全部写者与队列/资源状态，再按固定旧版本执行回退，保留新文件和所有受理/幂等/历史数据；不可删文件开放、重 init、更换 master 或用旧备份覆盖新业务。恢复本轮代码后读取原持久暂停值。暂停/就绪不替代一致备份和独立 scheduler 停机确认。

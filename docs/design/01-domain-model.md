# 01 领域模型与数据设计

状态：设计建议；术语以原稿第二节为依据 · 阶段：P0

导航：[总览](00-overview.md) · 依赖：[配置](03-configuration-attachments.md)、[执行](05-scheduling-execution.md)、[评分](06-results-scoring.md)

## 1. 统一术语

“实验”只用于产品叙述，持久对象使用“运行”。“任务”只指数据集中的测试项目；Worker 领取的是“工作单元”，其首期粒度为一个计划试次。

| 对象 | 身份与职责 | 可变性 |
| --- | --- | --- |
| 数据集来源 DatasetSource | 提供目录和指定版本内容；首期仅 Hub | 接入配置可变 |
| 数据集 Dataset | 来源 + 作者 / 数据集名 | 说明可更新 |
| 数据集版本 DatasetVersion | Hub 明确引用 + 解析后的上游 digest + 本地材料清单摘要 | 内容固定，保留原标签 / 修订供展示 |
| 任务 Task | 版本内的稳定任务键 | 随数据集版本固定 |
| 任务准入 TaskAdmission | 任务内容 + 已批准准备方式 + 首次成功证明 | 带修订；不随缓存回收改变 |
| 内容可得性 ContentAvailability | 必要内容摘要 + 本地 / 来源检查证据 | 可更新；暂态失败不等于不可得 |
| 准备缓存 Preparation | 实际准备规格 + 位置 + 缓存状态 | 可回收、恢复；历史由 Operation 保留 |
| 恢复等待者 PreparationWaiter | 共享恢复操作与运行 / 试次 / 尝试的关联 | 可独立取消或到期 |
| 模型配置 ModelConfig | 提供商、模型、参数及凭据引用 | 创建新修订，不覆盖历史 |
| Harness 版本 HarnessVersion | 程序版本、内容摘要、参数契约 | 发布后固定 |
| 附件版本 AttachmentVersion | 能力包内容、作用范围及加载协议 | 发布后固定 |
| 实验方案 ExperimentPlan | 可编辑的实验模板 | 带修订号 |
| 运行 Run | 一次受理的实验 | 定义固定，状态演进 |
| 运行快照 RunSnapshot | 生效配置、来源、内容标识和口径 | 固定 |
| 试次 Trial | 运行中某任务的第几次计划执行 | 身份固定，结果演进 |
| 执行尝试 ExecutionAttempt | 同一试次的一次基础设施执行 | 每次独立记录 |
| 工作单元 WorkItem | 可领取的一个试次及当前尝试 | 调度状态可变 |
| 提交批次 SubmissionBatch | 一次原子成组受理的运行集合 | 成员固定，状态聚合 |
| 实验集合 ExperimentCollection | 持续维护的运行引用 | P1，可增删成员 |
| 分析快照 AnalysisSnapshot | 固定运行清单、配置和结果版本 | P1，内容固定 |
| 操作记录 Operation | 一次长操作的跟踪对象 | 状态和进度可变 |

“尝试次数”在产品配置中建议命名为“每任务计划试次数”，避免与 ExecutionAttempt 的自动重试混淆。API 分别使用 repetitions 和 attempt_index。

## 2. 实体关系

~~~mermaid
erDiagram
    DATASET ||--o{ DATASET_VERSION : contains
    DATASET_VERSION ||--o{ TASK : defines
    TASK ||--o{ TASK_ADMISSION : admits
    TASK ||--o{ PREPARATION : prepares
    PREPARATION ||--o{ OPERATION : restores
    OPERATION ||--o{ PREPARATION_WAITER : serves
    EXECUTION_ATTEMPT ||--o{ PREPARATION_WAITER : awaits
    EXPERIMENT_PLAN o|--o{ RUN : creates
    SUBMISSION_BATCH o|--|{ RUN : groups
    RUN ||--|| RUN_SNAPSHOT : freezes
    RUN ||--|{ TRIAL : plans
    TASK ||--o{ TRIAL : evaluates
    TRIAL ||--o{ EXECUTION_ATTEMPT : executes
    TRIAL ||--o| TRIAL_RESULT : resolves
    EXECUTION_ATTEMPT ||--o{ ARTIFACT : produces
    EXPERIMENT_COLLECTION ||--o{ COLLECTION_MEMBER : contains
    RUN ||--o{ COLLECTION_MEMBER : referenced
~~~

每个运行只有一个执行跟踪 Operation，批次另有聚合 Operation。首次准备、缓存恢复和导出各有自己的 Operation；同键并发恢复共享一个操作，通过 PreparationWaiter 关联多个运行。共享恢复不归首个等待者所有，其租约与进程身份独立保存。Operation 不代替业务对象，进度可从领域记录重建。

## 3. 通用数据约定

- 所有主键为服务端生成的不透明字符串；外部名称和版本号另列，不作为可变外键。
- 时间按 UTC 保存，API 使用带 Z 的 RFC 3339 字符串；网页按用户时区展示。
- CPU 采用毫核，内存与磁盘采用字节，时限采用秒；不混用 MB 与 MiB。
- 可缺失的评分、费用、token 使用 null，并提供 availability 或 reason；禁止用 0、-1 或空字符串代替未知。
- JSON 对象有 schema_version；参与哈希前按约定规范化键顺序、数值和空值，不包含展示文本、请求时间与凭据明文。
- 内容摘要带算法，例如 sha256:…；目录摘要基于按路径排序的文件摘要清单，禁止纳入随机临时路径。
- 可修改对象带 revision；更新需提交 expected_revision，过期版本返回冲突。
- 除主密钥外，业务对象都可删除，采用回收站两步删除（[07](07-artifacts-export.md) 第 8 节，用户决定 U-08）；名义删除后已有引用仍能解析。目录配置的停用与删除是两种操作，停用不影响已引用的不可变版本。

## 4. 核心表与字段

下表为逻辑数据字典。实现时可将较大的不可变 JSON 单独拆表，不能删去含义或唯一约束。

| 表 | 关键字段 | 约束与用途 |
| --- | --- | --- |
| users | id、role、status、password_hash、created_at | 仅 admin / member；移除使用 disabled |
| invitations | token_hash、expires_at、used_at、created_by、target_user_id | 单次邀请，不保存原始令牌；target_user_id 非空时为重置密码链接 |
| sessions | token_hash、user_id、expires_at、revoked_at | 网页会话只存摘要，可在服务端撤销（14 M2 实施记录） |
| pats | id、owner_id、token_hash、scope、expires_at、run_limit、accepted_runs、revoked_at | scope 为 read / experiment；计数只能在受理事务内增加 |
| credentials | id、kind、encrypted_payload、key_version、enabled、revision | 对外仅返回引用与脱敏描述 |
| datasets | id、source_kind、namespace、name、enabled、credential_id | 来源、namespace、name 在未物理删除的记录中唯一（导入事务检查；物理删除只留回执，可重新添加，M4 实施记录） |
| dataset_versions | id、dataset_id、upstream_ref、ref_kind、resolved_digest、materialization_digest、manifest_json、status | 上游 digest 与本地展开摘要分开；标签漂移不覆盖旧版本；同一数据集下未物理删除的版本按 resolved_digest 去重（M4 实施记录） |
| tasks | id、dataset_version_id、task_key、definition_json、content_digest、material_digest、spec_digest | 版本 + task_key 唯一；content_digest 是上游内容身份，material_digest 是本地文件摘要，spec_digest 是准备规格摘要 |
| task_admissions | id、task_id、preparation_method_digest、state、revision、evidence_json、approved_by、approved_at | task_id + preparation_method_digest 唯一；证据含任务 / 输入 / 必需输出摘要、参数契约与首次成功 Operation，回收不删除 |
| content_availability | content_digest、resource_kind、availability、evidence_json、checked_at、revision | content_digest + resource_kind 唯一；unknown / available / unavailable；网络 / 鉴权暂态失败只记录观测 |
| preparations | id、task_id、spec_digest、location_id、cache_state、generation、active_operation_id、eviction_operation_id、output_json、prepared_at、last_used_at、last_restore_error_json | spec_digest + location_id 唯一；absent / restoring / ready / stale；回收认领阻止新 pin / 发布，与准入分离 |
| preparation_waiters | operation_id、attempt_id（可空）、run_id（可空）、holder_operation_id（可空）、deadline_at、state | 等待者是运行（D-020）或管理员的首次准备 Operation；operation_id + 等待者唯一；取消仅解除自身等待；历史不影响活动引用计数 |
| preparation_pins | preparation_id、holder_kind、holder_id、expires_at | holder 为恢复 / 尝试；发布、使用、回收互斥；到期需先确认资源停止 |
| model_configs / model_revisions | id、name、revision、provider、model_id、params_json、credential_id | 运行引用具体修订 |
| harness_versions | id、name、version、content_digest、schema_json、enabled | 名称 + 版本唯一，摘要不可改 |
| attachment_versions | id、owner_id、name、version、content_digest、manifest_json、enabled | 上传者不能覆盖已发布内容 |
| experiment_plans | id、owner_id、name、revision、template_json、archived_at | 修改不回写运行 |
| submission_batches | id、owner_id、operation_id、idempotency_record_id | 成员关系由 runs.batch_id 固定 |
| runs | id、owner_id、pat_id、batch_id、plan_id、plan_revision、source_run_id、relation、state、stop_requested、client_request_id、accepted_at、deadline_at、stop_reason | relation 为 initial / rerun / modified |
| run_snapshots | run_id、schema_version、effective_json、provenance_json、snapshot_digest、config_digest、comparison_digest、policy_json | run_id 唯一；快照只插入不更新 |
| trials | id、run_id、task_id、repetition_index、state、reason_code、execution_terminal_at、result_revision、artifact_state、cleanup_state | run + task + repetition_index 唯一 |
| execution_attempts | id、trial_id、attempt_index、worker_id、service_epoch、lease_token、runner_id、protocol_version、process_identity_json、state、started_at、ended_at、error_json | trial + attempt_index 唯一；进程身份含 PID、启动标识与进程组 |
| work_items | id、trial_id、state、eligible_at、enqueue_seq、lease_token | trial_id 唯一；重试复用工作单元 |
| trial_results | trial_id、attempt_id、metrics_json、verifier_status、failure_cause、exception_type、reward_valid、grade_requested、retry_recommended、actual_model_json、usage_json、policy_version | 原始奖励可仅供诊断；统计需合法值且 reward_valid=true |
| artifacts | id、run_id、trial_id、attempt_id、kind、relative_path、storage_key、digest、size_bytes、status、expires_at | 不返回宿主机路径 |
| operations | id、kind、owner_id、resource_id、status、phase、progress_json、error_json、result_json、revision、service_epoch、lease_token、deadline_at、process_identity_json | 共享恢复由系统管理，owner_id 为空；持独立租约、进程身份与有限时限，等待者关联原主体 |
| idempotency_records | id、principal_id、action、key、request_hash、response_json、expires_at | principal + action + key 唯一 |
| audit_events | id、actor_user_id、pat_id、action、object_type、object_id、outcome、request_id、created_at | 不含令牌、密码、凭据明文 |

P1 增加 collections、collection_members、analysis_snapshots、analysis_snapshot_results、maintenance_jobs、backup_manifests。集合成员采用 collection_id + run_id 唯一约束；分析快照保存清单与结果版本，不跟随集合变化。

## 5. 状态与派生字段

运行的展示至少包含四个独立维度：

| 维度 | 字段 | 说明 |
| --- | --- | --- |
| 生命周期 | state | queued / preparing / running / finalizing / finished / cancelled / interrupted |
| 结果完整度 | result_completeness | none / partial / complete；按已评分试次数计算 |
| 产物保存 | artifact_state | pending / saving / complete / partial / failed / expired |
| 环境清理 | cleanup_state | pending / running / complete / failed / not_required |

建议保存试次层原始状态，运行级聚合按版本化规则计算并缓存。scored 要求合法奖励且 reward_valid=true，存在异常并不必然否定评分，例如 Agent 超时后验证所得奖励。运行 finished 仅表示计划已终结，不意味着全部试次获分；API 另返回 completed、scored、failed、not_started 等计数。不能把缓存中的旧计数作为受理或权限依据。

任务可提交性由准入、固定内容可得性、必要配置及当前策略派生；本机 cache_state 不作为准入条件。RunSnapshot 冻结准入 id / revision / 证明摘要、准备方式和实际 spec_digest；缓存命中、位置和恢复进度作为运行观测另存，回收不会改变 config_digest。内容检查证据与准备失败历史也不能反向改写快照。

## 6. 事务、索引与并发

必须原子的操作：

1. 受理：幂等检查、PAT 和用户有效性、任务准入修订与已知内容阻塞检查、额度扣减、运行 / 快照 / 试次 / 队列 / Operation 插入。
2. 领取 / 启动：检查工作仍可领取，写入唯一 lease_token 与尝试号；按阶段原子预留构建或容器容量，容器与进程启动在事务外。
3. 结果提交：校验 lease_token、尝试身份、结果摘要，写入最终结果并推进试次状态。
4. 取消：写入 stop_requested，阻止后续领取；已领取项通过 Worker 协议取消。
5. 恢复协调：按唯一缓存键原子认领 generation / 活动租约并添加等待者；发布时校验租约并交接 pin。取消等待者、无引用时终止恢复及回收认领必须重检相同记录，防止取消和新加入竞争。

建议索引：runs(owner_id, accepted_at, id)、runs(dataset_version_id, accepted_at, id)（可增冗余筛选列）、runs(owner_id, client_request_id)、trials(run_id, state)、work_items(state, eligible_at, enqueue_seq)、task_admissions(task_id, state)、preparations(cache_state, last_used_at)、preparation_waiters(operation_id, state)、artifacts(status, expires_at)、operations(owner_id, created_at, id)、audit_events(object_type, object_id, created_at)。准入与缓存的联合唯一键按上表建立唯一约束。

SQLite 开启外键、WAL 与有限 busy_timeout，使用 SQLAlchemy 2 仓储和 Alembic 迁移。异步访问采用独立于 Runner 的平台依赖；每个事务独立 session，不跨 asyncio 任务共享可变 session。哈希、网络请求、Docker 调用、压缩和文件复制都在事务外完成；涉及的只读解析在入事务后需重新校验引用修订。WAL 数据库备份使用一致性备份接口，禁止只复制主数据库文件。

## 7. 保留与迁移

产物过期保留 artifacts 的身份、摘要、大小和 expired 状态。方案或配置停用不删除快照与来源引用。操作记录、PAT 使用审计和配置摘要的保留期采用 [07](07-artifacts-export.md) 与 [09](09-identity-security.md) 的统一策略。

任务准入和首次成功证明独立于可回收缓存保留。备份 / 异机恢复复制这些业务事实，新位置的缓存状态单独重建；只有显式撤销修改准入，内容缺失或接口不兼容通过独立阻塞表达。

数据库迁移带 schema_version、应用兼容区间及迁移记录；启动前不匹配则进入维护状态。首期不导入旧平台数据。备份、回滚与异机恢复见 [12](12-operations.md)。

## 8. 模块验收

- 同一受理请求重试不增加运行、试次或 PAT 计数；批次失败时不留下部分数据。
- 修改模型、方案、附件展示名称后，历史快照内容摘要和来源关系保持稳定。
- 两个领取者竞争同一工作单元，只能一个取得有效租约；迟到结果不能覆盖已确认结果。
- 未评分为 null，有效零分为数值 0；数据库和导出均可区分。
- 回收不改变准入记录；并发恢复仅一个有效租约，等待者取消独立，旧租约不能发布；受理与准入撤销竞争时不误扣额度。

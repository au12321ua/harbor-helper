# 05 调度与执行生命周期

阶段：P0；公平调度 P1 · 来源：故事二执行、A5、B4、B10、C3

导航：[总览](00-overview.md) · 依赖：[提交](04-plans-submission.md)、[评分](06-results-scoring.md)、[产物](07-artifacts-export.md)

> 本阶段调整：调度单位暂为运行，一个运行执行一个 Harbor Job，试次与执行尝试仍持久记录。本文按试次领取的部分按 [14](14-decisions.md) D-020 解释。

## 1. 拓扑与职责

设计采用单服务进程内多个逻辑 Worker，asyncio 调度数据库队列；每个执行尝试由 Worker 启动独立 uv 环境中的 Harbor Runner 子进程。每个 Worker 有独立身份、location_id、容量、支持的执行器与环境版本、心跳和执行记录。systemd 管理服务进程；SQLite 是工作和状态的事实来源。

业务服务负责权限、计划、队列、额度和终态；调度器负责资源准入与领取；Worker 负责一次执行的生命周期；执行器负责测试与验证；环境接口负责容器、文件传输和清理。Worker 不直接访问数据库，也不依赖业务目录的绝对路径。

| 编号 | 要求 |
| --- | --- |
| EXE-01 | 持久队列、FIFO 优先、可恢复管理状态 |
| EXE-02 | 并发同时满足槽位、CPU、内存、运行和提供商限制 |
| EXE-03 | 进度与日志按准备、执行、验证、收集阶段上报 |
| EXE-04 | 取消、总时限、维护停止均保留已完成结果 |
| EXE-05 | 意外重启不自动恢复容器执行，明确标记中断并清理 |
| EXE-06 | 试次临时资源带实例 / 运行 / 试次 / 尝试标签；共享恢复资源带实例 / 恢复 Operation 标签 |

## 2. Worker 接口

以下为平台接口，不等同于 Harbor 方法。

| 方法 | 输入 | 约束 |
| --- | --- | --- |
| register | worker_id、location_id、capacity、capabilities | 首期仅内部注册，不暴露公网 |
| claim | worker_id、可用资源 | 服务端返回 WorkItem、快照、attempt_id、lease_token |
| heartbeat | attempt_id、lease_token、phase | 更新存活与取消指令；不隐式改变业务结果 |
| report_progress | lease_token、sequence、phase、counts | 序号单调，重复可去重 |
| append_log | lease_token、stream、offset、chunk | 有界批次，经脱敏后保存 |
| commit_result | lease_token、result_digest、结构化结果 | 有效租约且结果未确认；同摘要重复提交幂等 |
| complete_cleanup | lease_token、cleanup_report | 独立于评分与运行终态 |
| upload_artifact | attempt_id、存储句柄、内容流 | 通过存储接口校验归属和摘要 |

将来拆为独立进程或多机时只更换传输与身份验证；业务语义、内容标识和产物上传不变。首期不实现远程 Worker 服务。

Worker 到 Runner 另有版本化 JSON 协议，进度与结果由 Runner 转换，具体见 [15](15-stack-harbor.md)。一次 Runner 作业显式设置 n_attempts=1、n_concurrent_trials=1、retry.max_retries=0；重试仅由平台按锁定 Harbor 策略发起，避免 Harbor 和平台重复重试。

## 3. 调度算法

1. 按入队序号读取到 eligible_at 的工作单元。
2. 跳过所属运行已停止或到期的项，写明未开始原因。
3. 校验准入、已知内容阻塞和本机能力；已准入的冷缓存交给准备协调器按固定规格创建或加入恢复操作。
4. 检查每运行及可选成员 / PAT 活动试次限制；等待恢复不预占执行 CPU / 内存或提供商槽位，实际恢复构建只预留一份独立容量。
5. 在短事务中领取并生成 service_epoch 与租约。缓存就绪后，在另一个短事务原子预留全局试次槽位、容器 CPU / 内存与提供商许可，再创建试次容器、安装附件和执行；资源未满足则显示等待，不能超额启动。
6. 完成或确定终止后释放容量，排入下一个可执行项。

首期采用单一调度协调器串行分配；各阶段容量检查与预留在同一写事务确认，不能多个 Worker 按过期容量判断后超额领取。准备中的试次计入自身运行的活动并发，独立构建与执行容量按真实活动资源重建；评分后容器尚未停止时仍占资源。准备和执行共用主机 CPU / 内存总账，不能各自按整机容量分配。

按 FIFO 扫描首个可容纳项，允许小任务越过暂时放不下的大任务；这不是严格不越队的 FIFO。必须显示等待原因与排队时长，资源始终不可能满足的项在受理阶段拒绝。P1 可加入等待老化或成员公平调度。

模型提供商限额包括最大同时运行试次；RPM / TPM 若可得则由共享限流器协调实际请求，执行器无法逐次拦截时只承诺并发限制，不宣称精确保证提供商配额。真实限流错误按评分模块记录，不持续高速重试。

## 4. 运行与试次状态

~~~mermaid
stateDiagram-v2
    [*] --> queued
    queued --> preparing
    preparing --> running
    running --> finalizing
    queued --> finalizing: 取消或到期
    preparing --> finalizing: 失败或停止
    running --> finalizing: 停止或中断
    finalizing --> finished: 全部计划已终结
    finalizing --> cancelled: 主动停止
    finalizing --> interrupted: 服务中断
~~~

图表示单一路径的主阶段。并行运行时，部分试次可能仍在准备而其他试次已执行；详情返回各阶段计数，运行主阶段采用“已启动执行则 running；无执行但有准备则 preparing”的展示规则。

试次按 queued → preparing → executing → verifying → 终态演进。终态为 scored、execution_error、not_started、cancelled、interrupted；reason_code 补充具体错因。合法且 reward_valid=true 的评分被确认时进入 scored，Agent 超时或拒绝任务仍可能得到有效评分。后续收集由 artifact_state 表达，清理由 cleanup_state 表达；二者不阻止试次确认执行终态。失败也需进入有限收尾流程，上传已有日志并清理。

可自动重试的失败先终结 ExecutionAttempt，Trial 记录重试事件后回到 queued，直到重试成功或耗尽才写最终错误。不能先把 Trial 写成最终 execution_error，再让后续自动重试覆盖它。

Run.finished 表示所有试次已有终态，即使全部失败也可 finished；实际健康度使用 error_count、result_completeness 和 stop_reason。Operation 在自然完成且至少有有效结果时可 succeeded；全部试次均错误则 failed；用户取消则 cancelled；这些状态不应抹去已保存结果。

## 5. 一次执行的顺序

~~~mermaid
sequenceDiagram
    participant S as 调度服务
    participant W as Worker
    participant E as 执行器/环境
    participant A as 产物存储
    W->>S: claim
    S-->>W: 快照、attempt、租约
    W->>E: 验证缓存或加入共享恢复，等待固定内容
    W->>S: 缓存就绪，原子申请容器资源
    W->>E: 创建试次容器，复制 Harness 与附件
    W->>E: 本试次 setup / bootstrap 安装，切换网络
    W->>E: 执行任务、验证
    W->>S: 提交结构化评分或错误
    W->>A: 上传日志、会话和输出文件
    W->>E: 清理环境与临时目录
    W->>S: 产物与清理报告
~~~

评分可先于大文件上传确认；运行结果完整度与产物状态因此独立。上传失败可在保留的暂存内容仍可用时重试，不重新调用模型。

共享恢复按 (spec_digest, location_id) 合并，持有独立 Operation、generation、租约与资源预留；每个试次作为等待者关联自己的 attempt。完成后验证摘要、原子发布并交接使用 pin。一个等待者取消只解除自身引用，无等待者才允许终止共享工作；不能按首个运行的标签清理共享构建。恢复失败向等待者报告同一根因，统一使用 [06](06-results-scoring.md) 的预算和退避，不叠加 Runner 或恢复服务内层重试，细则见 [02](02-datasets-preparation.md)。

附件 P0 在每个试次容器内独立安装，不挂载宿主目录、不写回共享缓存；失败影响该试次。安装超时、等待超时与运行总时限分别记录；安装的外网权限在 Agent 执行前切换到批准范围。

## 6. 租约与重复执行防护

每次领取产生 attempt_id 和不可复用 lease_token，携带 service_epoch。首期建议心跳 10 秒、30 秒未响应标记 suspect；这些是 D-011 初值。心跳过期不能立即证明旧环境已经停止。

处于 suspect 的尝试先查本机 Worker 与容器标签，执行终止和清理；确认旧执行已停止后，才能按重试规则创建新尝试。无法确认停止则隔离相关资源并阻塞重试，避免同一试次同时调用模型。

旧租约的迟到结果返回 STALE_EXECUTION_LEASE。结果提交必须同时校验试次状态、当前 attempt 和取消标志；不依靠客户端时间判断先后。最终结果同摘要重传可确认成功，不同摘要返回 RESULT_CONFLICT。

## 7. 取消与超时

取消先停止领取，再向 Worker 发出指令。等待共享缓存的试次先解除自身等待，不杀死其他等待者仍需的恢复进程。独立试次 Runner 在 Linux 进程组启动，先协作取消、SIGTERM，建议 30 秒后仍未结束则 SIGKILL；再按实例与尝试标签清理容器、网络和 sidecar。无等待者的恢复由其独立租约与 Operation 标签取消。结束进程组不能代替 Docker 清理；清理另给 120 秒初始宽限，实际值公开并记录。

超时需区分准备超时、Agent 执行超时、验证超时与总运行到期。Harbor 基线中 AgentTimeoutError 属于 agent_exhausted_budget，继续验证且奖励有效，不自动重试；仍须有合法验证输出才能评分。用户取消或总时限到期后不再开始新的验证工作，已接受的评分保留。例外与版本证据按 [06](06-results-scoring.md) 记录。

无法清理时设置 cleanup_state=failed，登记待处理事项，运行生命周期仍可结束。暂存产物可用时继续收集，收集失败不将已有评分改成错误。

## 8. 意外重启与对账

启动先进入 recovering，关闭新受理和派发：

1. 加载数据库并校验 schema，生成新 service_epoch。
2. 查询旧 epoch 中仍在 preparing / executing / verifying / collecting 的尝试。
3. 已确认评分保留；未有最终结果的在途试次标记 interrupted，原因 SERVICE_RESTARTED。
4. 被影响运行的未领取试次标记 not_started / RUN_INTERRUPTED；该运行整体中断，不自动补跑。
5. 完全未开始、所有试次仍 queued 的运行可继续留队；已经全部确认结果、只剩上传或清理的运行完成收尾，不改为未评分。
6. 校验持久化的 Runner 进程启动标识并终止遗留进程组，再按实例标签停止孤儿容器、网络和 sidecar，清理或隔离对应目录；不按可复用 PID 盲目杀进程，不删除其他实例或人工容器。
7. 对已确认但文件状态未确认的产物校验摘要、补齐索引或标记 unavailable。
8. 对旧共享恢复 Operation、等待者和 pin 对账，终止旧构建进程并清理未发布成果；已发布缓存验证后保留，未完成缓存标记 absent / stale，准入不变。关联在途试次按上述规则中断，不自动续跑。
9. 重建内存容量与操作进度，发布恢复报告后进入 ready。

重启不会自动新建运行或消耗 PAT 额度。用户可对未完成任务创建新重跑。

## 9. 维护模式与验收

P0 的手动停止 / 重启会中断在途工作，必须如实记录。P1 维护模式先禁止新受理和派发，再选择等待已领取项完成或立即取消；排队项保留到维护结束，除非已到总运行时限。

关键验收：同时竞争只领取一次；满载仍不超资源；取消与评分并发保持单一终态；杀死进程后不继续原运行执行；孤儿资源按实例标签清理；上传失败和清理失败均不丢已确认评分。

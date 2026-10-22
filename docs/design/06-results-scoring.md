# 06 结果状态与评分统计

阶段：P0 · 来源：故事二结果、A3、B8、C3

导航：[总览](00-overview.md) · 依赖：[领域](01-domain-model.md)、[配置](03-configuration-attachments.md)、[比较](08-collections-comparison.md)

## 1. 基本原则

原始奖励、奖励有效性和平台评分状态分别记录。验证器实际产出的奖励可保存为 raw_score；没有输出时为 null。只有值合法且平台策略判定 reward_valid=true 时，才能成为计入统计的 scored 结果。reward_valid=false 时即便产物中存在数值，也只作为诊断证据，不能计入均值或通过率。

有效零分为真实输出的 0，不能从“发生了异常”或“reward_valid=true 但无输出”推导出来。Harbor 的 Agent 超时、上下文 / 输出预算耗尽和拒绝任务仍可产生有效奖励；模型提供商错误则可能继续验证，但奖励仍无效。

基线按平台错误策略过滤无效奖励并报告覆盖率。若团队另设“某错误计未通过”的口径，必须标为显式平台扩展、保存独立策略版本，不宣称与默认汇总相同，也不能伪造原始零分。

| 编号 | 要求 |
| --- | --- |
| RES-01 | 原始值、状态、错因、验证器与计分口径可以追溯 |
| RES-02 | 有效零分、无评分、未执行与已清理证据明确区分 |
| RES-03 | 基础设施错误和模型 / 任务相关错误分别处理 |
| RES-04 | 自动重试与计划重复试次分别计数 |
| RES-05 | 汇总显示计划数、已评分数、排除数、未完成数和样本量 |
| RES-06 | 首期提供均值、标准差、通过率；pass@k 等暂不提供 |

## 2. 评分契约

每个数据集版本需有经管理员确认的评分契约，保存进运行快照：

- metric_id、名称、单位、方向、值域与聚合方式。
- 验证器版本及内容摘要，分数提取规则，何为合法输出。
- passed 的显式来源或阈值；不能默认“分数大于 0 就通过”。
- 平台错误策略版本，执行器适配器的版本与映射摘要（含锁定的 Harbor 版本）。
- grade 是否要求继续验证、验证的独立时限，以及用户取消 / 总时限的停止规则。
- 有效奖励过滤规则；可选 aggregation_action=count_as_failure 为非默认扩展，须单列策略。
- 平台自动重试次数。
- 多试次到任务级、任务到 bench 级的聚合规则及版本。

作者没有提供完整契约时，平台给出建议模板，由管理员确认后才能受理正式评测。成员 / PAT 不通过任意临时字段覆盖作者基准；选择已发布且明确声明 verifier / scoring 影响的附件时，由解析器生成独立评分契约并展示差异，通过新提交或修改后运行固定，不能覆写已有运行或基准契约。

## 3. 结果状态与错误决策表

错误策略由平台自定并带版本（[14](14-decisions.md) U-15），不依附某个执行器。下表的初值参考 [Harbor Error classification](https://docs.harborframework.com/jobs/error-classification.md)。执行器适配器负责把执行器的原生结果映射成下表的 cause 与奖励有效性：Harbor 适配器按锁定版本的异常类型和结果文件映射，Harbor 自身是否带有错误策略模块不影响平台口径。适配器无法识别的异常记为 unclassified；平台要求继续验证、执行器却跳过时，记录实际是否验证，不伪造评分。

| cause / 场景 | reward_valid | retry 建议 | grade | 平台处理 |
| --- | --- | --- | --- | --- |
| 无错误且奖励合法 | true | 无需 | 正常验证 | scored，含有效 0 |
| agent_exhausted_budget：超时、上下文或输出预算耗尽 | true | false | true | 保留合法验证奖励，标记预算事件 |
| agent_refused_task：安全拒绝、内容策略拒绝 | true | false | true | 保留合法验证奖励，不能一概排除 |
| sandbox_failed：构建、启动、OOM、环境访问失败 | false | true | false | 重试允许范围内重新执行，最终无效则排除 |
| model_provider_failed：限流、连接或服务故障等暂态类型 | false | true | true | 可继续验证留证，奖励不计统计；平台控制重试 |
| model_provider_failed：请求参数等永久错误 | false | false | true | 不重试，保留诊断 |
| model_provider_failed：认证、权限、模型不存在 | false | false | false | 阻塞并给凭据或模型修复入口 |
| harbor_failed：框架 / 依赖能力不支持 | false | false | false | 排除并要求修复 Runner |
| verifier_failed：超时、奖励文件缺失 / 为空 / 解析失败 | false | false | true | 无有效评分，不自动重新执行 Agent |
| unclassified：适配器未识别的异常 | false | true | true | 按本表处理，记录原异常和未分类告警，补充映射后升级策略版本 |
| cancelled | false | false | false | 取消，不新增验证或重试 |

grade 表示策略允许或要求验证路径，不是“遇到验证器失败后无限重试验证”的命令。reward_valid=true 仍需有合法实际奖励；缺失 / 解析失败按验证器错误处理，不能自动补 0。无效奖励可以非空，所以状态不能仅靠 raw_score 是否为 null 判断。

平台额外记录未开始 USER_CANCELLED / RUN_DEADLINE_EXCEEDED、服务重启 SERVICE_RESTARTED、Runner 协议失败 RUNNER_PROTOCOL_ERROR 等管理原因，不伪造为执行器原生异常。平台取消、运行到期和服务中断优先阻止新增工作。

错误记录至少包含 stage、code、exception_type、failure_cause、reward_valid、retry_recommended、grade_requested、policy_version、attempt_id、message、suggested_action。最终 trial.state 根据奖励有效性和管理状态确定，异常原文另保留。message 可变化，Agent 依据稳定字段处理。

### 平台准备错误

以下为平台错误码，不冒充执行器原生异常；统一保存 platform_policy_version。它们在 Agent 执行前失败，不运行验证，raw_score=null、reward_valid=false，耗尽重试后计入 excluded_error_trials。

| code / 场景 | 重试与后续动作 | 对准入和其他试次的影响 |
| --- | --- | --- |
| PREPARATION_RESTORE_FAILED：临时下载、拉取或构建失败 | 仅确认可重试的根因按统一预算退避；配置错误 / 鉴权失败需修复后重跑 | 准入保持；共享恢复的当前等待者各自记录同一根因 |
| RESOURCE_CONTENT_UNAVAILABLE：必需原内容确实不可得 | 不盲目重试；包含 expected_digest / evidence，后续新提交和原配置重跑均阻塞 | 不撤销准入，单独更新相应内容可得性 |
| RESOURCE_CONTENT_MISMATCH：恢复得到不同摘要 | 拒绝替换；若无满足原标识的副本则归入内容不可得阻塞 | 不发布错误缓存，不改快照 |
| ATTACHMENT_SETUP_FAILED / ATTACHMENT_SETUP_TIMEOUT | 确认可重试的安装基础设施错误受同一预算限制；脚本逻辑错误不自动重试 | 仅该试次，保留安装日志；不改变其他试次或数据集准入 |

未准入、撤销或已知内容不可得在受理前被发现时只返回 blocker，不创建未评分试次、不消耗额度。受理后发现则记录上述执行错误；取消、总时限和服务重启继续用既有管理原因。一次网络超时不能据此标记内容不可得。

## 4. 自动重试规则

设计建议：对锁定 Harbor 策略中 retry=true 的失败最多再试 2 次，即总执行尝试最多 3 次；退避建议 5 秒、20 秒并加抖动，始终受总运行时限、取消和资源状态约束。Harbor 作业设置 retry.max_retries=0，由平台统一重试，避免两层相乘。具体配置见 D-011。

同一 Trial 下 attempt_index 从 1 递增。一次最终获分只形成一个计划样本，历史失败尝试仍保留并统计 retry_count。不能从多次模型执行里挑最高分作为原试次成绩。

本轮替换 v0.1 中“默认仅模型调用前自动重试”的建议，沿用 Harbor 对 model_provider_failed 等错误的 retry 基线。提供商故障重试可能重复实际模型请求并增加费用，所有尝试均记录 usage 与不确定性；它不提供金额预算或提供商调用恰好一次保证。

自动重试前必须确认旧进程组、容器和网络资源已经停止；未取回结果的 Runner 断线先核对结果文件，不因父进程没读到输出就立即重跑。没有 Harbor 最终分类且无法确认旧执行停止时标记中断并交由人工处理。平台覆盖 Harbor retry 的原因必须记录 policy_override，不能静默改策略。

产物上传和清理重试是收尾重试，与模型执行尝试和试次评分无关。

缓存恢复没有独立的内层重试预算；一次共享恢复失败终结各等待者的当前 ExecutionAttempt，仍有预算的试次退避后重新排队，同键请求重新合并。不得按等待者数同时启动恢复，也不能因加入共享操作而重置计数。附件重试从干净容器开始，P0 不复用其他试次的安装层。

## 5. 单运行汇总口径

建议 P0 固定每任务计划试次数 r；显式任务数 T，计划试次数 N=T×r。所有汇总返回以下计数：

| 字段 | 含义 |
| --- | --- |
| planned_trials | 本运行计划试次数 N |
| scored_trials | 有合法奖励且 reward_valid=true 的 S |
| count_as_failure_trials | 非默认扩展策略中按未通过计入的 F；Harbor 基线为 0 |
| excluded_error_trials | 不计分母的错误 E |
| unfinished_trials | 未开始、取消、中断等 U |
| passed_trials | 验证器判通过的 P |
| scored_coverage | S / N |
| evaluation_coverage | (S + F) / N |
| bench_task_coverage | 本运行任务数 / bench 全量任务数 |

终态时应满足 N = S + F + E + U。运行中另返回 active_trials、queued_trials，避免把尚在执行的项提前当终态错误。

基础统计：

- 原始分数均值只对合法且 reward_valid=true 的奖励计算，明确 metric_id、样本量 S；无样本时为 null。
- 样本标准差使用 n−1，n 小于 2 时为 null，不能返回 0 暗示稳定。
- 通过率为 P / (S+F)，分母为 0 时返回 null。只对定义了 passed 的指标提供。
- 单任务先对该任务的已评分重复试次取均值；bench 主分数建议对可汇总任务均值取宏平均，并显示参与任务数。
- 部分重复试次缺失时，任务均值带 partial 标记。主界面必须同时展示覆盖率，不能把不同覆盖范围的均值当完整 bench 排名。

若作者基准采用其他方式（例如微平均、加权平均、最低值），以快照中的明确规则为准，保留 metric_definition 与 aggregation_version。禁止跨不同指标单位直接求平均。

## 6. 计算例子

某运行含 5 个任务，每任务 1 次：3 个正常有效奖励为 1、0、1；1 个 Agent 超时但验证得到有效奖励 0；1 个环境失败。按 Harbor 基线汇总：

~~~text
N=5，S=4，F=0，E=1，U=0，P=2
有效奖励均值 = (1+0+1+0)/4 = 0.5
通过率 = 2/4 = 0.5
已评分覆盖率 = 4/5 = 80%
评测覆盖率 = 4/5 = 80%
~~~

超时项 raw_score=0、reward_valid=true，属于正常计分样本；环境失败没有奖励时 raw_score=null。反例：模型提供商错误后验证产物中出现 1，但 reward_valid=false，该 1 只供诊断，仍不计入 S 或 P。导出与网页使用同一计算服务，必须得到相同计数。

## 7. 结果完整度和版本

result_completeness=complete 仅在所有计划试次都有合法且 reward_valid=true 的评分时成立；有一部分有效获分为 partial，无有效评分为 none。该字段不等于 evaluation_coverage。

P0 最终评分确认后不提供手动改分。适配器解析错误修复后若需重算，必须形成新的解析 / 结果修订并保留旧版本，不能静默覆盖分析快照。若尚未实现版本化重算，则通过新运行或离线导出处理。

cost 和 tokens 保存 source、value、availability、observed_at。部分提供商无用量时，聚合显示 known_total + unknown_count，不把已知部分标成总费用。

## 8. 验收

- 表中每个错因都可通过假执行器构造，并验证 raw_score、分母和 retryable。
- 0 分正常计入；5 个计划只有 1 个获分时，均值旁必须显示 20% 已评分覆盖率。
- 三次基础设施尝试最终成功，计划试次数仍为 1，retry_count=2。
- Agent 超时和拒绝任务仍运行验证，合法奖励计分；提供商错误即使有奖励数值也不计分。
- Runner 与平台不会双重重试，错误映射来自锁定策略而非动态读取上游 main。
- 所有样本均被排除时，均值和通过率为 null，统计字段不出现除零错误。
- 单样本标准差为 null；不同 repetitions、指标或口径比较时明确提示差异。

参考：[Error classification](https://docs.harborframework.com/jobs/error-classification.md)、[Job configs](https://docs.harborframework.com/jobs/configs.md)。文档核查于 2026-10-22；发布版本须记录实际 Harbor 策略与结果样例。

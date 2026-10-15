---
name: harbor-helper-research
description: Operate a Harbor Helper team service as an authorized research client; discover inputs, submit attachment controls, recover requests and read safe results. Use for HTTP or remote CLI experiments, not skills/sdk inside experiment attachments.
---

# Harbor Helper 研究操作

你是代成员调用团队服务的研究客户端；被评测 agent 在任务容器里。此 skill 及访问凭证不作为实验附件。服务负责身份、权限、队列与报告门槛。

先读 [操作参考](references/operations.md)，按用户目标选择现有薄 CLI 或 HTTP。需要完整字段时读取目标服务 `/api/v1/machine/schema`，不凭旧示例猜接口。CLI 必须已安装支持机器 API v1 的 harbor-helper；复制整个 skill 目录后参考文件仍可用，不依赖仓库相对路径。

## 授权与发现

- 沿用当前用户已授权的操作和预算，不重复确认已授权步骤。缺少实验范围或真实模型预算时只推进发现/读取，澄清后再提交；本 skill 不扩大授权、不自动追加付费尝试。
- 网页签发 PAT；通过当前用户独占、0600、非 symlink 文件或安全 stdin 配置明确 profile。原值不进入 argv/history、环境变量、附件、task、日志或报告。不打印 profile 文件，不使用调试 HTTP header 日志；模型方案的团队 key 与 PAT 分开。
- 每次使用明确 `--remote-profile`，确认 `/me` 的成员 ID、服务 URL 和能力。失效/撤销/到期返回 reauthorize 时停止对应操作；scope 不足也停止，不能切换管理员会话绕过。不把本地 logout 当服务端撤销。
- 读取 schema/discovery，核 `contract_version`、`allowed_operations`、数据集验证状态、模型方案、附件具体版本和限制；按 `next_offset` 续读任务切片。未知版本/缺少需要的操作时停止相关调用，报告差异。发现可用不保证 Hub/Docker/模型可执行；容量/时长/token 观测不是金额预算保证，费用 unknown 保持 unknown。

## 固定对照并提交

保存一个研究计划：数据集固定引用/已配置 ID 与版本、任务选择及评分来源、agent/模型方案、作者参数、attempts/concurrency/wall_seconds、环境构建倍率、明确附件身份/摘要、授权与预算范围。省略参数的服务默认也可能变动：核发现/schema，并在受理后检查冻结输入/比较条件；需要 CLI 未暴露字段时用 HTTP，不臆造 CLI flags。

无附件、v1、v2 都用**新 submit**，分别明确新键；仅附件版本为计划中的变量。无附件省略 `attachment_version_id`；候选只指定明确 `attachment_version_id`，不用 latest、不自动沿用。普通 rerun/retry/recover 继承附件，不用于换版本。已有附件可直接选择；上传/发布只在用户授权且有 attachments 能力时做。

**发写请求前**持久保存服务 URL、成员 ID、固定操作类别、目标路径、原键和完整原正文（或附件内容摘要及发布元信息）。不含 PAT。每个操作单独保全，不让后一个请求覆盖前一个记录。CLI 自动 receipt 在发请求前保存 path/body/user_id/key，但一个 profile 只保留最后一次；参考文件说明如何在下一次写前保全它。不要无键依赖 CLI 自动生成随机键。

## 通信恢复与停止

- 超时或响应丢失：先以原成员+操作+键 lookup，或原路径/正文/键重发。查不到不等于未受理，保持原键，不造新键；尚未解决的写操作先恢复，再开始下一次写。
- CLI `service retry` 是**最近 receipt 的通信重发**；普通 `retry RUN` 是新研究尝试，两者不可混用。凭证更换仍须同一成员、同一服务，原记录/键不因撤销而消失。
- 409 幂等冲突/action=fix_input：保留原记录，核正文/目标差异并修正误输后找回原操作；不通过换键继续制造任务。确实要改变实验是另一个需授权的新操作。
- 新受理前读取 discovery.readiness（或授权 GET /readiness）：区分 initialized、accepting、scheduler 活动和观察时间、maintenance 原因及可选建议重试时间、pending 身份额度。旧服务缺字段时以实时 schema 为准；额度共用成员的全部凭证，不切换身份绕过。维护暂停/活动未知时只推进读、取消或原键找回；建议重试时间不触发自动恢复，就绪不保证执行成功。
- 429/503 或 retry_same_request：在本轮约定等待期限/最大请求次数内有限退避，继续用原键；wait_known=false 不承诺多久可用。到期限返回记录、已知状态和下一步，不自动提交补偿任务。

## 查询与结果

按受理 ID query，拿到 run_id 后可 query run。分别呈现 resource/audit/report 的 state 与 reason，不把执行结束当报告可读。按 poll_after_seconds 建议轮询；用户未指定时可采用本次观察最多 60 秒/30 次的可调整上限（不是服务/实验限制）。上限到达交还受理 ID、run ID、原键、三轴与下一动作，不把超时解释成失败。

- pending：继续查询原记录，直到本次观察期限。
- resource=cleanup_blocked 或 report=blocked：说明资源/审计原因，contact_admin；不读取原始日志/产物绕过门槛，也不自动重复提交。
- report=unavailable：给明确 reason，停止等报告；explicit_new_attempt 是建议，需在现有授权和预算内主动决定，不能自动补跑。
- report=available：读取安全机器报告，按 attempts.valid/rewards/failure 解读。有效 reward=0.0 是零分；missing_score 是缺评分，execution_failure 是执行失败，unknown 是证据不足，均不能补成 0。报告自身 status/complete 与有效/缺失 attempt 数也保留。

比较展示 comparable/reasons、`bundle_change`、`attachment_inputs` 的冻结版本身份以及有效评分 delta；附件差异是研究变量，不能仅凭它宣布不可比。其他条件变化仍呈现原因。fixture/Oracle/脚本化成功仅证明相应契约/流程，不能声称真实 LLM 能力提升；真实模型结果也须标明样本与条件，不扩展成通用结论。

交付用户：服务/契约版本、输入与版本身份、受理/run ID、三轴、报告有效性及比较、下一动作、预算/证据的实际覆盖。不包含访问值或内部诊断。

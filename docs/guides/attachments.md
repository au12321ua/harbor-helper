# 团队附件版本（HTTP v1 / 远程 CLI）

附件与任务、评分器分别维护。成员可固定任务、基础 agent/model、作者参数、尝试次数和资源/时长等条件，主动新建无附件基线与明确 v1/v2 候选；普通重跑保留父输入，不切换附件。附件差异仍可比较，其他条件沿现有可比性门槛。fixture 中的分数差不证明模型效果或通用能力提高。

浏览器“团队附件”提供创建、版本发布、派生、名称/说明维护及附件/版本停用恢复。新建实验默认无附件；从目录或失败草稿带入版本时会显示明确 ID，可用“清除附件，使用无附件基线”清除。实验详情与比较仅展示冻结引用和原摘要；没有版本引用即为无附件。附件只能以版本形式进入实验，提交表单不提供直接上传 ZIP。

## 认证、类型与权限

沿用受邀成员的登录会话：浏览器同源 cookie，HTTP/CLI 可使用 `Authorization: Bearer <会话值>`。写操作须 `X-Requested-With: harbor-helper`；服务拒绝跨源写入。访问值不应出现在命令行、附件或日志中。自动化凭证签发、scope、客户端 skill/SDK/MCP 不属于本交付。

类型定义在 `service/attachment_contracts.py`，HTTP 不接受未知 metadata 字段或将字符串当作 boolean。ZIP 校验、权限、事务、队列受理都由应用统一执行；Web 与远程 CLI 没有独立业务规则。现有全局 OpenAPI 入口保持关闭，本页描述新增附件 HTTP v1 契约，不声明后续机器发现/schema 已完成。

| 操作 | 方法与路径（相对 `/api/v1`） | 当前会话权限 | 请求 |
| --- | --- | --- | --- |
| 目录 | `GET /attachments` | 任意启用成员/管理员 | 无 |
| 新建与 v1 | `POST /attachments` | 任意启用成员/管理员 | multipart `file` + `metadata={name,description?}` |
| 后续发布 | `POST /attachments/{attachment_id}/versions` | 创建者或管理员 | multipart `file` + `metadata={notes?}` |
| 派生与 v1 | `POST /attachment-versions/{version_id}/derive` | 任意启用成员/管理员，来源须可用 | multipart `file` + `metadata={name,description?}`；上传自己的内容 |
| 查回写入 | `GET /attachment-operations/{operation}/{key}` | 原成员，发布另校验维护权 | 固定操作类别与原键；键需 URL 编码 |
| 名称/说明/启用状态 | `PATCH /attachments/{attachment_id}` | 创建者或管理员 | JSON 中至少一个 `name/description/enabled` |
| 版本停用/恢复 | `PATCH /attachments/{attachment_id}/versions/{version_id}` | 创建者或管理员 | JSON `{enabled: boolean}` |

名称1–128字符，说明/发布说明最多4096字符，可重名；调用选择 ID。创建者账户被停用不会隐式停用附件，团队仍可复用，管理员仍可维护。版本字节、序号、摘要、发布者/时间及来源不可变；版本只允许变更启用状态。没有下载、覆盖或物理删除版本库接口。

目录返回 `{attachments}`。每个附件含 `id,name,description,creator_id,creator,created,enabled,versions`；versions 按序号倒序排列，含 `id,attachment_id,number,bundle_id,digest,publisher_id,publisher,created,notes,source_version_id,enabled,availability`。时间为 Unix 秒，`availability` 为 `available/unavailable`，与启用状态分别表示。当前目录沿已有全量发现方式返回，不宣称分页机器发现已交付。

所有附件写入返回 `{attachment,version}`，创建/发布/派生 HTTP201。三种写操作须1–128字符 `Idempotency-Key`，按成员+固定操作类别+键查找：`attachment_create`、`attachment_publish`、`attachment_derive`。目标和来源属于请求摘要，不属于操作类别。摘要包括规范语义字段、默认空说明及实际解包树摘要（含文件名、内容及可执行位）；不同 ZIP 压缩字节不影响相同内容的查回。同键不同输入/目标 HTTP409 `idempotency_conflict`。校验失败不登记键；相同内容的不同键仍发布独立版本。

通信失败保存原输入与原键重试，或按键查询；未知键404只表示尚未观察到已提交操作。键不能跨成员查回。停用后仍可查回已成写入；损坏/缺失字节返回 `availability=unavailable`，不能生成替代内容。

## 明确引用

`POST /submissions` 用 `attachment_version_id` 引用附件；省略或传 null 是无附件基线，不接受 `bundle_id`。成员共享任意可用版本，受理冻结版本 ID、附件 ID、bundle ID 与摘要到 service binding；现有受理响应另有 `attachment` 引用字段。停用附件或版本409 `attachment_disabled`。

沿现有 `/runs/{id}/rerun`、`/runs/{id}/retry`、`/submissions/{id}/retry` 使用新键主动受理，保留谱系和父快照，受理身份始终取当前成员。已受理任务不受后来停用影响。准备和执行前照常验证固定摘要，失配停止，不改用最新版。

当前请求附件字节/路径与当前实际访问值相同会拒绝；所有上传、发布、派生、历史使用/复制还拒绝 `hh_pat_v1_` 加43个 base64url 字符的可识别明文，包括二进制与跨读取块。后台只作格式扫描，不接收请求 token，不将其写入 worker/env。原路径、文件秘密限制和资源释放/证据审计门槛保留；此项不检测任意编码、加密或分片秘密。

比较保留 `bundle_change`，新增 `attachment_inputs.left/right={kind,attachment_version_id,bundle_id,digest}`。kind 为 none/versioned。版本只取冻结字段，不查当前版本库。评分缺失、失败、任务/模型或其他条件变化仍不可比，不把附件变化当作拒绝理由。

## 远程 CLI

先按现有 `service login` 选择远程 profile；无登录不会落回本地队列。以下 ID/键仅为示例，文件不得含任何真实凭据：

```bash
harbor-helper --remote-profile team --json attachments list
harbor-helper --remote-profile team --json attachments create --file input.zip --name SDK --idempotency-key create-sdk-v1
harbor-helper --remote-profile team --json attachments lookup attachment_create create-sdk-v1
harbor-helper --remote-profile team --json attachments publish att-ID --file updated.zip --notes '修订说明' --idempotency-key publish-sdk-v2
harbor-helper --remote-profile team --json attachments derive av-ID --file fork.zip --name Fork --idempotency-key derive-fork-v1
harbor-helper --remote-profile team --json attachments update att-ID --version-id av-ID --enabled false
harbor-helper --remote-profile team --json submit --agent oracle --idempotency-key baseline
harbor-helper --remote-profile team --json submit --agent oracle --attachment-version-id av-ID --idempotency-key candidate
```

附件写操作要求显式原键；超时后使用 lookup 或原参数重发。`service retry` 保持已有实验受理回执恢复语义，不负责自动重发附件文件。`submit` 只接受 `--attachment-version-id`，不直接上传附件文件。HTTP 与 CLI 不自动换键、批量提交或执行付费模型。Oracle/fixture 只验证流程，不是实际研究 agent/模型效果。

## 迁移与回退边界

启动 `ServiceData` 时在既有 queue.sqlite 附加 `attachments`、`attachment_versions`、`attachment_operations` 三表，不重新 init、不改主密钥，不重写旧 manifest/评分。`attachment_versions.legacy` 列为已废弃的登记标记，新写入恒为0。迁移报错则初始化失败，不能继续以该实例写入。正式升级前须按现场保护说明核所有写者、停服务、保全一致SQLite备份及外 master；本次开发没有操作正式 state。

发布先校验并 fsync 私有 bundle 字节/目录，再用单一 SQLite 事务公开 bundle 行、身份、版本及幂等键；control锁串行化序号和停用/受理。进程退出可能遗留无引用字节，但目录/任务选择只读已提交行，不会出现可选半成品或空身份。本版不自动回收此类孤立字节，不清理历史或已有引用对象。

旧代码能忽略附加表，但不能保障新版本停用/谱系语义，不能将“表可读”视为安全业务回退。已有版本数据的state应优先向前修复；如确需回退，先停止全部写者、保全最新业务数据并单独评审兼容策略。不得删除新表或回放旧WAL，不得用过期备份覆盖新业务；代码回退不代表 state 回退。日志/产物保留不删除附件版本库。

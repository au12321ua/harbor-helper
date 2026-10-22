# 03 配置解析与附件

阶段：P0 · 来源：原稿故事二配置、A2、A6、A9、B2、补充 3、边界 2

导航：[总览](00-overview.md) · 依赖：[数据集](02-datasets-preparation.md)、[权限](09-identity-security.md)

## 1. 模块职责

解析器将作者预设、团队默认、方案和单次覆盖转换为一份可验证、可解释、可哈希的执行配置。目录配置供人选择，运行快照记录实际使用内容；两者分开存储。

| 编号 | 要求 |
| --- | --- |
| CFG-01 | 网页和 SDK 调用同一解析服务，取得最终值、来源、差异和阻塞项 |
| CFG-02 | 每个运行固定数据集、任务、模型请求配置、Harness、附件和资源 |
| CFG-03 | 内容版本不可覆盖，凭据只保存引用 |
| CFG-04 | 附件明确组成、作用范围、加载顺序和实际加载证据 |
| CFG-05 | 模型、Harness、附件变更不改写已有运行 |
| CFG-06 | 重跑使用原快照，不能重新套用最新团队默认值 |

## 2. 配置对象

| 对象 | 必要字段 | 管理规则 |
| --- | --- | --- |
| ModelConfigRevision | provider、transport、endpoint、model_id、request_params、credential_ref、capabilities | 管理员创建修订；敏感 URL 参数不得明文导出 |
| HarnessVersion | name、version、content_digest、parameter_schema、supported_transports、entrypoint、environment_requirements | 管理员发布，版本内容固定 |
| AttachmentVersion | name、version、content_digest、manifest、files_manifest、owner_id | 成员可上传；发布后内容固定 |
| TeamPolicyRevision | defaults、hard_limits、provider_limits、retention_policy | 管理员变更，保留版本 |
| ExperimentPlan | 配置引用、任务选择、覆盖值、revision | 创建者编辑，运行固定具体修订与展开值 |

提供商配置中的 endpoint 必须属于管理员批准的服务端目录；PAT 不能用临时 endpoint 绕过执行网络边界。模型标识记录“请求值”，接口返回实际版本时再记录 observed_model；无法固定远端模型权重，结果页必须说明这种复现限制。

## 3. 合并与约束

设计建议的覆盖顺序：

~~~text
作者预设 → 团队默认 → 实验方案 → 单次覆盖
                           ↓
作者硬性要求 + 团队强制上限 + 类型与兼容性检查
                           ↓
生效配置 + 字段来源 + 基准差异 + 阻塞项
~~~

具体规则：

1. 未提供字段继承前层；显式 null 仅允许出现在 schema 声明 nullable 的字段，不能表示“清除必填”。
2. 对象按字段合并；数组整体替换，附件列表保留显式顺序；不做隐式数组拼接。
3. 时间、CPU、内存先转成标准单位再比较。必填字段、枚举和数值边界统一由参数 schema 校验。
4. 作者资源建议可被缩短超时或减少内存，标记 deviates_from_author_baseline=true；作者明确硬性要求和团队硬上限不得违反。
5. 作者要求强度不明时不擅自降级，返回待管理员确认的 blocker。
6. 团队默认改变只影响以后解析的新提交；已受理快照不变。
7. 团队上限收紧不改写已受理快照。出于安全或主机容量无法执行时可阻塞或取消并给出原因，不能暗中降低内存、并发或时间。

示例：作者建议超时 600 秒，团队默认 900 秒，方案 1200 秒，单次覆盖 1800 秒，团队上限 1500 秒。解析结果返回超限错误，不把 1800 静默截断成 1500。若单次为 300 秒，则生效 300，来源 single_override，并显示偏离作者基准。

## 4. 解析接口输出

~~~json
{
  "resolution_id": "res_01",
  "expires_at": "2026-10-22T02:10:00Z",
  "effective_config": {
    "dataset_version_id": "dsv_01",
    "task_ids": ["task_01"],
    "repetitions": 2,
    "trial_timeout_seconds": 600,
    "max_concurrency": 2
  },
  "field_sources": {
    "/trial_timeout_seconds": {
      "layer": "author",
      "source_id": "dsv_01",
      "revision": 1
    }
  },
  "baseline_differences": [],
  "required_preparation": [
    {"task_id": "task_01", "action": "restore_cache", "spec_digest": "sha256:..."}
  ],
  "cache_observations": [
    {"task_id": "task_01", "location_id": "local-host", "cache_state": "absent"}
  ],
  "warnings": [],
  "blockers": [],
  "config_digest": "sha256:...",
  "reference_revisions": {"team_policy": 3}
}
~~~

建议解析记录有效 10 分钟，用于提交前确认，不能预留资源或额度。受理时重新检查版本、准入修订、已知内容阻塞、权限和策略；若生效内容将变化，返回 CONFIG_RESOLUTION_STALE 及差异，要求调用方重新取得解析结果。缓存观测、恢复计划和容量检查是独立输出，不参与 config_digest；回收、恢复成功或历史恢复失败不会使内容解析过期。已准入但冷缓存只生成恢复提示，不能生成 TASK_NOT_ADMITTED；固定内容确认不可得才返回相应 blocker。

## 5. 快照固定粒度

| 内容 | 快照记录 | 重跑行为 |
| --- | --- | --- |
| 数据集 | 内部版本、Hub 原引用及 resolved_digest、本地材料摘要、任务列表、bench 全量列表 | 使用同 digest；任务子集另记 selection |
| 准入依据 | admission_id、revision、证明摘要；生效配置保存 preparation_method_digest 与实际 spec_digest | 保留原依据；重新检查显式撤销与兼容性，不要求缓存常驻 |
| 环境 | 镜像 digest、构建 / 依赖摘要、环境 ABI | 允许按摘要重新准备 |
| 模型 | 提供商、接入方式、endpoint 标识、请求模型、参数、凭据引用 | 不套最新模型修订；用当前有效凭据 |
| Harness | 不可变版本、内容摘要、参数 | 内容不匹配拒绝 |
| 附件 | 有序版本列表、每包摘要、加载契约、影响域 | 固定内容与顺序 |
| 运行资源 | CPU、内存、试次数、并发、各阶段超时与总时限 | 原值复制，仍须检查当前可执行性 |
| 计分 | 指标定义、平台错误策略版本与适配器映射摘要、奖励有效性规则、聚合方式、验证器摘要 | 原口径复制，比较中展示 |
| 执行器 | runner_id、Harbor 精确版本、Runner 协议、作业 schema 摘要 | 使用兼容且已验证的环境，不静默切换版本 |
| 来源 | 每字段来源、方案修订、团队策略修订、原运行 | 供追溯，不参与实际凭据解析 |

config_digest 是完整生效配置摘要，不包含运行身份、准入证明元数据、缓存观测和字段来源；snapshot_digest 另外覆盖来源、准入证明和冻结策略，是整份快照的校验值。comparison_digest 排除运行 ID、时间、展示名称、来源运行、准入证明元数据、缓存观测、实际任务子集和纯调度信息，保留内容、准备方式、资源、指标与重复次数等比较条件。比较模块仍逐字段展示差异，不能只凭摘要断言可比较。

执行时另写 actual_execution：实际模型响应标识、Worker / Runner / Harbor 版本、镜像 digest、资源设置和附件加载清单。实际值偏离快照时标记 deviation，禁止将其包装成严格复现。

解析器还将固定配置转换为 Harbor 作业，在对应 Runner 环境用导出的 JSON Schema 校验，并运行 --dry-run 检查参数、凭据和来源。此检查不下载任务、不验证镜像就绪，不能替代平台准备与资源检查。公共 API schema 与 Harbor schema 是不同边界，详见 [15](15-stack-harbor.md)。

## 6. 附件包协议

以下是平台建议的包结构，需由 Harbor 适配器实现转换，不假设 Harbor 已原生支持。

~~~text
attachment/
  manifest.json
  sdk/                 可选
  skills/              可选
  tools/               可选
  bootstrap.sh         可选
~~~

manifest 至少声明 schema_version、name、version、components、entrypoints、parameter_schema、compatible_harnesses、effects、load_order_requirements。

effects 使用 model_call、agent_tools、task_environment、verifier、scoring 五类。改变验证器或评分规则的包必须显式声明，形成不同的评分契约；普通工具附件不得隐式覆写验证目录。

上传流程：解包检查 → 文件清单与摘要 → schema / 路径 / 大小校验 → 兼容性检查 → 发布固定版本。拒绝绝对路径、路径穿越、逃出包目录的符号链接和重复冲突文件。发布后再次上传相同版本同摘要返回已有记录，不同摘要报冲突。

## 7. 加载阶段与冲突

1. 准备阶段在该试次容器内安装依赖并执行 bootstrap，属于已授权运行；成员 / experiment PAT 无需管理员再次准备。建议放入自定义 Agent 包装器 setup 路径；受独立安装超时、CPU / 内存 / 磁盘限制和运行总时限约束，允许按准备策略访问外网。
2. 通过环境文件传输接口将固定的 SDK、skills、tools 复制到容器约定路径，不挂载宿主机目录；执行阶段直接加载，不再临时下载依赖。
3. 验证阶段只加载已声明影响验证的部分。
4. 每个阶段记录实际摘要、开始 / 结束、出口码、产物与失败原因。

附件按配置列表顺序加载。多个附件定义相同工具名、环境变量或入口时，默认拒绝并列出冲突，不采用“最后一个覆盖”。只有 schema 显式支持的合并点可合并。bootstrap 失败归类为环境 / 附件准备失败，不能伪装成模型零分。

P0 每个试次各自安装，安装成果不写回共享数据集缓存，也不被另一个试次复用。失败仅影响本试次；按错误规则可重试时，在干净容器重新安装，不改变其他试次或版本准入。进入执行 / 验证后仍只允许批准的模型服务，不延续安装阶段外网权限。脚本不得指定宿主目录、Docker socket、服务管理命令或读取平台主密钥。

后续若缓存附件安装结果，键至少覆盖附件内容哈希、基础镜像 digest、安装参数、依赖锁及环境 ABI，并验证独立可写层与失效规则；“附件哈希 + 镜像 digest”仅是起点，不作为 P0 共享缓存承诺。仅上传附件不执行 bootstrap，安装只随受理运行发生。

### Harbor 字段映射

| 扩展包部分 | 已核对的 Harbor 接入点 | 平台补充责任 |
| --- | --- | --- |
| skills | agents[].skills | 指向已固定的本地包内容，禁止运行时漂移到新 Git 引用 |
| MCP tools | agents[].mcp_servers | 按 Agent / transport 兼容性检查；远程目标仍受网络边界限制 |
| Agent 环境变量 | agents[].env | 仅按对应阶段注入，不假定 setup 能读取同一组变量 |
| 环境 / 验证变量 | environment.env、verifier.env | 只注入必要字段，凭据保持引用直到执行 |
| SDK 与普通工具文件 | 环境文件传输或自定义 Agent 包装器 | 复制到容器；不挂载宿主目录（执行器为本试次输出挂载的日志与产物目录除外，[14](14-decisions.md) U-16），不把任意 SDK 包当作 Harbor 原生字段 |
| bootstrap.sh | 自定义 Agent 的安装 / setup 路径 | 每试次安装；时机、用户、目录、超时、失败隔离与网络切换需原型验证 |

bootstrap 不能为了下载依赖延迟到 agent.run() 才执行。公共模型能力比较中必须显示包装器与附件摘要；真实原生字段不等于所有 Agent 都支持相同 MCP / skills 组合。字段依据与首周验证项见 [15](15-stack-harbor.md)。

## 8. 验收

- 同一输入在网页与 SDK 中得到相同 config_digest、字段来源和错误列表。
- 默认值改变后，历史快照保持不变；重跑仍采用原配置和当前凭据引用。
- 修改镜像标签、附件包内容、Harness 文件时可以检测内容漂移。
- 附件改变评分规则时，结果和比较明确显示不同评分契约。
- 超出硬上限、未知参数、附件冲突均在容器启动前失败。
- 缓存回收前后生效配置摘要相同，已准入任务仍可提交；成员 / experiment PAT 的附件在试次容器独立安装，无管理员操作或宿主目录挂载。

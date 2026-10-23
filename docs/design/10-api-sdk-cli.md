# 10 API、SDK与CLI契约

阶段：P0；CLI 与 MCP 为后续范围（[14](14-decisions.md) U-11） · 来源：贯穿要求、B14、C1 / C2 / C5 / C6

导航：[总览](00-overview.md) · 依赖：[提交](04-plans-submission.md)、[权限](09-identity-security.md)

## 1. 契约原则

采用 HTTP JSON、/api/v1 前缀。FastAPI 路由和平台 Pydantic 模型输出唯一公共 OpenAPI，React / TypeScript 网页客户端与 Python SDK 类型从同一构建产物生成。SDK 采用 httpx；生成代码与手写的等待、分页、下载辅助层分开维护，不依赖服务端或 Harbor 内部代码。

网页的业务请求均通过公开定义的 API；管理 API 仍要求管理员网页会话，公共契约不意味着 PAT 获得管理员权限。Harbor 作业 JSON Schema 仅用于下游适配校验，不是第二份平台 API 来源，详见 [15](15-stack-harbor.md)。

| 编号 | 要求 |
| --- | --- |
| API-01 | 能力、参数、默认值、约束与权限可读取 |
| API-02 | 长操作返回可持久查询的 Operation |
| API-03 | 错误包含稳定代码、阶段、字段、重试信息和下一步 |
| API-04 | 创建运行等请求支持幂等，断线不产生意外重复工作 |
| API-05 | 分页、批量查询、下载与未知值具有一致语义 |
| API-06 | 版本兼容可发现，不支持的能力提前报错 |

## 2. 响应与错误

普通成功响应建议使用 data、meta；meta 至少含 request_id。列表另有 next_cursor。下载为二进制响应，不套 JSON 外壳；下载失败仍返回结构化错误。

~~~json
{
  "error": {
    "code": "CONFIG_VALIDATION_FAILED",
    "message": "单试次超时超过团队上限",
    "stage": "preflight",
    "field_errors": [
      {"path": "/trial_timeout_seconds", "code": "LIMIT_EXCEEDED", "limit": 1500}
    ],
    "retryable": false,
    "suggested_actions": [
      {"type": "edit_configuration", "fields": ["/trial_timeout_seconds"]}
    ]
  },
  "meta": {"request_id": "req_01"}
}
~~~

| HTTP 状态 | 典型语义 |
| --- | --- |
| 200 / 201 | 查询 / 同步创建成功 |
| 202 | 异步操作已受理，返回对象和 Operation |
| 400 / 422 | 请求结构 / 业务配置不合法 |
| 401 / 403 | 未认证 / 权限不足或 PAT 无管理通道 |
| 404 | 对象不存在或按权限策略不可见 |
| 409 | 幂等冲突、修订过期、资源内容变化 |
| 410 | 产物或导出包已过期 |
| 413 | 请求或批次展开规模超过限制 |
| 429 | 请求速率或 PAT 提交额度不足，code 区分 |
| 503 | 恢复中、维护中、存储不足或暂不能受理 |

retryable 表示相同业务请求是否适合重试，不代表 SDK 可以换幂等键再次提交。响应不返回堆栈或凭据。

## 3. 能力与健康接口

| 接口 | 内容 |
| --- | --- |
| GET /health/live | 进程可响应，无敏感详情 |
| GET /health/ready | API 管理能力可用；恢复 / 迁移阶段返回未就绪 |
| GET /api/v1/capabilities | 版本、功能开关、参数 schema、限制、兼容区间 |
| GET /api/v1/system-status | 认证后查看数据源、准备、Worker、存储和受理状态 |
| POST /api/v1/config-resolutions | 解析输入，返回最终值、来源、摘要、差异与 blockers |

健康、能受理和某运行可执行是三个不同判断。ready 可以为真但 accepting_runs=false，例如磁盘不足仍允许用户取消和下载。capabilities 包含 actions 及权限条件；运行实例响应再提供当前 allowed_actions。

## 4. 资源接口清单

以下为设计契约，尚无实现。读取默认团队共享，写入按 [权限矩阵](09-identity-security.md) 校验。

| 资源 | 核心接口 |
| --- | --- |
| 数据集来源 | GET /dataset-sources；GET /dataset-search；GET /dataset-search/versions；GET /dataset-search/version（后三个检索外部来源，只有管理员网页会话，U-20） |
| 目录与准备 | GET /datasets；GET /dataset-versions/{id}；GET /dataset-versions/{id}/tasks；GET /preparations/{id} |
| 模型与 Harness | GET /model-configs；GET /harness-versions |
| 附件 | GET /attachment-versions；POST /attachment-uploads；POST /attachment-uploads/{id}/publish |
| 方案 | GET /plans；POST /plans；GET /plans/{id}；PATCH /plans/{id} |
| 运行 | POST /runs；GET /runs；POST /runs/query；GET /runs/{id}；GET /runs/{id}/trials |
| 后续动作 | POST /runs/{id}/cancel；POST /runs/{id}/rerun；POST /runs/{id}/derive |
| 批次 | POST /batch-previews；POST /batches；GET /batches/{id}；POST /batches/{id}/cancel |
| 日志与产物 | GET /trials/{id}/logs；GET /runs/{id}/artifacts；GET /artifacts/{id}；GET /artifacts/{id}/download |
| 导出 | POST /exports；GET /exports/{id}；GET /exports/{id}/download |
| 长操作 | GET /operations/{id}；GET /operations |
| 集合 P1 | GET /collections；POST /collections；PATCH /collections/{id}；PUT /collections/{id}/members |
| 分析 P1 | POST /comparisons；POST /analysis-snapshots；GET /analysis-snapshots/{id} |
| 本人网页账号 | POST /session；DELETE /session；POST /me/pats；GET /me/pats；DELETE /me/pats/{id} |
| 管理员网页 | /admin/datasets、/admin/preparations、/admin/model-configs、/admin/harness-versions、/admin/credentials、/admin/members、/admin/policies |
| 运维管理 | /admin/maintenance，转交受限独立服务管理入口 |

表中除健康接口外均省略 /api/v1 前缀。附件上传由预分配上传句柄承接流式文件；publish 执行包校验并返回版本或 Operation。管理接口的方法与字段在实现前展开 OpenAPI；禁止通过通用管理字段传任意 shell。

### 任务准入与本机缓存响应

任务列表和详情分别返回准入、内容可得性与缓存，不再用一个 ready 字段决定能否提交。下例为已准入但缓存已被清理的任务：

~~~json
{
  "id": "task_01",
  "admission": {"id": "adm_01", "state": "admitted", "revision": 1},
  "content": {
    "digest": "sha256:...",
    "availability": "unknown",
    "checked_at": "2026-10-22T02:00:00Z"
  },
  "local_preparation": {
    "location_id": "local-host",
    "cache_state": "stale",
    "last_restore_error": null,
    "operation_id": null
  },
  "can_submit": true,
  "blockers": [],
  "warnings": [{"code": "PREPARATION_CACHE_MISS", "action": "restore_on_run"}],
  "required_preparation": [{"action": "restore_cache", "spec_digest": "sha256:..."}]
}
~~~

任务级 can_submit 只表达目录与当前必要配置允许选择，不保证调用方额度、维护或容量检查通过；read PAT 仍不能提交。unknown 表示尚无“确切内容不可得”的证据，不把缓存清理当作永久缺失。availability 的详细响应按必要资源列出 digest、证据与检查时间；一个任务的多个输入不能被单一任务摘要掩盖。

首次准备未成功返回 can_submit=false、TASK_NOT_ADMITTED；必要配置缺失、显式撤销和内容不可得分别返回对应 blocker。RESOURCE_CONTENT_UNAVAILABLE 包含 resource_kind、expected_digest 和脱敏 evidence，对新提交与原配置重跑使用相同规则。暂态恢复失败仅更新 last_restore_error 与关联运行错误，准入不变。

config-resolutions 同时返回 required_preparation 与 cache_observations，二者不参与 config_digest；缓存变化不产生 CONFIG_RESOLUTION_STALE。版本摘要提供 admitted_task_count、submittable_task_count、cache_ready_task_count。默认任务选择使用 task_selection.mode=all_eligible，受理后固定展开结果。

/admin/preparations 只用于管理员首次准备及其重试；成员 / PAT 的恢复只由正常提交和重跑触发，不新增绕过运行权限的手动恢复入口。共享恢复进度通过准备记录与 Operation 查询，关联每个等待试次；等待者不获得取消整个共享操作的权限。

## 5. 运行提交和幂等

~~~http
POST /api/v1/runs
Authorization: Bearer <PAT>
Idempotency-Key: <本次逻辑提交的唯一键>
Content-Type: application/json
~~~

~~~json
{
  "resolution_id": "res_01",
  "expected_config_digest": "sha256:...",
  "client_request_id": "evaluation-round-01",
  "name": "模型 A 基线"
}
~~~

受理响应 data 包含 run_id、operation_id、snapshot_digest、state 和 links。重跑 body 包含 task_selection 与 expected_source_digest；derive 包含原运行身份与 overrides，进入新解析 / 受理流程。

幂等键建议至少保留 7 天，作用域为有效主体 + 动作 + key；同键同内容返回原受理响应，不创建新资源。请求摘要包括明确配置内容和选择范围，不含无关追踪头。异步失败后同键仍返回原操作；有意再运行使用新键。

幂等键过期后重复提交可能创建新运行。SDK 不自动重试超过有效期的创建请求，应先按 client_request_id 查询既有 Operation / 运行并报告歧义。client_request_id 用于发现，不自动取代幂等唯一约束。

## 6. 统一 Operation

~~~json
{
  "id": "op_01",
  "kind": "run",
  "resource": {"type": "run", "id": "run_01"},
  "status": "running",
  "phase": "executing",
  "progress": {
    "planned": 20,
    "terminal": 7,
    "scored": 5,
    "errors": 2,
    "active": 3
  },
  "error": null,
  "result": null,
  "allowed_actions": ["view", "cancel"],
  "links": {"resource": "/api/v1/runs/run_01"},
  "revision": 12
}
~~~

status 为 accepted、running、succeeded、failed、cancelled、interrupted。failed 仍可能有可用的历史或部分结果，不能据此删除业务对象。维护 Operation 的恢复由独立管理入口负责；其他 Operation 在重启后根据业务记录重建。

取消通过业务资源接口发起，避免一个不区分资源的 Operation.cancel 绕过归属和维护权限。Operation 自身不会自动赋予写权限。

共享恢复 Operation 使用 kind=preparation_restore、phase=downloading / pulling / building / checking，响应包含 preparation_id 与调用方可见的等待关系。普通等待者的 allowed_actions 仅含 view，可通过自己的运行取消来解除等待。操作自身超时 / 失败与单个运行等待超时分别返回，保证 SDK 能定位实际受影响范围。

## 7. 查询、轮询与 SDK

列表默认 limit=50、最大 200，使用稳定的 created_at + id 游标；筛选条件改变后不能复用旧游标。运行筛选包含版本、模型、Harness、附件、提交者、时间和执行状态；批量查询接受明确 IDs 并逐项报告不存在 / 不可访问。

建议轮询初始间隔 1 秒，逐步到 5 秒，遵守 Retry-After 并加抖动；wait 的客户端超时不取消服务端操作。断线后使用 operation_id 或 client_request_id 接续，不依赖 SDK 内存保存唯一身份。

以下为拟议 Python SDK 用法，用于说明接口目标：

~~~python
client = MaestroClient(base_url=service_url, token=pat)
caps = client.capabilities.get()
resolved = client.configurations.resolve(configuration)
resolved.raise_for_blockers()
accepted = client.runs.submit(
    resolution_id=resolved.id,
    expected_config_digest=resolved.config_digest,
    idempotency_key=request_key,
)
operation = client.operations.wait(accepted.operation_id, timeout=3600)
run = client.runs.get(accepted.run_id)
client.artifacts.download_available(run.id, destination=local_directory)
~~~

SDK 类型区分 None、0、未知用量、已清理产物。下载校验摘要、支持断点或安全重试；默认不自动重提运行。兼容不匹配时先报 UNSUPPORTED_CAPABILITY，不能尝试猜测字段。

CLI 与 MCP 不属于 P0（U-11）。以后加入时建立在 SDK 之上，不成为新增管理通道：CLI 支持 JSON 输出、非零失败退出码、稳定 ID 和 --wait，PAT 从受保护配置或环境变量读取，不回显到输出。

## 8. 契约验收

- OpenAPI 校验覆盖所有响应和错误示例，SDK 类型与服务端 schema 不漂移。
- CI 从平台应用重新导出 OpenAPI，重新生成网页客户端和 SDK 类型，检查与仓库受控产物一致；SDK 单独安装时无需 FastAPI 应用或 Harbor。
- 同一业务通过网页与 SDK 得到一致快照和状态，SDK 无需服务器文件系统。
- 断线、客户端超时和重试不会重复受理；过期幂等键有明确提示。
- 管理接口拒绝 PAT，列表与下载仍遵守身份和归属。
- 能力关闭或版本不兼容时给出明确错误；轮询不把暂无进度当失败。
- 已准入冷缓存示例在网页与 SDK 均可选择并提交，首次失败与确切内容不可得均有独立 blocker；共享恢复的查询不授予管理或他人取消权限。

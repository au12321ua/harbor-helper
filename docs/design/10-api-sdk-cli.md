# 10 API、SDK与CLI契约

阶段：P0；CLI 与 MCP 为后续范围（[14](14-decisions.md) U-11） · 来源：贯穿要求、B14、C1 / C2 / C5 / C6

导航：[总览](00-overview.md) · 依赖：[提交](04-plans-submission.md)、[权限](09-identity-security.md)

## 1. 契约原则

采用 HTTP JSON、/api/v1 前缀。FastAPI 路由和平台 Pydantic 模型输出唯一公共 OpenAPI，提交在仓库的 `openapi/maestro-v1.json`；网页类型（`frontend/src/lib/schema.d.ts`，`npm run gen:api`）与 SDK 模型（`tools/generate_clients.py`）都从这份文件生成（M7，见 [M7 实施记录](records/m7-sdk-web.md)）。SDK 采用 httpx；生成代码与手写的等待、分页、下载辅助层分开维护，不依赖服务端或 Harbor 内部代码。

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
| 400 | 参数格式不合法：分页 limit / 游标、Idempotency-Key、分段读取范围 |
| 422 | 请求结构不合法（REQUEST_INVALID，field_errors 指向字段），或业务配置不合法 |
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
| GET /api/v1/capabilities | api_version、service_version、schema_revision、contract_digest、功能开关、生效限制与团队策略修订、认证方式、actions 及权限条件、执行器与 Harness 适配器 |
| GET /api/v1/system-status | 认证后查看数据源、准备、Worker、存储和受理状态 |
| POST /api/v1/config-resolutions | 解析输入，返回最终值、来源、摘要、差异与 blockers |

没有单独的“兼容区间”：SDK 要求 api_version 为 v1 且所需功能开启，否则报 UNSUPPORTED_CAPABILITY；contract_digest 与 SDK 内置摘要不同只发警告（见 [M7 实施记录](records/m7-sdk-web.md)）。

健康、能受理和某运行可执行是三个不同判断。ready 可以为真但 accepting_runs=false，例如磁盘不足仍允许用户取消和下载。capabilities 包含 actions 及权限条件；运行实例响应再提供当前 allowed_actions。

## 4. 资源接口清单

公共契约是服务导出并提交在仓库的 `openapi/maestro-v1.json`，接口的方法、字段与错误以它为准。下表只是按领域的概览，不逐条列出。读取默认团队共享，写入按 [权限矩阵](09-identity-security.md) 校验。

| 领域 | 核心接口 |
| --- | --- |
| 能力与状态 | GET /capabilities；GET /system-status；GET /team-policy |
| 数据集来源 | GET /dataset-sources；GET /dataset-search、/dataset-search/versions、/dataset-search/version（检索外部来源，只有管理员网页会话，U-20） |
| 目录与准备 | GET /datasets；GET /dataset-versions/{id}；GET /dataset-versions/{id}/tasks；GET /preparations/{id} |
| 模型、Harness 与凭据名称 | GET /model-configs[/{id}]；GET /harness-versions[/{id}]；GET /credentials（只有名称，U-23） |
| 配置解析 | POST /config-resolutions；GET /config-resolutions/{id} |
| 附件 | GET /attachments[/{id}]；POST /attachments（上传归档并发布）；POST /attachments/{id}/enabled；DELETE /attachments/{id} |
| 方案 | GET / POST /plans；GET / PUT / DELETE /plans/{id}；POST /plans/{id}/copy、/archive |
| 运行 | POST /runs；GET /runs；GET / DELETE /runs/{id}；GET /runs/{id}/trials、/summary、/request |
| 后续动作 | POST /runs/{id}/cancel；POST /runs/{id}/rerun；修改后运行：GET /runs/{id}/request 取原请求，修改后重新解析，提交时带 source_run_id |
| 批次 | POST /run-batches/preview；GET / POST /run-batches；GET /run-batches/{id}；POST /run-batches/{id}/cancel |
| 产物 | GET /runs/{id}/artifacts（可按 trial_id 筛选，日志也在其中）；GET /artifacts/{id}/download（可用 offset / length 分段读）；DELETE /artifacts/{id} |
| 导出 | GET / POST /exports；GET /exports/{id}；GET /exports/{id}/download |
| 长操作 | GET /operations；GET /operations/{id} |
| 账号与会话（网页） | GET / POST / DELETE /session；GET /me；POST /me/password；GET / POST /me/pats；POST /me/pats/{id}/revoke（撤销）；DELETE /me/pats/{id}（撤销并移出列表）；GET / POST /setup；POST /invitations/lookup、/invitations/accept |
| 管理员网页 | /admin/ 下：members、invitations、credentials、master-key、model-configs、harness-versions、harness-adapters、team-policy、capacity、dataset-imports、dataset-versions/{id}/preparations、dataset-versions/{id}/scoring-contract、preparations/{id}/evict、task-admissions/{id}/revoke、datasets / dataset-versions 删除、pats/{id}、recycle-bin、audit-events |
| 集合 P1 | GET /collections；POST /collections；PATCH /collections/{id}；PUT /collections/{id}/members（未实现） |
| 分析 P1 | POST /comparisons；POST /analysis-snapshots；GET /analysis-snapshots/{id}（未实现） |
| 运维管理 | /admin/maintenance，转交受限独立服务管理入口。现状：未实现；网页维护页只读展示状态（[11](11-web-ui.md) 第 5 节） |

表中除健康接口外均省略 /api/v1 前缀。附件以单次 POST /attachments 流式上传归档，服务端校验包并同步返回版本（同名同版本同内容返回 200），不分上传句柄与 publish 两步。原设计的 POST /runs/query、GET /trials/{id}/logs、GET /artifacts/{id} 与 POST /runs/{id}/derive 没有实现：日志与其他证据一样通过产物列表和下载读取，修改后运行见上表。禁止通过通用管理字段传任意 shell。

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

管理员的准备入口（POST /admin/dataset-versions/{id}/preparations）只用于首次准备及其重试；成员 / PAT 的恢复只由正常提交和重跑触发，不新增绕过运行权限的手动恢复入口。共享恢复进度通过准备记录与 Operation 查询，关联每个等待试次；等待者不获得取消整个共享操作的权限。

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
  "client_request_id": "evaluation-round-01",
  "name": "模型 A 基线"
}
~~~

受理时按 resolution_id 重新解析：生效配置已变返回 409 CONFIG_RESOLUTION_STALE，解析过期返回 410 CONFIG_RESOLUTION_EXPIRED；也可不带 resolution_id 直接内联配置。受理响应 data 包含 run_id、operation_id、state、config_digest、snapshot_digest、planned_trials、excluded_tasks、cache_observations 和 links。重跑 body 包含 name、task_selection（all / unfinished / explicit）与 client_request_id，按原快照重新解析受理；修改后运行不设 derive 接口，见第 4 节（[M5 实施记录](records/m5-configuration-submission.md)第四阶段）。

幂等键保留 7 天，作用域为用户 + 动作 + key，同一用户的网页与 PAT 共用（[M2 实施记录](records/m2-foundation.md)）；同键同内容返回原受理响应，不创建新资源。请求摘要取客户端原样的请求体，不含无关追踪头，并在方案、上限、来源运行等随时间变化的检查之前比对（[M5 独立审查与修复记录](records/m5-configuration-submission.md)）。异步失败后同键仍返回原操作；有意再运行使用新键。

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

列表默认 limit=50、最大 200，使用稳定的 created_at + id 游标；筛选条件改变后不能复用旧游标。运行筛选包含版本、模型、Harness、附件、提交者、时间和执行状态；批量查询接受明确 IDs 并逐项报告不存在 / 不可访问。现状：运行筛选另有方案与 client_request_id；按 ID 批量查询尚未实现。

建议轮询初始间隔 1 秒，逐步到 5 秒，遵守 Retry-After 并加抖动；wait 的客户端超时不取消服务端操作。断线后使用 operation_id 或 client_request_id 接续，不依赖 SDK 内存保存唯一身份。

Python SDK 在仓库 `sdk/`（包 `maestro_sdk`，M7 实现，用法见 `sdk/README.md`）：

~~~python
client = MaestroClient(service_url, token=pat)
client.require("runs", "execution")          # 不支持时抛 UNSUPPORTED_CAPABILITY
resolved = client.configs.resolve(configuration).raise_for_blockers()
submitted = client.runs.submit(
    name="baseline",
    resolution_id=resolved.resolution_id,     # 生效配置变了返回 409 CONFIG_RESOLUTION_STALE
    idempotency_key=request_key,              # 省略时自动生成，结果里带回
)
operation = client.operations.wait(submitted.operation_id, timeout=3600)
run = client.runs.get(submitted.run_id)
client.runs.download_artifacts(run.id, local_directory)
~~~

SDK 类型区分 None、0、未知用量、已清理产物。下载校验摘要、支持断点或安全重试；默认不自动重提运行。兼容不匹配时先报 UNSUPPORTED_CAPABILITY，不能尝试猜测字段。

CLI 与 MCP 不属于 P0（U-11）。以后加入时建立在 SDK 之上，不成为新增管理通道：CLI 支持 JSON 输出、非零失败退出码、稳定 ID 和 --wait，PAT 从受保护配置或环境变量读取，不回显到输出。

## 8. 契约验收

- OpenAPI 校验覆盖所有响应和错误示例，SDK 类型与服务端 schema 不漂移。
- CI 从平台应用重新导出 OpenAPI，重新生成网页客户端和 SDK 类型，检查与仓库受控产物一致；SDK 单独安装时无需 FastAPI 应用或 Harbor。已由 `.gitea/workflows/verify.yml` 执行 `tools/generate_clients.py --check` 与 `npm run check:api`。
- 同一业务通过网页与 SDK 得到一致快照和状态，SDK 无需服务器文件系统。
- 断线、客户端超时和重试不会重复受理；过期幂等键有明确提示。
- 管理接口拒绝 PAT，列表与下载仍遵守身份和归属。
- 能力关闭或版本不兼容时给出明确错误；轮询不把暂无进度当失败。
- 已准入冷缓存示例在网页与 SDK 均可选择并提交，首次失败与确切内容不可得均有独立 blocker；共享恢复的查询不授予管理或他人取消权限。

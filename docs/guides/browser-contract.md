# 浏览器 HTTP 类型契约

后端公开 DTO 是字段来源：`service/browser_contracts.py` 定义浏览器投影，复用 `machine.py` 的共享模型和 `attachment_contracts.py` 的附件模型。`persistence/statuses.py` 定义运行、提交、审计和报告状态；执行写入和浏览器 DTO 引用同一来源，不改变状态转换。

在仓库根目录执行：

```bash
uv sync --locked --group dev
uv run python tools/browser_contract.py
uv run python tools/browser_contract.py --check
cd frontend
npm ci
npm run test:types
npm run build
npm run lint
```

生成文件为 `frontend/contracts.json` 和 `frontend/src/generated/contracts.ts`，两者入库。工具使用项目锁定的 Python/Pydantic/FastAPI，不依赖外部生成服务或新依赖。修改 DTO 或路由后先更新生成物，再修改消费代码；`--check` 对缺失或漂移的文件失败。生成器遇到不支持的 JSON Schema 形式会失败，显式开放 JSON 才生成 `unknown`。输出路径可用 `--output`、`--schema-output` 指定。

导出不接受运行 root，不启动 app lifespan、HTTP、scheduler 或外部执行。路由枚举使用自有临时目录中的未初始化 app，临时文件自动删除；不读取已有 state、用户配置或秘密。只导出下表明确列出的浏览器契约，不发布管理员 OpenAPI，不改变 `/api/v1/machine/schema` 的 allowlist。

`ContractRoute` 在 FastAPI 序列化之前验证 handler 原始输出，递归拒绝 DTO 未声明键、缺失必需字段、错误类型和非法状态；显式 JSON 映射保持开放。校验结果不用于补默认值或删除原始字段。响应缺陷返回安全 `503 service_unavailable`，不进入请求的 422 分支，也不回显输入。浏览器与 PAT 按已认证 actor 选择独立模型；原机器 Accepted 的 schema 保持不变，输出在验证后直接发送，防止其过滤浏览器诊断列表。

九类历史 dict 管理写入使用独立 schema 描述，实际接受集合、空/null/缺省处理和业务错误仍由原 handler 与业务验证器决定。配置中原本允许的任意 JSON 标签、参数和 falsy 默认引用继续保留，前端先收窄或转为显示文本；不以响应模型变相收紧写入。

页面使用 `api`、`post`、`mutation`、`upload`。泛型只能由生成的方法/路径推导，调用方不能指定任意响应 DTO。动态路径按后端路由逐段匹配，再优先选择较具体路由；普通参数仅消费一段，拼错的 `/runs/id/logz` 不会被详情 ID 吞掉，`{key:path}` 则保留跨段查询。动态字符串 ID 的实际内容仍须符合服务器参数规则，编译器不证明运行时字符串值。`mutation` 只有 POST 可省略方法，PATCH/PUT 必须传入相符的运行时方法；页面转发封装沿用同一约束。JSON 请求体直接传对象；附件 `upload` 将生成的 metadata DTO 编码为 multipart JSON 字符串、接收 File/Blob，要求稳定幂等键，页面保留失败后的重试键。同源 cookie、请求头和 session-expired 行为保留。

`frontend/type-tests/contracts.ts` 使用实际调用层验证字段、方法、body、HTTP 路径、状态、nullable、附件 metadata/文件/幂等键和穷尽标签表的负例，不进入生产 bundle。新增状态会使标签表缺项报错，运行时未知标签仍回显原值。

## 覆盖清单

所有路径以 `/api/v1` 为前缀，下表来自生成契约。当前浏览器 JSON 调用没有 query 参数；动态 path 参数均为字符串，由现有服务业务规则验证。成功和错误媒体类型均为 JSON，三项上传使用 multipart；错误统一为生成的 `ApiFailure`。不把导航下载包装成 JSON fetch。

| 方法 | 路径 | 操作/请求来源 | 成功状态 | 身份/媒体 |
| --- | --- | --- | --- | --- |
| GET | `/access-credentials` | `list_access` | 200 | shared/session；application/json |
| POST | `/access-credentials` | `issue_access` | 201 | shared/session；application/json |
| POST | `/access-credentials/{credential_id}/revoke` | `revoke_access` | 200 | shared/session；application/json |
| GET | `/admin/access-credentials` | `list_all_access` | 200 | shared/session；application/json |
| POST | `/admin/catalog/{kind}` | `save_catalog` | 200 | shared/session；application/json |
| POST | `/admin/catalog/{kind}/{object_id}/verify` | `verify_catalog` | 200 | shared/session；application/json |
| GET | `/admin/credentials` | `credentials` | 200 | shared/session；application/json |
| POST | `/admin/credentials` | `credential` | 201 | shared/session；application/json |
| POST | `/admin/credentials/{credential_id}/disable` | `disable` | 200 | shared/session；application/json |
| POST | `/admin/credentials/{credential_id}/rotate` | `rotate` | 200 | shared/session；application/json |
| PUT | `/admin/datasets/{object_id}/author-inputs` | `save_author_inputs` | 200 | shared/session；application/json |
| POST | `/admin/datasets/{object_id}/author-inputs/check` | `inspect_author_inputs` | 200 | shared/session；application/json |
| GET | `/admin/docker` | `docker_discovery` | 200 | shared/session；application/json |
| POST | `/admin/hub` | `hub` | 200 | shared/session；application/json |
| POST | `/admin/hub/disable` | `hub_disable` | 200 | shared/session；application/json |
| GET | `/admin/limits` | `limits` | 200 | shared/session；application/json |
| PATCH | `/admin/limits` | `set_limits` | 200 | shared/session；application/json |
| PATCH | `/admin/maintenance` | `set_maintenance` | 200 | shared/session；application/json |
| GET | `/admin/model-profiles` | `profiles` | 200 | shared/session；application/json |
| POST | `/admin/model-profiles` | `profile` | 200 | shared/session；application/json |
| GET | `/admin/providers` | `providers` | 200 | shared/session；application/json |
| POST | `/admin/providers` | `provider` | 200 | shared/session；application/json |
| PATCH | `/admin/settings` | `settings` | 200 | shared/session；application/json |
| GET | `/admin/users` | `users` | 200 | shared/session；application/json |
| POST | `/admin/users` | `add_user` | 201 | shared/session；application/json |
| PATCH | `/admin/users/{user_id}` | `update_user` | 200 | shared/session；application/json |
| GET | `/attachment-operations/{operation}/{key:path}` | `attachment_lookup` | 200 | shared/session；application/json |
| POST | `/attachment-versions/{version_id}/derive` | `derive_attachment`（metadata） | 201 | shared/session；multipart/form-data |
| GET | `/attachments` | `attachments` | 200 | shared/session；application/json |
| POST | `/attachments` | `create_attachment`（metadata） | 201 | shared/session；multipart/form-data |
| PATCH | `/attachments/{attachment_id}` | `update_attachment` | 200 | shared/session；application/json |
| POST | `/attachments/{attachment_id}/versions` | `publish_attachment`（metadata） | 201 | shared/session；multipart/form-data |
| PATCH | `/attachments/{attachment_id}/versions/{version_id}` | `update_attachment_version` | 200 | shared/session；application/json |
| POST | `/auth/login` | `login` | 200 | shared/session；application/json |
| POST | `/auth/logout` | `logout` | 200 | shared/session；application/json |
| POST | `/auth/password` | `password_change` | 200 | shared/session；application/json |
| GET | `/catalog` | `catalog` | 200 | browser/PAT；application/json |
| POST | `/compare` | `compare` | 200 | browser/PAT；application/json |
| GET | `/me` | `me` | 200 | browser/PAT；application/json |
| GET | `/readiness` | `readiness` | 200 | shared/session；application/json |
| GET | `/runs` | `runs` | 200 | browser/PAT；application/json |
| GET | `/runs/{run_id}` | `run` | 200 | browser/PAT；application/json |
| DELETE | `/runs/{run_id}/artifacts/{file_id}` | `delete_artifact` | 200 | shared/session；application/json |
| POST | `/runs/{run_id}/cancel` | `cancel` | 200 | shared/session；application/json |
| GET | `/runs/{run_id}/logs` | `logs` | 200 | shared/session；application/json |
| GET | `/runs/{run_id}/report` | `report` | 200 | browser/PAT；application/json |
| GET | `/runs/{run_id}/report/download` | `download_report` | 200 | browser/PAT；导航 JSON 下载 |
| POST | `/runs/{run_id}/rerun` | `rerun` | 202 | browser/PAT；application/json |
| POST | `/runs/{run_id}/retry` | `retry_run` | 202 | browser/PAT；application/json |
| GET | `/setup` | `setup_status` | 200 | shared/session；application/json |
| POST | `/setup` | `setup` | 201 | shared/session；application/json |
| GET | `/submission-operations/{operation}/{key:path}` | `lookup_submission` | 200 | browser/PAT；application/json |
| POST | `/submissions` | `submit` | 202 | browser/PAT；application/json |
| GET | `/submissions/{submission_id}` | `submission` | 200 | browser/PAT；application/json |
| POST | `/submissions/{submission_id}/cancel` | `cancel_submission` | 200 | browser/PAT；application/json |
| POST | `/submissions/{submission_id}/retry` | `recover_submission` | 202 | browser/PAT；application/json |
| GET | `/usage` | `usage` | 200 | shared/session；application/json |
| GET | `/runs/{run_id}/artifacts/{file_id}` | 浏览器链接导航 | 200 | application/octet-stream；原权限/审计门禁 |

`browser/PAT` 项分别校验两种投影。Accepted 相关提交、取消、重跑、重试、恢复和幂等查询也分别验证；logs 是 JSON 文本信封。报告与附件下载保留原权限与安全门禁。机器专用 API、SPA catch-all、assets/favicon 不进入浏览器生成契约。

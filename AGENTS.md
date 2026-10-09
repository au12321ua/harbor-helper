# 项目工作入口

先读 [docs/HANDOFF.md](docs/HANDOFF.md)，再按当前任务读取相关原始文件；启动时不必读完整个文档目录。

## 目标与用户确认的边界

让受邀的可信团队通过 CLI 和 Web 提交、观察、比较和重跑实验；数据集可选择，实验配置固定，结果全团队共享。

本轮用户优先级：成员只用浏览器、不登录服务器完成实验操作，管理员日常配置也在网页完成；结构整理次要。当前 Web 交付与版本限定的独立结论见 `docs/web-usability-checker-report.md`。

- 保留个人提交身份，仅成员/管理员两种角色；管理员邀请账户，不开放注册，不引入复杂 SSO。
- 成员取消自己的任务；管理员可取消任何任务、删除产物、管理团队凭据与容量；重跑归当前提交者。
- 团队共用多提供商、多 key；明确绑定、加密存储，主密钥在数据库之外；密钥不回传前端、不进入日志。
- CLI/Web 共用队列、记录和容量；保留幂等、持久排队、取消/恢复及资源限制，区分有效零分、缺评分和执行失败。
- 资源释放与证据审计分开：只有执行资源未确认释放才占用清理阻塞容量；审计异常限制相关证据展示。
- 前端为 Vite + React + shadcn/ui + Tailwind；同一可配置 HTTP 服务提供构建页面与相对 API；HTTPS/代理/证书/域名由部署环境处理。
- 首版没有个人模型 key 模式、private 实验或复杂权限体系；运行时长/并发不是金额预算保证。上述边界适用于团队服务，旧本地 CLI 的兼容行为另见交接。

## 按任务查阅

- 需求来源与现场、证据边界、文档冲突：[HANDOFF](docs/HANDOFF.md)。
- 服务设计/验收/运行：[service-design](docs/service-design.md)、[service-acceptance](docs/service-acceptance.md)、[service-operations](docs/service-operations.md)。技术细节的来源分类以交接为准。
- 本地 CLI：[README](README.md)、[configuration](docs/configuration.md)、[operations](docs/operations.md)；历史验收：[acceptance](docs/acceptance.md)。
- 应用/API/数据：`src/harbor_helper/service_app.py`、`service_api.py`、`service_data.py`；入口：`cli.py`、`service_cli.py`、`remote_cli.py`。
- 执行/存储/结果：`runs.py`、`worker.py`、`storage.py`、`agents.py`、`reports.py`、`credentials.py`；Web：`frontend/src/App.tsx`、`frontend/src/api.ts`。

## 运行与验证入口

当前实现需要 Linux、Python 3.12–3.13、uv；实际执行另需 Docker/Compose、可用镜像及 Hub 数据集权限。依赖由 `pyproject.toml`、`uv.lock`、`frontend/package-lock.json` 记录。

- Python：`uv sync --locked --group dev`；`uv run pytest -q`；`uv run ruff check src tests`。测试隔离前提与版本证据见交接，不能默认这些命令无副作用。
- Web：在 `frontend/` 运行 `npm ci`、`npm run build`、`npm run lint`；构建会写入 `src/harbor_helper/static/`。`npm run test:ui` 另需 Playwright Chromium，使用拦截 API 的 UI fixture。
- 服务：按操作说明用全新独立 state 执行 `service serve --root … --setup-token-file … --master-key-file … --host … --port …`，引导凭证和主密钥在 state 外；首管理员及业务设置在网页完成。`service init` 保留兼容。成员用浏览器，远程 CLI 用 `service login`，不使用本地 `auth login` 注入团队模型凭据。

## 工作原则

区分本轮观察、版本限定的历史证据、文档声称及推测；未经用户确认的 Agent 方案、默认值或实现选择不能升格为硬约束。变更按影响范围验证，并记录代码版本、前置条件及未覆盖范围。

保护已有现场与秘密：不把凭据或运行数据入库，不用已有团队 state/真实凭据作随手测试；真实模型请求须核对当前任务授权与预算。后续代码修改或重构依当前用户任务决定，交接阶段的暂停开发不构成长期禁令。

# 项目工作入口

先按任务大小决定读多少。小任务（可回滚，不改接口、数据结构、密钥、部署和验收标准，例如查问题、清理环境、改文档或配置）只读与当前任务直接相关的文件，不必先读交接和协作规则，也不必核对群内计划版本；但操作服务、state或镜像前仍须先读 `.local/LOCAL_ENVIRONMENT.md`（若存在），“工作原则”中保护现场与秘密的要求同样适用。其他任务按下文进入。

先读 [docs/HANDOFF.md](docs/HANDOFF.md)，开发前再读[分支、协作与发布规则](docs/guides/development-workflow.md)，然后按当前任务读取相关原始文件；启动时不必读完整个文档目录。若 `.local/LOCAL_ENVIRONMENT.md` 存在，先读其中的本地保护与恢复信息，再操作服务、state或镜像；该文件由部署者维护，不要求开源clone包含它。

日常修改从 `dev` 新建短期分支和独立worktree，不在部署目录或 `master` 上开发。动态项目状态统一维护在项目飞书群的 `botmux project` 持久状态中，唯一置顶进度卡显示同一份数据；开始工作时用 `botmux project status` 核对当前任务。白板只保留入口，仓库和本地笔记不另存持续更新的进度或待办；群消息保留用户决策出处，用户当前明确指令优先。

## 目标与用户确认的边界

让受邀的可信团队通过 CLI 和 Web 提交、观察、比较和重跑实验；数据集可选择，实验配置固定，结果全团队共享。

本轮用户优先级：成员只用浏览器、不登录服务器完成实验操作，管理员日常配置也在网页完成；结构整理次要。维护与验证边界从[HANDOFF](docs/HANDOFF.md)读取；独立报告只证明其固定版本与列出的覆盖范围。

- 保留个人提交身份，仅成员/管理员两种角色；管理员邀请账户，不开放注册，不引入复杂 SSO。
- 成员取消自己的任务；管理员可取消任何任务、删除产物、管理团队凭据与容量；重跑归当前提交者。
- 团队共用多提供商、多 key；明确绑定、加密存储，主密钥在数据库之外；密钥不回传前端、不进入日志。
- CLI/Web 共用队列、记录和容量；保留幂等、持久排队、取消/恢复及资源限制，区分有效零分、缺评分和执行失败。
- 资源释放与证据审计分开：只有执行资源未确认释放才占用清理阻塞容量；审计异常限制相关证据展示。
- 前端为 Vite + React + shadcn/ui + Tailwind；同一可配置 HTTP 服务提供构建页面与相对 API；HTTPS/代理/证书/域名由部署环境处理。
- 首版没有个人模型 key 模式、private 实验或复杂权限体系；运行时长/并发不是金额预算保证。不承诺向后兼容，只维护当前主干线；旧记录可删，策略见交接。

## 按任务查阅

- 维护入口与验证边界：[开发交接](docs/HANDOFF.md)。部署现场以存在时的 `.local/LOCAL_ENVIRONMENT.md` 为准；操作前实时核对身份与引用。
- 服务设计/验收/运行：[service-design](docs/archive/team-service/service-design.md)、[service-acceptance](docs/reference/service-acceptance.md)、[service-operations](docs/guides/web-service.md)。技术细节的来源分类以交接为准。
- 远程 CLI：[Web服务指南](docs/guides/web-service.md)；已移除的旧本地 CLI 历史验收：[acceptance](docs/archive/local-cli/acceptance.md)。
- 职责：[源码结构](docs/architecture/source-layout.md)。应用/HTTP装配/初始化：`src/harbor_helper/service/{application,api,data}.py`，领域职责入口见源码结构；CLI：`commands/{main,service,remote}.py`。
- 执行/调度：`execution/{runs,worker,scheduler,runner,resources,audit,processes,agents,environments,agent_tools}.py`；持久层：`persistence/`；安全：`security/`；报告：`results/`。这些短路径均相对`src/harbor_helper/`。Web：`frontend/src/App.tsx`、`frontend/src/app/`、`frontend/src/features/`、`frontend/src/api.ts`。
- 当前使用和历史设计从[文档导航](docs/README.md)进入；旧设计与报告不成为新增约束。

## 运行与验证入口

当前实现需要 Linux、Python 3.12–3.13、uv；实际执行另需 Docker/Compose、可用镜像及 Hub 数据集权限。依赖由 `pyproject.toml`、`uv.lock`、`frontend/package-lock.json` 记录。

- Python：`uv sync --locked --group dev`；`uv run pytest -q`；`uv run ruff check src tests scripts tools`、`uv run ruff format --check src tests scripts tools`、`uv run ty check --python .venv --error-on-warning src tests scripts tools`。测试隔离前提与覆盖边界见交接，不能默认这些命令无副作用。
- Web：在 `frontend/` 运行 `npm ci`、`npm run build`、`npm run lint`；构建会写入 `src/harbor_helper/static/`。`npm run test:ui` 另需 Playwright Chromium，使用拦截 API 的 UI fixture。
- 服务：按操作说明用全新独立 state 执行 `service serve --root … --setup-token-file … --master-key-file … --host … --port …`，引导凭证和主密钥在 state 外；首管理员及业务设置在网页完成。成员用浏览器，远程 CLI 用 `service login`。

## 工作原则

区分本轮观察、版本限定的历史证据、文档声称及推测；未经用户确认的 Agent 方案、默认值或实现选择不能升格为硬约束。变更按影响范围验证，并记录代码版本、前置条件及未覆盖范围。

现场报告、原始日志/capture/截图/索引和开发草稿只进主仓 ignored `.local/`，公开文档只留短的固定版本范围摘要；不要求将 Agent 提供的原始证据重新入库。历史笔记和报告按原时点保留，不随任务反复同步为“最新状态”。集成后负责人必须按协作规则收尾 worktree/短期分支；旧群计划入口先归档再清 pin，不另建与进度卡并行的计划。

保护已有现场与秘密：不把凭据或运行数据入库，不用已有团队 state/真实凭据作随手测试；真实模型请求须核对当前任务授权与预算。后续代码修改或重构依当前用户任务决定，交接阶段的暂停开发不构成长期禁令。

# 开发交接

本页提供可移植的维护入口。团队服务的安装与成员使用见[项目README](../README.md)，详细运行说明见[Web服务指南](guides/web-service.md)。

开始修改前读取[分支、协作与发布规则](guides/development-workflow.md)：从 `dev` 建立单项分支和独立工作树，固定候选验收后才发布到 `master`/tag。当前目标、阶段、待办与阻塞统一由项目飞书群的 `botmux project` 持久状态维护，唯一置顶进度卡显示同一份数据；白板仅作入口，本地笔记和报告保留各自时点，不维护另一份动态计划。

## 产品边界

受邀的可信团队通过浏览器提交、观察、比较和重跑实验；管理员在网页邀请账户、配置数据集、多提供商/key及容量。只有成员与管理员两种角色，保留个人提交身份，结果全团队共享，无开放注册、个人模型key模式或private实验。

CLI/Web共用持久队列、记录和容量，保留幂等、取消与恢复。成员取消自己的任务，管理员可取消任何任务和删除合规终态产物；重跑归当前提交者。密钥明确绑定、加密存储，主密钥在数据库之外，秘密不回传前端或进入日志。

有效零分、缺评分与执行失败分别展示；只有执行资源未确认释放才占用清理阻塞容量，单独审计异常限制相关证据展示。时长、并发和token观测不保证金额预算，未知费用保持unknown。

Harbor按作者Dockerfile、Compose、镜像及网络定义执行；helper管理来源、调度、固定输入和结果。数据集作者参数独立版本化，提交冻结原生Job环境；修复后重试新建实验并保留父历史。新工具策略与等待倍率在受理时冻结。镜像/构建缓存日常清理须先核配置、冻结输入、活动任务与资源归属。

## 源码与兼容策略

职责和canonical路径见[源码结构](architecture/source-layout.md)。CLI位于`src/harbor_helper/commands/`，团队应用装配、领域能力、HTTP与数据位于`service/`，执行调度与资源/审计机制位于`execution/`，持久、安全、报告分别位于`persistence/`、`security/`、`results/`。

前端使用Vite、React、shadcn/ui、Tailwind，构建到`src/harbor_helper/static/`，由同一可配置HTTP服务提供页面与相对API。HTTPS、代理、证书和域名由部署环境处理。

项目尚无外部用户，不承诺向后兼容，只维护当前主干线：浏览器团队服务与基于机器API的远程CLI。旧本地CLI、旧持久Job类路径、旧镜像覆盖执行模式、旧附件上传与旧幂等键格式已放弃；旧state记录可以删除，不为其保留迁移、显示或回读分支。对外HTTP/CLI契约（含机器API v1）随主干线修改，不为旧客户端保留别名；机器API本身是远程CLI与后续MCP的基础，保留。

## 验证入口

需要Linux、Python3.12–3.13和uv；实际执行另需Docker/Compose、可用作者依赖与Hub权限。依赖由`pyproject.toml`、`uv.lock`、`frontend/package-lock.json`记录。

- Python：`uv sync --locked --group dev`、`uv run pytest -q`、`uv run ruff check src tests`。
- 前端：在`frontend/`执行`npm ci`、`npm run build`、`npm run lint`；`npm run test:ui`另需Playwright Chromium，使用拦截API的fixture。build会更新包内static。
- 验证使用独立HOME/state/master，隔离Harbor/profile并清除继承的真实凭据环境。测试含本地子进程，不能默认没有副作用；真实Hub、Docker、模型请求与fixture验证分列，真实模型请求须核当前授权与预算。

[验收标准](reference/service-acceptance.md)定义通过条件，不代表当前环境或任意版本已经验证。现场报告与原始证据只保存到主仓 ignored `.local/`；Agent 提供的原件路径不构成入库要求。公开文档只留短的固定代码版本、实际覆盖与未覆盖范围摘要；历史设计和独立报告的结论只属于受审版本。集成后的 worktree/短期分支收尾与群新版入口归档按[协作规则](guides/development-workflow.md)执行。

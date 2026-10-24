# 文档导航

本分支（`feature/rewrite`）正在把项目按目标设计重写为 Maestro，入口是[重写目标设计](design/README.md)。文档描述设计、契约和可复用的操作；进度只在[开发交接](HANDOFF.md)中维护。

## 重写设计

- [设计入口](design/README.md)：文档地位、实践优先规则、当前阶段调整和模块索引。
- [需求整理与审查](design/requirements-review.md)：需求基线（审计稿）。
- [测试验收与实施计划](design/13-testing-plan.md)：重写路线、里程碑与验收场景。
- [决策记录与需求追踪](design/14-decisions.md)：用户决定、待确认冲突、设计建议与待验证项。
- [实施记录](design/records/README.md)：各里程碑实施时的原设计与实际做法、验证范围和未覆盖项，按记录时点保留。

## 代码

- [源码职责](architecture/source-layout.md)：新 `maestro` 包的分工与尚未重写的基线模块。
- [前端开发](../frontend/README.md)、[Python SDK](../sdk/README.md)。
- 公开 API 的受控副本是 `openapi/maestro-v1.json`（运行中的服务在 `/api/v1/openapi.json`，离线用 `maestro openapi`）；网页类型与 SDK 模型从它生成。

基线的 Web 服务指南、机器 API 文档、研究客户端 skill 与附件说明已删除，需要时查 `9ff43b5`。

## 开发协作

- [开发交接](HANDOFF.md)：重写分支的状态、兼容策略和验证入口。
- [分支、协作与发布规则](guides/development-workflow.md)：独立工作树、重写分支、`dev` 集成与固定版本发布。

旧设计、归档、0.2.0 发布说明和旧验收标准已从本分支删除，可在 Git 历史与 `dev` 中查阅；它们不成为重写的约束。现场报告与原始证据只保存于 ignored `.local/`。

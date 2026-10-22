# 文档导航

本分支（`feature/rewrite`）正在把项目按目标设计重写为 Maestro，入口是[重写目标设计](design/README.md)。文档描述设计、契约和可复用的操作，不记录进度。

## 重写设计

- [设计入口](design/README.md)：文档地位、实践优先规则、当前阶段调整和模块索引。
- [需求整理与审查](design/requirements-review.md)：需求基线（审计稿）。
- [测试验收与实施计划](design/13-testing-plan.md)：重写路线、里程碑与验收场景。
- [决策记录与需求追踪](design/14-decisions.md)：用户决定、待确认冲突、设计建议与待验证项。

## 基线代码的使用与维护

以下文档描述 `9ff43b5` 基线代码，随对应模块被重写而更新或删除，不作为重写的约束：

- [Web服务指南](guides/web-service.md)：管理员配置、远程CLI、完整停机、备份与审计。
- [自动化授权与机器 API](reference/automation-api.md)：能力、schema、状态、幂等与薄 CLI。
- [团队附件版本](guides/attachments.md)、[研究客户端 skill](guides/research-skill.md)。
- [源码职责](architecture/source-layout.md)、[前端开发](../frontend/README.md)。

## 开发协作

- [开发交接](HANDOFF.md)：重写分支的状态、兼容策略和验证入口。
- [分支、协作与发布规则](guides/development-workflow.md)：独立工作树、重写分支、`dev` 集成与固定版本发布。

旧设计、归档、0.2.0 发布说明和旧验收标准已从本分支删除，可在 Git 历史与 `dev` 中查阅；它们不成为重写的约束。现场报告与原始证据只保存于 ignored `.local/`。

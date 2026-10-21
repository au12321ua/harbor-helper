# 文档导航

从[项目 README](../README.md)开始。当前任务和部署状态在项目群的持久进度卡中维护；文档描述可复用的操作与契约。

## 使用与集成

- [Web 服务指南](guides/web-service.md)：安装、首次设置、管理员配置、成员 CLI、维护与升级。
- [网页版本与更新](guides/web-updates.md)：版本来源、更新接入、持久屏障与宿主恢复。
- [团队附件版本](guides/attachments.md)：ZIP 格式、版本发布、引用与权限。
- [自动化授权与机器 API](reference/automation-api.md)：能力、schema、状态、幂等与薄 CLI。
- [Python SDK 与 MCP](guides/sdk-mcp.md)、[研究客户端 skill](guides/research-skill.md)。

## 开发与运维

- [开发交接](HANDOFF.md)：产品边界、兼容策略和验证入口。
- [分支、协作与发布](guides/development-workflow.md)：独立工作树、dev 集成与固定版本发布。
- [自动化验证与离线运维](guides/automation-ops-ci.md)：GitHub/Gitea CI、隔离验证、巡检、备份与恢复。
- [源码职责](architecture/source-layout.md)、[前端开发](../frontend/README.md)、[浏览器类型契约](guides/browser-contract.md)。
- [团队服务验收标准](reference/service-acceptance.md)：通过条件，标准本身不代表任意版本已通过。

- [测试维护约定](guides/testing.md)：测试层次、fixture/factory、严格 API mock、生产浏览器门禁与删测审查。

已废弃的本地 CLI、被否定的环境方案和被当前指南替代的设计稿不再保留在文档目录，可通过 Git 历史查阅。现场报告与原始证据只保存于 ignored `.local/`，各自结论限定到其受验版本和范围。

- [请求、版本与回收管理](guides/management.md)：版本预览确认、组与来源、回收恢复、永久删除及机器入口。

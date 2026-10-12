# 文档导航

从[项目README](../README.md)完成Web初装或成员使用，再按用途查阅。

## 使用、维护与开发

- [Web服务指南](guides/web-service.md)：管理员配置、远程CLI、完整停机、备份与审计。
- [本地CLI](guides/local-cli.md)、[配置](guides/local-configuration.md)、[操作](guides/local-operations.md)：旧本地模式兼容入口。
- [前端开发](../frontend/README.md)、[源码职责与兼容](architecture/source-layout.md)、[开发交接](HANDOFF.md)。
- [分支、协作与发布规则](guides/development-workflow.md)：独立工作树、`dev`集成、固定版本发布及群内计划入口。
- [自动化授权与机器 API](reference/automation-api.md)：固定能力、schema、状态、幂等与薄 CLI；迁移/回退边界。
- [研究客户端 skill](guides/research-skill.md)：可移植发布源、安装/调用与无附件/明确版本对照流程。
- [自动化 API 固定 50b0 独立验收](reference/acceptance/automation-50b0/README.md)：限定 PASS / 54 与会话输出文字证据边界。
- [附件候选独立安全报告](reference/acceptance/attachment-28102/README.md)：原 PARTIAL 和 Docker 补验各自版本/覆盖。
- [0.2.0版本标识补验](reference/acceptance/version-0.2.0/README.md)：固定标识同步、包内容/CLI入口一致性；旧全量和串联证据原范围保留。
- [最终集成工程证据](reference/acceptance/final-integration/README.md)：本轮全量、生产网页/CLI fixture串联及发布迁移交接；待最终独立验收。
- [额度维护固定6db930独立原件](reference/acceptance/admission-independent-6db930/README.md)：原限定范围及安全原始归档。
- [团队服务验收标准](reference/service-acceptance.md)：可验证的产品行为；标准本身不代表已经通过验收。

## 产品设计

- [附件版本与研究 agent 调用契约](design/attachment-agent-contract.md)：吸收设计审计意见后的实施契约，描述版本复用、授权、受理恢复及机器状态；不表示已经实现，开发计划仍以群内版本记录为准。

## 历史设计与验收条件

- [团队服务设计](archive/team-service/service-design.md)。
- [早期本地CLI设计](archive/local-cli/v0-design.md)、[一次登录设计](archive/local-cli/usability-design.md)、[本地CLI验收条件](archive/local-cli/acceptance.md)、[成员试用步骤](archive/local-cli/member-acceptance.md)。
- [Harbor原生环境与缓存设计](archive/harbor-native/harbor-native-environment-design.md)。
- [已否定的任务环境方案](archive/rejected-task-environment/task-environment-design.md)：只用于解释历史取舍，不能恢复为当前约束。

历史设计中的默认值、范围和建议属于原设计阶段；当前使用以指南及源码为准。工程自查、独立验收、实际部署和真实模型证据需分别记录产品版本、前置条件及未覆盖范围，不能互相替代。

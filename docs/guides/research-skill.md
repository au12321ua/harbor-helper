# 研究客户端 skill

发布源为 [harbor-helper-research](../../skills/harbor-helper-research/SKILL.md)，用于代成员调用团队服务，复用当前薄 CLI 或 HTTP。它与实验附件内提供给被评测 agent 的 `skills/`、`sdk/` 分开；不需要服务器登录，不新增 SDK/MCP、权限或队列。

使用前安装支持 [机器 API v1](../reference/automation-api.md) 的 harbor-helper CLI，或使用可安全读取凭证的 HTTP 客户端。CLI 安装见 [Web 服务指南](web-service.md)。PAT 在网页签发后，经私有文件/stdin 配置；目标 URL/profile 均由调用者选择。安装 skill 不会配置服务连接或授权真实模型预算。

本仓库保存发布源，**不自动安装到全局或改配置**。调用者可按自己的 agent 支持方式加载此 SKILL.md；Codex 使用者可主动将整个 `skills/harbor-helper-research/` 目录复制到自己选择的 skill 根目录（例如 `~/.codex/skills/harbor-helper-research/`），保留 `references/operations.md`，不要覆盖已有修改。随后在已发现该 skill 的会话中调用 `$harbor-helper-research`，例如：

> 用 research profile 发现数据集和任务，整理无附件/v1/v2 的固定对照计划；本次只授权读取，先不提交。

或在已有明确实验授权和真实模型预算的会话中委托其提交、找回原键、有限等待与比较。已授权步骤不需要重复确认；缺失执行授权/预算只推进读取。示例里的 profile/ID/数值按当前发现和授权替换，不能当默认业务限制。

skill 目录的必要参考可随复制使用，完整 schema 以目标服务运行时发现为准；它不复制完整 API 手册。discovery/readiness 可读取持久维护状态、scheduler 活动与成员额度；暂停/未知就绪只限制新受理，原键恢复仍可用。具体以目标服务 schema 为准，旧服务器可能缺这些字段。固定 `0b05daf` 的历史客户端验证和 `50b0` 的自动化服务验证只证明各自列明范围，不证明真实模型效果或后续版本。

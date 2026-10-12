# 成员额度、维护与就绪工程报告

当前状态：工程验证中，待固定版本完成自查后更新本报告；不代表独立验收。

基线为 `0b05daf92c8478f990af46e6edf45a6b10abb60f`，独立工作树 `/tmp/hh-admission-maintenance`，分支 `feature/member-admission-maintenance`。产品实现与隔离验证范围会由最终证据提交固定。正式 `master 9451363155674f138123c94c5e1ba51687139b36`、部署树、正式 state、外主密钥未改。

实现范围：管理员网页可调成员待处理额度，按 target 去重并共享身份；持久暂停/恢复新受理；birth/heartbeat 就绪及安全匿名/授权视图；机器发现/schema、网页、运维文档与研究 skill 必要引用同步。迁移与回退限制见[接口文档](../../automation-api.md#兼容升级与回退)。前项固定研究 skill 原报告及必要非秘密原始记录见[逐字归档](../research-skill-0b05daf/README.md)，原限定 PASS 不用于本轮产品。

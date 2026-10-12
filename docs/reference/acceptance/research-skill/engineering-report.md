# 研究操作 skill 工程交付

实现固定版本：`f9c8ebe860fd6a1aede9b6adf0e6f79764356d00`；基线 `50b0dde46d66bd509fed3fe56eb749919779968c`。独立工作树 `/tmp/hh-research-skill`，分支 `feature/harbor-helper-research-skill`。这是 Engineer 工程自查，**待 Root 审查/独立有界验收**，不替 Checker 宣布通过。

## 产物与选择

- 发布源 [SKILL.md](../../../../skills/harbor-helper-research/SKILL.md) 与唯一必要 [操作参考](../../../../skills/harbor-helper-research/references/operations.md)，整个目录复制后仍能读取参考。复用现有薄 CLI，无新增运行 helper、SDK/MCP 或服务业务逻辑；无需重复实现安全凭证与原键 receipt。
- [安装/调用指南](../../../guides/research-skill.md) 接入 docs 导航与机器 API 手册。安装由调用者主动选择，未安装到用户全局、未改配置。CLI 未暴露 dataset_id/构建倍率时指向 HTTP，dataset_id 的 task 例子使用确切已验证任务名。
- 操作包含安全 PAT 文件/stdin/profile、版本/能力/数据集任务切片、已有授权/预算内无附件/v1/v2 新 submit、发请求前保全成员/类别/原键/正文、原键找回及通信重发、有限观察与三轴/下一动作、安全报告与比较。scope/撤销停止，冲突不自动换键，blocked/unavailable 不伪装为待报告；不把 fixture/Oracle 当 LLM 能力证据。
- [50b0 独立归档](../automation-50b0/README.md)：两报告和十份安全文字证据逐字复制，源索引逐字保留，真实归档路径重建 SHA256 索引；初次 Node 缺依赖失败保留。原独立报告 SHA256 为 `3a0f9386c675d8f7ca916dc547854d6d29c693739fa252682e11278b56063ddb`，限定 PASS / 54 仅属于固定 50b0 和原范围。归档前核全部 12 个源索引项（含未收入截图）的摘要/字节数。补报告引用的不存在 sha256-index.json 由 README 解释，不改原件。执行文字为会话 tool 输出副本，未倒称原始 stdout；未重跑原验收。

src/frontend/tests/依赖锁与基线完全相同；未改主部署树、旧自动化工程树、dev/master 或正式服务/state/master/镜像。

## 实际验证

使用既有 dev Python 3.13 环境只读复用依赖，源码及测试从独立工作树加载；env -i 白名单 PATH/HOME/PYTHONPATH，HOME 在本次私有 /tmp 目录。所有 fixture state/master/profile 都在独立 basetemp，HTTP 使用动态 loopback 端口。未继承真实模型凭据。测试后的专属子进程由 fixture 收尾，临时 state/master/profile 已清理，不入库。

固定实现提交上实际命令（stdout/stderr 运行时重定向，exit 0）：

```bash
env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp/hh-research-validation/home PYTHONPATH=/tmp/hh-research-skill/src:/tmp/hh-research-skill/tests /tmp/hh-automation-api-v1/.venv/bin/python -m pytest -q -p no:cacheprovider docs/reference/acceptance/research-skill/scenario.py tests/test_automation.py::test_three_axes_report_scores_and_evidence_boundary --basetemp /tmp/hh-research-validation/pytest-fixed
```

**4 passed，1 条 Starlette/httpx 弃用提示**。[场景 harness](scenario.py) 为验收复现材料，未随 skill 发布为运行 helper。1 个实际监听 HTTP→CLI→生产 scheduler/worker 场景覆盖：

- 明确 research profile，安全文件与 stdin 配置；0644 文件及 symlink 拒绝；schema/discovery、任务切片续读。
- 已确认固定条件的无附件/v1/v2 三个新提交；receipt 原成员/正文/路径/键保全到独立记录；原键未知 404 后仍用原键提交。丢弃成功响应再 lookup/service retry 得同 ID，冲突 fix_input 不新增任务。
- 三轴查询有限等待，资源 released/audit clean/report available；有效零分保持 0；两组比较可比且展示 bundle_change 与冻结 v2 身份。
- 已终态隔离记录改为审计异常与缺报告，分别 blocked/contact_admin、unavailable/explicit_new_attempt，报告请求明确失败。
- read-only scope 拒绝新写、撤销拒绝读取；同成员替换凭证找回原键；提交数量保持三条；输出、服务 state/产物及 HTTP 日志无生成 PAT 明文。

另 3 个现有安全报告参数场景实际执行：有效 0、缺评分 missing_score、执行失败 execution_failure，安全报告不泄露原始异常；阻塞/资源门槛与缺报告响应保留。

skill-creator quick_validate 对仓库目录及复制目录均通过；必要相对引用与导航检查、归档逐字/SHA/长度检查、可识别 PAT 明文扫描、harness ruff 与 git diff --check 通过。系统 python 首次运行 quick_validate 缺 PyYAML，改用已含依赖的既有 dev Python 后通过，未安装系统依赖。

场景开发两次失败原 stdout/stderr 保留在 logs：自建已验证数据集缺 resolved 导致安全 503；补齐后，harness 错调用不存在的 ServiceData.submissions。分别补齐合成 fixture 和用数据库实际受理数断言修正；没有改服务或弱化断言。最终固定提交完整场景重新执行通过。日志 SHA/字节索引见 [evidence-sha256.json](evidence-sha256.json)，与旧 Checker 会话文字证据保存方式分开。

## 未覆盖与下一步

外部来源/worker 执行 adapter 均为既有隔离 fixture；Oracle 选择也不是真实 Harbor/Oracle 执行。未发 Hub/Docker/模型请求，无真实预算消耗；未验证真实模型效果、LLM 自主研究能力、真实来源任务 glob 筛选、生产 HTTPS/代理或升级恢复。没有新 SDK/MCP、额度/维护功能，没有重跑无关全量/build/UI；服务固定 50b0 的历史 PASS 不等于新 skill 已独立验收。

工程范围无未完成实现项。下一步由 Root 审候选，再按风险作一轮有界独立行为验收；真实模型实验需另核实际授权与预算。

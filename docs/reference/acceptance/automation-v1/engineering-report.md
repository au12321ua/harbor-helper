# 自动化授权与 API 机器契约工程交付

状态：实现完成，**待主控审查及 Checker 独立验收**。本文为实现负责人的版本限定自查，不是本项或下一阶段整体验收 PASS。

## 固定版本与产物

- 基线 `origin/dev 28102da47acfae696cf8cce1e8f42dee057944a9`，开发独立树 `/tmp/hh-automation-api-v1`，分支 `feature/automation-api-v1`。
- 受测实现提交：`d46e31ae8f6bab129f7a3e03b984f9542c46730a`。实现之后附加的交付提交只加入本文及安全日志，不改代码、static、测试或锁；最终候选 SHA 以交付消息为准。
- 受测源码 tree `b3e3e324084550d013adf8c0d047723b2db5e95b`，frontend tree `972cd36fecf639dfa4f1570d9bdcd41174e15f26`；构建后 `git status --short` 空，源码/static 与固定提交一致。
- 完整接口、能力表、schema/错误/状态/薄 CLI、迁移与回退说明：[自动化 API](../../automation-api.md)。实现位于 `service/access.py`、`service/machine.py`、`service/api.py` 及既有应用/持久层，CLI 共用 HTTP，前端只局部新增凭证页面。
- 前项独立安全原文及 SHA：[附件候选归档](../attachment-28102/README.md)。两份逐字保留原 PARTIAL 与 Docker 补 PASS，各自固定版本/范围，不作为本项独立验收。

## 可观察交付

网页签发复核当前密码，默认只读/30 天，可调整到期；明确选择 attachments/execute/cancel_own，原值一次显示且关闭/重载不找回。列表显示名称、用户 ID、能力、到期、撤销和最后成功认证时间；管理员网页可查看全团队及撤销任意凭证。PAT 随机格式固定，服务只存摘要；账户停用/撤销/过期/重置拒绝后续调用。管理员 PAT 也无管理员权限，不能铸造授权、维护别人附件或取消别人任务；浏览器保留角色。

机器接口提供限制过的类型化 OpenAPI，逐操作固定能力、metadata schema、当前数据集/任务目录切片/模型方案/附件版本/限制及安全状态。机器报告使用类型化安全投影，保留有效零分/缺评分/执行失败，排除原始异常与宿主配置。三轴由现有生命周期派生，不改容量或历史 manifest；终态无报告 unavailable，未知审计进度 blocked，未知资源不因显示额外占容量。heartbeat 只证明核到 scheduler 活动，不宣称维护/成员额度/统一就绪受理开关完成。

submit/rerun/retry/recover 按当前成员+固定类别+键幂等；目标进入请求摘要，换目标冲突，匹配先于新容量检查。按键找回跨同成员不同凭证与网页会话，先鉴身份/scope，不泄漏别人请求；未知键不建议换键。旧目标前缀记录兼容、不重写历史；多目标历史键明确歧义。受理和审计记录当前用户与非秘密访问 ID，复制父输入不复制父访问身份。空输入操作不接受意外字段，附件不能通过 rerun 偷换。

薄 CLI 支持安全文件/隐藏输入/stdin 配置，不接收 literal token argv；沿现有 owner-only remote profile 存储，兼容会话 profile。发现/schema/任务切片/提交/原键找回/恢复/查询/安全报告均走同一 HTTP 与队列，没有独立授权或执行回退。沿既有完整树扫描/脱敏，拒绝 PAT 格式和当前请求 bearer 的明文附件、快照、请求字段/键；不把访问值传入 worker/env。

## 实际执行的固定版本检查

日期 2026-10-12。Linux，Python 3.13.13、Node v22.23.1、npm 12.2.0；`uv sync --locked --group dev`、`frontend/npm ci` 完成，锁文件未改。独立 HOME `/tmp/hh-automation-validation/home`，各 pytest fixture 自建独立 state/外 master/Harbor profile，fake 账户和模型 key；`env -i` 清掉真实继承环境，仅传 PATH/LANG/HOME 及浏览器测试标志/浏览器缓存路径。HTTP 监听由 fixture 选独立空闲端口，按持有进程/birth 身份收尾，不使用正式 state。

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 固定 d46e31a 全量 Python（启用生产浏览器专项） | **292 passed**，无 skip，116.25 秒 | [日志](logs/fixed-d46e31a-python.log) |
| UI fixture 全量 | **28 passed**，15.5 秒 | [日志](logs/fixed-d46e31a-ui.log) |
| npm run build | 成功；`index-D4xOaHh3.js`/`index-Brm6OTRC.css` 与源码同提交 | [日志](logs/fixed-d46e31a-build.log) |
| npm run lint | 成功，无警告 | [日志](logs/fixed-d46e31a-lint.log) |
| ruff check src tests | All checks passed | [日志](logs/fixed-d46e31a-ruff.log) |
| git diff --check | 成功 | [日志](logs/fixed-d46e31a-diff-check.log) |

所有入库日志非秘密 SHA/字节数见 [log-index.json](log-index.json)。没有上传 state、私有 profile、原值或整个 evidence。失败记录也保留，未删必要测试或降低断言。

`tests/test_automation.py` 的 15 项参数化用例覆盖：成员/管理员 PAT 的能力矩阵及管理员边界；密码复核、摘要/元信息、过期/撤销/密码重置/账户停用与恢复；旧会话角色；跨凭证与网页登录同键、跨成员/不足 scope 拒绝、先匹配再容量、固定类别目标冲突和旧键兼容；并发跨凭证同键唯一；recover/retry 当前身份与键；三轴/零分/缺评分/执行失败/终态缺报告/未知 scheduler/未知资源/安全输出；附件及父快照完整 PAT 明文拒绝；每个 schema 操作必须有能力、类型和安全错误声明。

`tests/test_automation_http.py` 的实际监听 HTTP 专项在该全量中 **2 项通过**：

1. 非交互 subprocess CLI 经生产 API、真实 scheduler/worker 进程完成一次网页授权后的发现→无附件 baseline→按键恢复→v1/v2 明确版本候选→查询→安全零分报告与比较；另凭证/网页找回同一键、撤旧凭证、私有 profile 文件/stdin 配置均验证。API、授权、队列、冻结、报告和 CLI 用正式实现；外部 source/执行 adapter 位于复制包内 fixture，返回原生形状的零分结果，**不是真实 Docker/Hub/模型执行**。
2. Playwright 从真实 HTTP 服务读取本提交的生产构建静态页，真实登录/签发密码错误/保持会话与清空密码/默认只读签发/原值只显示一次/重载不再显示/撤销；API 没有拦截。生产 UI 的账户/state 是隔离 fake fixture。fixture UI 另覆盖显式 execute 勾选和请求正文，管理员边界由实际 HTTP/API 用例覆盖；不声称所有管理员网页操作都有独立端到端故事。

现有 275 项测试（其余 17 项为本次 automation/HTTP 用例）仍通过，含模型凭据、旧远程 profile、附件冻结/比较、取消/执行恢复、资源/审计分离及前端配置回归。已有 fixture 的通过不能倒称为真实外部执行验证。

## 中间失败与修复证据

- [首轮回归](logs/regression-initial.log)：57 通过/1 失败。浏览器冻结绑定新增 null 键撞到原“不得继承父凭证字段”断言；实现改为浏览器冻结沿用省略，公共响应仍 null，原断言保留。
- [首轮生产 UI](logs/http-initial.log)：CLI 闭环已通过；浏览器 harness 的“用户名”标签与实际“账户”不符，修正定位器。
- [第二轮生产 UI](logs/http-second.log) 和 [UI fixture](logs/ui-third.log)：复核密码失败的 401 被公共客户端误当会话过期，页面跳回登录。修复 `invalid_login` 不触发 session-expired，保留错误及密码清空断言，固定版本真实 HTTP/fixture 均通过。
- [首次 UI 服务等待](logs/ui.log)：dev server 就绪等待超时，外部原因未确定；使用隔离环境重试通过，不推断部署故障。
- [专项追加失败](logs/automation-final-initial.log)：新用例缺 ThreadPoolExecutor import；另 schema 逐操作审计发现 Starlette `:path` 转换后的 OpenAPI 路径未加 x-capability/x-operation，改用 route.path_format。没有跳过路径或弱化覆盖检查，固定版本全部声明操作有注解/错误结构。

这些中间版本日志仅用于修复审计，不能作为固定 d46e31a 的通过证据。

## 未覆盖、迁移及后续

本项无真实 Hub/模型调用、无新 Docker/Harbor/Oracle 补验、无 LLM 自主研究能力/效果证明。前项 Docker 补验仅属于附件候选与本地 source fixture，LiteLLM 公开价格表超时回退仍如其原报告，不写成 Hub/LLM 通过。本项无独立研究 skill/完整 SDK/MCP、成员额度、公平调度、维护开关或备份实现/演练；不是整个下一阶段完成。

无正式部署/服务/state/主密钥操作、无 master/dev 集成或全局清理。只创建独立 worktree、运行隔离 fixtures、正常提交与推送 feature。交付时远端 dev 仍 28102da4，master 仍 94513631。

新增 access_credentials/access_events 在 SQLite 事务创建；不改旧表结构/manifest/评分、不中断迁移失败后继续服务。真实存量部署迁移及生产恢复演练未进行。尤其旧代码的 per-target 幂等会遗漏新 fixed-operation 记录；禁止有新客户端通信重试时直接恢复旧受理写服务，也不能删键/回放旧 state。发布前保全最新一致 state/外 master、核所有写者；完整[接口与回退边界](../../automation-api.md#迁移与回退)。

当前无已知阻塞本有界交付的未完成实现项；剩余是主控固定候选审查及有界 Checker 独立验收，任何新发现按固定版本另报告，不由实现负责人宣告通过。

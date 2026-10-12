# 成员额度、维护与就绪工程报告

结论：**工程完成，待 Root 固定候选审查及 Checker 有界独立验收**。本报告为 Engineer 自查，不宣布独立 PASS。

## 版本与交付

- 基线：`0b05daf92c8478f990af46e6edf45a6b10abb60f`（实时 origin/dev）。实现固定：`7b77f5f3a922b131cef6522b46ed7b2f646e6fe1`。本报告及原始自查日志另以证据提交交付，后者不改 src/frontend/tests/skills/锁文件。
- 独立工作树 `/tmp/hh-admission-maintenance`，分支 `feature/member-admission-maintenance`；正常 push 同名 feature，未合入 dev/master。最终 tip 由 Git 与派单回报固定，报告不自引用尚未产生的提交 SHA。
- 源码和重新构建 static 同提交。正式 `master 9451363155674f138123c94c5e1ba51687139b36` 保持；本轮没有操作旧工程/部署树、正式 state、外 master、既有服务/镜像或运行凭据。这里只证明本轮执行范围，不断言其他协作者/外部进程从未改变现场。

## 当前行为

管理员浏览器在团队管理→容量与保留可调整 `max_pending_per_member`。配置默认10可调整，有效值 `min(配置,max_queue)`；全部 CLI/Web/PAT、新的 submit/rerun/retry/recover 都走 Application.accept，同成员所有凭证与管理员本人共用 user_id。准备与排队按 target 去重；run 已落库时按 run 当前 queued/active/terminal 判定，不再计残留 preparing。可靠身份来自对应受理或冻结 service.user_id；旧无身份记录不按姓名猜成员，仍计全局/执行容量。降额不取消存量。取消 preparing/准备失败立即释放；排队取消请求到调度器确认终态才释放；开始执行不再占待处理。原执行资源与证据审计容量规则保持。

维护 `admission.json` 原子保存 paused/reason/retry_at/updated；更新和新受理共享 control 锁，每次锁内读取最新持久值。成功旧幂等找回位于维护、就绪及额度检查前，身份/scope仍在最前；禁用成员在锁内再核对。暂停不停止 scheduler；已有准备/队列继续排空。建议重试时间不自动恢复，读/取消/安全报告保留原门槛。

`GET /health` 匿名仅 alive/ready；`GET /readiness` 授权读取 initialized/accepting/安全 reason/observed、scheduler/maintenance/pending，PAT需read。管理员维护默认拒绝 PAT。birth 身份与 heartbeat 从同一次 scheduler 观察复用；正常循环约0.5秒，10秒以上、缺失或未来活动为 unknown/unready，未确认进程为 unavailable。无需新心跳进程。新受理503 maintenance_paused/scheduler_unready，额度429 member_queue_full/queue_full；沿现有 action=retry_same_request 与未知等待表示。网页、机器 schema/discovery、接口/运行指南和研究 skill 必要引用同步。accepting 只是维护/活动门，不预留容量、不保证外部执行成功或开始时间，不声称公平调度/金额预算。

公共维护原因禁止已存团队模型/Hub秘密（包括旧版本及停用值）、PAT、当前会话值及内部绝对路径；安全校验异常不回显输入。没有配置/PID/birth/宿主路径/密文输出。可信管理员仍不得把任意未登记、编码或拆分秘密写进公开文本；没有宣称通用秘密识别。

## 固定实现的实际验证

Python3.13.13、Node22.23.1、npm12.2.0；uv锁定安装、npm ci，锁摘要及环境见 [environment.json](capture/environment.json)。执行环境从空字典白名单构造（等价 env-i），仅保留 PATH/语言/缓存/浏览器位置；独立 HOME/XDG/Harbor profile。每个 state 新建，master在其外；不继承真实模型/cloud/PAT环境。单位测试显式写入**测试进程 birth + 合成心跳**，不启动实际 scheduler、不旁路生产就绪判断；进程/HTTP测试启动真实隔离 scheduler并等待有效活动。旧未知审计、GET无副作用与CLI读取消断言通过先移除合成心跳保留，未削弱断言。

| 固定7b77f5f检查 | 实际结果/原始记录 |
| --- | --- |
| `.venv/bin/python -m pytest -q --basetemp=/tmp/hh-admission-validation/fixed-python`，HH_TEST_BROWSER=1 | **327 passed，无skip**；2个原依赖弃用提示。[输出](capture/python-fixed-7b77f5f.log)、[退出0](capture/python-fixed-7b77f5f.exit) |
| `npm run test:ui` | **29 passed**，拦截API UI fixture。[输出](capture/ui-fixed-7b77f5f.log)、[退出0](capture/ui-fixed-7b77f5f.exit) |
| `npm run build` | static与提交内容一致。[输出](capture/build-fixed-7b77f5f.log)、[退出0](capture/build-fixed-7b77f5f.exit) |
| `npm run lint`、ruff check src tests | 0错误/警告。[lint](capture/lint-fixed-7b77f5f.log)、[ruff](capture/ruff-fixed-7b77f5f.log)，各退出0 |
| 固定版本diff-check | `0b05daf..7b77f5f`通过，包含前项逐字原件。[输出](capture/version-diff.log)、[退出0](capture/version-diff.exit) |
| skill quick_validate、必要相对引用/前项归档SHA | 通过；skill内容与固定实现相同。[skill](capture/skill-validation.log)、[引用及31份归档摘要](capture/link-archive-validation.log) |

专项 `tests/test_admission.py` 覆盖：同成员两PAT+Web、管理员本人、跨成员、并发原键唯一/新键额度、额度降低、target已发布而submission未ready时的queued/active/cleanup/终态去重、未知历史身份保全全局与执行容量、实际准备失败/取消/入执行释放、所有新操作的维护门、旧键/失效活动、只读scope先拒绝、管理员PAT拒绝维护、线性锁并发及跨进程读取、重建API仍暂停、当前/陈旧/错误birth、匿名/成员安全投影、故障文件拒绝、schema/discovery、旧limits合成升级保DDL/密文/历史manifest/外master。

`tests/test_admission_http.py` 用两实际API进程读同一持久 state：第二进程先观察开放，另一进程写暂停后立即看到暂停并拒新键，旧键仍找回；真实CLI提交→准备hold→暂停→原键恢复→放开hold→实际scheduler/worker fixture排空，safe report有效零分；CLI新键被503拒绝（真实退出1），scheduler停止后真实身份不可用/原键可找回，恢复维护仍unready，重启scheduler后新受理排空。五条CLI原stdout/stderr/退出在 [admission-cli.jsonl](capture/admission-cli.jsonl)，不保存Authorization或PAT原值。外部来源/镜像/worker执行适配器是fixture，不是真实Hub/Docker/模型执行。

## 生产网页QA

流程：实际HTTP提供构建static→管理员登录→修改成员额度3→暂停并填写原因/建议时间→刷新确认额度与暂停仍保存→成员登录并导航共享实验读取安全详情→管理员恢复。Browser插件不可用，使用项目Playwright Chromium；桌面1280×900与成员390×844。

| 检查 | 观察 |
| --- | --- |
| 页面身份/非空 | 实际服务URL与`Harbor Helper · 团队实验室`标题；管理/共享实验内容真实渲染 |
| overlay/异常 | 无Vite overlay或pageerror；唯一console网络错误是启动未登录 `/api/v1/me` 的预期401，响应路径及数量有断言，其余无HTTP错误 |
| 交互/持久 | PATCH limits/maintenance真实响应及刷新后当前值；成员无恢复按钮；恢复后显示允许新受理 |
| 布局/截图 | 移动端无页面横向溢出；两截图经实际查看，表单、状态及未知等待文本可读 |

浏览器原stdout/stderr/退出：[browser.stdout](capture/browser.stdout)、[browser.stderr](capture/browser.stderr)、[browser.exit](capture/browser.exit)。安全截图仅保留在 `/tmp/hh-admission-validation/evidence/admission-admin.png`、`admission-member-mobile.png`，摘要/字节由 evidence-sha256.json 固定，不上传整包fixture资源。需要应用内浏览器工具时可另安装Browser插件；本轮未安装插件/修改全局浏览器配置。

## 原失败、归档及收尾

[capture](capture/) 保留每次检查原始合并stdout/stderr和退出码，不用成功输出替换失败：

- python-initial：6 failed/309 passed；合成活动引入后3个旧“未知审计”测试及GET/CLI“无scheduler文件”缺明确前置，生产浏览器在独立HOME找不到缓存。修正前置与浏览器位置，未删断言。admission-first：1 failed/7 passed，历史fixture的manifest缺原summary需要的effective字段，补完整旧输入。
- targeted-second：1 failed/76 passed，CLI原无scheduler文件断言仍见合成文件；在提交后去掉合成活动，原键/read/cancel仍须通过且原断言保留。
- ui-first：1 failed/28 passed，新测试误把原CardTitle div当heading；定位实际卡片文本，没有改变保存行为。
- production UI first/second/third各1失败：分别是测试预期title少团队后缀、换成员后仍在/admin而未导航共享实验、把启动未登录/me的正常401当应用错误。修正真实页面身份/导航并精确断言仅该401（不全局忽略console错误）；fourth及固定全量通过。
- ruff-initial：导入顺序；格式修复后固定ruff通过。额外一次编辑脚本因cwd为frontend而使用仓库根相对路径失败，工具输出已在会话保留；该非验证编辑步骤没有另捕获原始字节流，不将会话文字说成raw stdout。后续编辑在独立仓库根完成。

归档原始失败日志后，最终证据提交的完整staged diff-check会报告这些原日志的行尾空白（退出码见capture/staged-report-diff.exit）；只出现在capture原stdout路径，逐字保留，没有去空白改原件。排除capture后的产品/文档diff-check通过；不声称最终全diff无空白。

本轮所有验证捕获的原失败stdout/退出码及成功记录的摘要/来源见 [evidence-sha256.json](evidence-sha256.json)。只归档必要非秘密输出；PAT形态扫描无命中。没有复制 state/master/PAT/profile、整个源码fixture资源或运行产物包。四个HTTP fixture teardown及监听复核均关闭，fixed-python目录中的run PID/birth无匹配残留，见 [postrun.json](capture/postrun.json)。只核本轮独立目录，不作全机清理；fixture state留在本地供复核。

前项研究skill原报告逐字归档 [research-skill-0b05daf](../research-skill-0b05daf/README.md)，SHA `cc9b5a6d5b844d2f11983340f1d1859364388b3c4fa03e384f0c20774b65f683`；31份必要原件包括最终capture和早期失败，逐字摘要已复核。其限定PASS只属于原固定版本与确定性fixture 0/1/0、504恢复和比较范围，不能改写成Harbor/LLM效果，也不是本轮产品验收。

## 迁移、回退与未覆盖

本次无新增SQLite表/字段或历史manifest迁移。旧limits缺新字段时读默认10并受max_queue约束；合成旧limits升级保全DDL、模型/Hub密文、历史manifest与外master字节及0600模式。新增维护文件缺失按首次默认开放解释，仍需就绪；损坏拒绝新受理，不自动开放。

**回退旧代码会忽略维护开关及成员额度/就绪门，不能把“已暂停”当作旧代码仍受保护。** 回退前阻断外部新写入口、确认最新业务/全部写者与资源状态，保留admission.json/limits及全部受理、幂等、历史输入/密文与原外master。不得删新文件、重init/换master或用旧备份覆盖新增业务。恢复本轮代码继续读原持久暂停值。暂停不是可立即备份。完整边界见[接口迁移/回退说明](../../automation-api.md#兼容升级与回退)。

未做真实Hub/Docker/模型请求、真实LLM评分、正式升级/备份恢复、HTTPS/代理部署、全局清理、公平调度、复杂配额账户或金额保证。未证明断电/fsync灾难恢复、多主机共享文件锁、任意恶意管理员分片/编码秘密识别或大量历史记录性能。本轮为同一state/本机多API进程的原锁模型，完整外部执行与部署仍须另行授权和固定验收。

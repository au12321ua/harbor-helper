# 最终集成候选工程报告

工程检查完成，**待 Root 审查和一次最终 Checker 独立验收**。本报告不是阶段整体 PASS，也没有发布、部署或真实外部执行。本任务按群计划 v1.7（`om_x100b63ff158434a4c479c3e0b7019d0`）执行，本页只记录交付证据，不复制路线。

## 固定版本与前置

- 起点为实时远端 dev `6db930d37b7e0f78e20fe3ec8221357b286b6352`；独立工作树 `/tmp/hh-final-integration`、分支 `feature/final-integration-candidate`。
- 全量受测产品为上述6db930d。新增归档/串联 harness 固定 `46a466fda25e669afe3a8e04cbae88e2d37d251f`；补完整网页报告/比较后固定 `efbc35908fd608da3f6cf11f8bd185586c5e4c79`，最终串联与打包检查在该提交执行。`src/`（含static）、原 `tests/`、`skills/`、frontend/src及全部锁文件/包元数据与6db930d逐对象相同；新增frontend/qa脚本分别补验。末提交仅报告/安全证据，交付提交可从Git取得，不把新报告提交倒称全量实际运行版本。
- 先核主树/refs，读取 AGENTS、HANDOFF、开发流程和主树存在的 `.local/LOCAL_ENVIRONMENT.md`。主树 master/部署保持 `9451363155674f138123c94c5e1ba51687139b36`，没有切部署分支、修改正式服务/state、移动dev/master/tag或调用Docker。
- Linux，Python3.12.3、uv0.11.31、Node22.23.1；全新独立HOME/XDG/Harbor profile、HF/Docker目录及uv/npm cache，子进程环境白名单等价env-i，未继承真实模型/Hub/代理凭据。只读使用已有Playwright Chromium安装。依赖公开下载由uv/npm按锁执行；不把安装网络活动说成完全离线。
- Browser插件未提供，依 frontend-testing-debugging 技能使用现有Playwright；1280×900与390×844。本机HTTP提供生产静态文件，实际CLI/API/scheduler/worker生命周期；只有外部source/image/execution适配是隔离复制包fixture，生产源码没有fixture开关。评分是确定性fixture verifier，无Hub、Docker/Harbor容器、Oracle或模型请求。

## 实际执行

原命令JSON、stdout/stderr字节与退出分别在 `capture/<name>.*`；CLI子命令的原文本输出/退出在研究capture的 `cli-transcript.jsonl`，没有记录PAT值。所有失败原件保留。

| 检查 | 本轮结果 | 证据 |
| --- | --- | --- |
| uv sync --locked --group dev；npm ci | 均退出0，锁不变 | uv-sync / npm-ci |
| Python全量，HH_TEST_BROWSER=1 | **352 passed，0 skipped**，138.38秒；两项依赖弃用警告 | python-full |
| npm run test:ui | **29 passed**，16.3秒；拦截API的UI fixture | ui-fixture |
| npm run build / lint；ruff check src tests | 均退出0；build与已提交static字节相同 | build / lint / ruff |
| 新串联harness lint/ruff及浏览器最终补验 | 退出0；最终脚本efbc359实际串联成功 | harness-lint / harness-ruff / research-complete |
| wheel/sdist构建与字节检查 | 退出0；CLI入口、static、产品文档/源码/锁、完整可复制skill相同 | package-fixed / release-fixed-check |
| 产品/skill链接、产品文档diff | 93个当前相对文件目标存在；diff原文保留；skill内部引用可移植 | release-fixed-check |
| 收尾与保护引用 | fixture进程birth释放、HTTP/代理端口和4173关闭；主树clean、远端dev/master原SHA | cleanup-check |

352是本轮实际全量，不沿用旧7b77的327或旧API报告的292；原历史失败和限定报告保持不变。Starlette TestClient/httpx与Harbor allow_internet弃用警告没有导致失败。相对链接检查是文件目标检查；不存在本轮全历史锚点验证的声称。

## 完整串联与覆盖矩阵

最终 `research-complete/capture/results.json` 固定efbc359：薄CLI无附件/v1/v2与生产网页无附件/v1/v2共六个实验，attempt1/concurrency1/wall120，同一fixture任务及评分来源。两组分数都是0/1/0；四组比较可比，mean_task_delta分别+1/-1/+1/-1。浏览器三项都实际POST受理，等待安全报告、打开评分页并通过真实比较控件展示无附件→v1；没有拦截浏览器API。CLI与网页各组内部条件固定；网页全任务与CLI单任务字段/构建倍率默认可能不同，本轮**没有跨两组比较**。这是绑定/操作/报告流程证明，不能说研究agent或LLM提升。

| 风险 | 当前候选实际覆盖 | 性质与限制 |
| --- | --- | --- |
| 凭证签发、复核、撤销与成员边界 | 全量包含实际生产网页凭证流程；最终串联read-only发现、同成员更换、服务端撤销旧PAT后旧认证401、replacement原键可找回；网页成员无团队管理入口 | 本机真实HTTP/浏览器；完整scope、管理员PAT不能维护/越权取消另由 test_scope_matrix_and_admin_never_automation、test_concurrent_cross_credentials_fixed_key_and_admin_own_boundary覆盖，TestClient fixture，不是实际团队认证 |
| 响应丢失与原键 | 实际代理上游202后返回504，CLI退出1；保全原请求/key，换同成员PAT原键找回唯一受理，未造补偿键 | 真实本机HTTP/CLI，网络故障由一次性代理合成；不证明断电恢复 |
| 并发、受理发布窗口 | 全量 test_concurrent_unique_acceptance_and_limit_reduction、跨凭证同键、test_target_publication_crash_dedup_and_releases | 并发TestClient/SQLite/control锁；target已落queued/active/终态而受理未ready为合成发布窗口，不是强制杀生产进程 |
| 附件版本历史、无附件对照 | 六个真实受理冻结各自版本；晚发布v3后历史v1 manifest字节SHA完全不变，明确v1/v2及无附件；四组安全比较 | 实际HTTP/CLI/生产网页/fixture scheduler；无真实容器附件安装。先前28102的真实Docker补验仍只属其原版本/任务 |
| 额度、维护、排空、就绪 | 全量 test_pause_two_http_processes_cli_drain_and_unready_old_key：两个HTTP进程、CLI→scheduler/fixture worker排空、旧键优先，停止/重启scheduler；生产网页额度、暂停/刷新/成员只读/恢复 | 本轮真实本机HTTP/CLI/scheduler/浏览器；坏heartbeat/birth/极大数值、旧limits兼容、同锁争用由合成fixture；不是生产迁移或多机文件锁证明 |
| 有效零分、缺评分、执行失败 | 最终六个安全报告中的0合法；全量 test_three_axes_report_scores_and_evidence_boundary三种参数均执行，failure分别null/missing_score/execution_failure，异常诊断不泄露 | 零分来自真实fixture worker；缺评分/执行异常是合成native-shaped结果经TestClient与生产报告投影。未新增实际模型失败调用 |
| 安全报告阻断与释放 | 最终对一个已完成fixture run合成audit=incomplete，实际CLI query显示resource=released/report=blocked，report退出1 | 审计破坏是合成，HTTP/CLI门槛实际；test_resource_cleanup_separate_audit_and_next_capacity另模拟cleanup异常，只有cleanup_blocked占容量 |
| 取消、重启、资源故障 | 全量实际进程fixture preparation cancel / scheduler restart no orphan、hard worker missing key，以及合成清理失败专项 | 全新fixture state与birth核对；未动真实资源，不代表Docker故障恢复 |
| 迁移、兼容、历史归属 | 全量legacy schema/limits/附件登记/旧幂等专项 | 完全合成fixture，未复制或试升级正式state；未知旧成员不猜身份 |

## 失败、修正与浏览器证据

首次新串联脚本（`research-integration` / `capture/research`）失败：Playwright“新建实验”同时匹配主导航与列表按钮，strict mode拒绝点击；原driver/browser脚本快照及stdout/stderr/exit保留。定位限定到“主导航”后 `research-second`成功；固定46a466的 `research-fixed`增补console、delta和精确teardown断言后成功；固定efbc359的 `research-complete`进一步完成报告与网页比较成功。没有产品缺陷修正、弱化旧断言或删除必要测试。新增脚本静态检查初见冗余global、缺check参数及宽泛cleanup异常，固定提交已修正；未把这类未运行捕获的格式检查倒称原始capture。

页面身份、非空/无overlay、真实交互、无pageerror/无非预期console error通过；唯一初始匿名 `/me`401是预期。手工查看最终桌面比较页和390共享实验截图，正文没有横向溢出；窄屏导航/列表横向容器采用原产品滚动行为，不声称每列始终可见。截图只保留本地 `/tmp/hh-final-integration-evidence/research-complete/capture/`，不入Git。其他浏览器引擎/视口、大规模历史性能、真实研究客户端agent决策与网络代理/HTTPS未验。

## 归档、安全与范围

[额度维护独立原件](../admission-independent-6db930/README.md)逐字SHA为 `6bc588bd00f7495c8f5f09e0782adb2114e745e76186caf3eda8c37fc80e7087`；原36 passed/1 opt-in skipped及单独网页1 passed限定范围不扩大。

当前目录实际索引为 `SHA256SUMS`；metadata记录构建包SHA和排除项。archive只白名单复制命令、输出、退出、请求/事件/结果及teardown，实际PAT匹配与本任务假master/PAT字节扫描无命中。排除全部截图、state、home、profile、cache、private、秘密原值和二进制发布包。完整fixture state仅留 `/tmp/hh-final-integration-evidence/` 供复核，禁止整包上传；完整目录不代表都可公开。源独立索引含排除的截图摘要，实际归档索引另建。没有全历史秘密扫描或真实state内容保全审计的声称。

## 发布、迁移和回退交接（未执行）

包元数据、frontend package及wheel都是 **0.1.0**，当前未选新发布tag也未擅自改版本。固定提交+包摘要可用于本轮候选审查；若正式发布需要区别既有0.1.0，应由Root先确定版本/tag，再按改动补构建/元数据验证。不要将本轮候选包替换成同名旧发布物或移动旧tag。末报告提交没有改变产品/static/锁或经过验证的QA脚本。

正式发布操作须另依授权及实时现场完成，以下是检查点，不是已经演练成功：

1. 核实时发布SHA/tag、安装依赖、static/文档与对应锁；核现役HTTP、canonical scheduler、worker、准备/下载子进程的argv/cwd/PID/birth及它们引用的state、外master。不要执行历史PID/reset命令，现存部署树不切分支。
2. 管理员暂停新受理，并从所有HTTP入口/代理/研究客户端/CLI及可能直连的本地写者停止新写。暂停不等于资源释放或无写者；旧键读取和已受理准备/队列仍可继续，其他配置/保留清理也可能写state。
3. 核全部preparing/queued/running/cancelling/cleanup_blocked，等待或按权限取消、处理资源收尾；审计异常另列证据风险，不偷换成容量阻塞。scheduler活动/就绪只证明当前观察，不证明Hub/模型可执行。处理未终态后停止HTTP及该state全部写者；按Web指南核专用空闲scheduler停止，实际确认worker与准备/清理/retention写者均停止，不能只看runs为空。
4. 在停写窗口保全最新完整state（配置、SQLite一致backup、冻结输入、版本库、所需证据及权限/引用清单），**原外master单独受保护保全**，保留service.json路径关联和主密钥模式。数据库用SQLite备份机制，不能单拷queue.sqlite丢WAL，更不能回放旧WAL/SHM；协调其余文件一致时点。备份不入Git。
5. 先在隔离复制的一致快照核启动事务迁移与兼容，再由授权发布流程启动固定发布目录。附件版本/操作及PAT两新增表、旧记录归属/幂等兼容按[附件说明](../../../guides/attachments.md)与[机器API](../../automation-api.md#迁移与回退)核查；本轮admission仅默认兼容缺成员字段及admission.json，不重写历史manifest/master。迁移失败应停服务调查，不继续新写、不重新init。
6. 发布后仍保暂停，核认证/凭据版本、历史受理/版本绑定、持久维护值、所有写者引用和安全report/资源轴；另核实际环境能力，再由管理员按授权恢复新受理。新旧实例不得同时对不兼容state写入。
7. 回退先阻断全部新写并停所有写者、保全最新一致state+原master。旧代码不懂PAT/固定类别幂等与admission暂停/就绪，不允许直接恢复旧受理写入口；优先兼容修复或限定前端回退。保留新表、维护文件、所有幂等/历史数据；不得删admission/keys隐式开放、换master、用旧state覆盖新增业务。恢复数据要另核最新业务差量与兼容，不能把代码回退称完整备份恢复。

未覆盖正式升级、生产schema迁移、完整备份恢复/灾备、多机/断电/fsync、大数据公平调度、SDK/MCP、真实Hub/Docker/Oracle/模型效果及金额预算。工程交付仅供Root审查和最终Checker选定范围。

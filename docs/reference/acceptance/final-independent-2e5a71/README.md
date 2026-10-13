# 最终独立验收：固定 2e5a71

[逐字报告](report.md)与[逐字 summary](summary.json)只证明 `2e5a71f2e7e47c6b19cca2d2219ae62384502097` 列明的最终整合和 0.2.0 包检查，不批准生产发布/升级。报告中当时 dev=6db930、master=945136 的观察保持原文；Root 后续正常快进 dev 到 2e5a71。当前交付状态另见[交付说明](../../../releases/0.2.0.md)。

## 两份索引

- [source-SHA256SUMS](source-SHA256SUMS)逐字复制源 `SHA256SUMS`：1230 项，包含源执行副本等未入库路径；不能在本目录整体运行 `sha256sum -c source-SHA256SUMS` 后把缺文件误认为源损坏。源清单 SHA256 为 `2fe82517d5c465021b2d19640c0c7b38fe177a07502d1333fad70442c9460f8f`。
- [SHA256SUMS](SHA256SUMS)重新索引本目录实际归档（自身除外）；可在本目录执行 `sha256sum -c SHA256SUMS`。它不是原 1230 项的改写。[archive-index.json](archive-index.json)列白名单源/归档路径、字节数、摘要及是否在源清单中，保存 300 份源文件。
- 原报告 SHA256：`10b5751c10c981c2c5b1de016c8e7a738f32d0ef14bbbd2957b033ee20b2b92b`；原 summary：`adcf9ef5e2d82f2258cfa8559a3e748c56ef43b4145ecf557a91a8477ffa3140`。每个归档源文件逐字比对，源清单覆盖者另核其摘要。行尾空白保留；产品/编辑文档 diff 检查与原 capture 空白观察分开登记。

## 原始证据入口

- [最终结果](live-certified/capture/results.json)、[39 条 CLI 原记录](live-certified/capture/cli-transcript.jsonl)、[浏览器 stdout](live-certified/capture/browser.stdout)：六份成功报告、四次比较，另一次 report 被合成安全门拒绝；六组无附件/v1/v2输入、下载、本人取消/重跑、维护与原键恢复。
- [维护排空结果](live-maintenance-drain-final3/capture/maintenance-drain-result.json)、[原浏览器 stdout](live-maintenance-drain-final3/capture/browser.stdout)、[执行命令](live-maintenance-drain-final3/capture/command.json)、[driver](maintenance-drain-driver.py)、[浏览器脚本](capture/maintenance-drain-followup.mjs)。第一项暂停期间完成、第二项本人取消/资源释放，新受理被拒绝。
- [最终进程端口审计](capture/final-process-port-audit.json)、[审计脚本](process-all-runs.py)、[完整整合脚本](independent-drive.py)、[包审计](capture/package-audit.json)、[分发完整性](capture/sdist-completeness.json)、[评分轴](capture/score-axis-fixtures-final.stdout)、[合成安全门](capture/certified-synthetic-safety-gates.stdout)。相关 command/stdout/stderr/exit 原件同目录保存。
- 首轮与后续失败在 `capture/` 的各轮命令/stdout/stderr/exit，以及 `live*/capture/` 浏览器原 stdout/stderr/exit；固定相关脚本同存。`restart-drain-recovery.py` 与失败记录保留失败方法，不表示独立 scheduler 重启恢复通过。脚本是历史证据，含专用临时路径；本次没有执行它们，不能直接覆盖原证据或部署 state。

只白名单读取文本，未把任何 state/home/profile/cache/private/master/PAT 值、截图、二进制包或重复 fixture/依赖副本转成归档。完整原证据仍在本地 `/tmp/hh-checker-independent-2e5a71-20261012`。文本中的隔离路径和源索引中未归档路径只作出处，不表示目录已公开。已扫描 `hh_pat_v1_`、常见 provider/GitHub token、私钥头和字面 Bearer 值，0 命中；脚本两种 `Fixture-only-…-password-2026` 是明确的测试口令，不是真实秘密。扫描只覆盖本次白名单文本，不证明所有秘密格式或历史清除。

未覆盖真实 Hub/Docker/Harbor/Oracle/模型、独立 scheduler 重启、额度编辑压力、生产迁移/备份恢复等，以原报告限制为准；以前额度独立和工程全量证据不倒称为最终 Checker 执行。源 Checker root `om_x100b63f9d96a0ca0c33c8d39570df04`、thread `omt_19a951b35e0f1b9f`、session `2bbd99c0-d3c8-4cdf-8cc6-52e1e79aa6ef`；Root 已收到原话题显式 completed100。本次只归档，不再发起 Checker。

# 研究 skill 独立前向行为验收

判定：**PASS（仅限下列固定候选与隔离 fixture 流程）**。

## 固定版本与隔离边界

- 候选：`0b05daf92c8478f990af46e6edf45a6b10abb60f`，与 `origin/feature/harbor-helper-research-skill` tip 一致；其 `src/harbor_helper` 与 `50b0dde` 相同。主仓 `master` 仍为 `9451363155674f138123c94c5e1ba51687139b36`。
- 使用新 detached worktree `/tmp/hh-checker-research-skill-20261012/worktree`；最终运行的独立 HOME、state、external master、fixture 服务和操作证据位于 `/tmp/hh-checker-research-skill-20261012-attempt5/`。master 和三份 fake PAT 都是 0600；profile 目录 0700，profile 文件 0600。启动通过 `env -i` 清除继承环境，HTTP 与故障代理仅绑定 loopback。
- 发布 skill 从候选复制到隔离目录 `skills/harbor-helper-research/` 后才操作；没有安装或修改全局配置。服务使用候选 Python 服务/API/队列、真实 CLI 和实际安全报告/比较路径；仅数据源、镜像身份和 worker 执行替换为本地 fixture adapter。没有访问 Hub、Docker、Harbor 或真实模型，也没有运行自动化 API 54、全量回归或计费实验。

## 实际操作与观察

1. 用只含 `read` 的成员 profile 执行 `status`、`schema`、`discover`、任务目录和附件目录读取。schema/discovery 显示 contract 1.0；唯一任务为 `fixture/research-task`，可用附件为同一附件身份的两个固定版本。read-only `allowed_operations` 不含 `submit`，因此先完成纯读取。
2. 研究范围获明确授权后，为隔离 fixture Oracle 切换为同一成员的 `read+execute` 凭证。固定条件为数据集 `fixture/research@1`、任务 `fixture/research-task`、Oracle、每组 1 attempt / concurrency 1 / wall 120 秒；冻结的环境构建倍率三组均为服务默认 10。三个写操作各自在发出前保全了 URL、成员、path、原键和正文，没有保存 PAT 到操作记录。
3. 第一组提交的 loopback 代理收到上游 **202** 后丢弃该响应，并向 CLI 返回 fixture **504**。CLI 以退出码 1 报通信失败并保留原幂等键。之后将显式 profile 换为该成员新签的凭证；`status` 确认成员 ID 不变，按原 `submit` 类别与原键 lookup 找回唯一的 `sub-f07dd6ac0a9a4f0c`，没有生成补偿键或重复提交。
4. v1、v2 分别作为新 submit，使用不同固定键。队列中最终恰有三条 submit 和三个 run；每个 run 均 succeeded、resource released、audit clean、report available，且各有 1 个有效 attempt。服务冻结输入确认任务、dataset、Oracle、1/1/120 一致，附件身份分别为 none、明确 v1、明确 v2。
5. 两次 compare 均 `comparable=true` 且 `config_changes={}`：no attachment→v1 得分 0.0→1.0（delta +1.0）；v1→v2 得分 1.0→0.0（delta -1.0）。所有得分来自同一个 `fixture-oracle-v1` 确定性 fixture verifier：它按固定任务标准检查附件中的响应值，结果只证明附件绑定、报告和比较流程，不代表真实模型效果。

| 组别 | submission / run | 附件 | 有效尝试评分 | resource / audit / report |
| --- | --- | --- | --- | --- |
| 无附件 | `sub-f07dd6ac0a9a4f0c` / `hh-99a2d5359f444cc2` | none | 1 / 1，0.0 | released / clean / available |
| v1 | `sub-1e62e214a7db4979` / `hh-414c63c9f4e84acf` | `av-d786cde771c744ad9cda5b89bd4d38e1` | 1 / 1，1.0 | released / clean / available |
| v2 | `sub-ed056b1ff09048ab` / `hh-1ea5ac73fe5a485a` | `av-a0f66465ed05445e8f8177e5ee9cb505` | 1 / 1，0.0 | released / clean / available |

## 收尾、证据和未覆盖

- API、fixture supervisor 和代理均已停止；其 loopback 端口不再监听，三个执行 PID 均不再匹配原 process birth。临时 state 保留在隔离目录供复核，没有指向或修改正式服务/state/master。
- 扫描最终 capture 未发现任何签发 PAT 原值。CLI 每条命令的 stdout/stderr 与退出码、原始 504 失败证据、逐次请求记录、事件、结果及服务/supervisor 日志保存在 `/tmp/hh-checker-research-skill-20261012-attempt5/capture/`。早期夹具搭建失败也留存于 `/tmp/hh-checker-research-skill-20261012*/capture/`；原因是 harness 一度未处理空 source target、候选路径和允许的附件目录结构，修正后从全新 HOME/state 重跑成功，不是候选产品代码失败。
- 本验收未覆盖真实 Harbor/Hub/模型、模型评分质量、Docker 清理、HTTPS/代理部署、浏览器 UI、超时真实网络断连（使用代理 504 丢响应模拟）、审计异常或资源清理阻塞。PASS 仅限固定候选的浏览器外 CLI 前向行为、fixture Oracle 比较、同成员更换凭证后的原键恢复及收尾。

代码版本/前提/原始输出分别见同目录 `study-plan.json`、`request-1.json` 至 `request-3.json`、`events.jsonl`、`results.json`、`cli-transcript.jsonl`、`driver.exit`、`http-service.log` 和 `supervisor.log`。

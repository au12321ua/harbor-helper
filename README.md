# harbor-helper

统一 Linux/Docker 机器上的 Harbor 实验 CLI。默认跑固定 CAD 数据集的 oracle；维护者配置自部署 vLLM 后，可选择 opencode。后台运行、共享容量、取消、输入快照、结果报告、对比和整体重跑均由同一个 state 管理。任务执行与评分仍由 Harbor 0.23.0 完成。

## 安装与维护者初始化

需要 Python 3.12–3.13、uv、Docker daemon 和 Compose 插件，以及 Harbor Hub 数据集访问权限。本项目固定 Harbor 0.23.0；不要使用 PATH 中其他版本的 harbor。

```bash
cd /path/to/harbor-helper
uv sync --locked
export HARBOR_HELPER_STATE=/path/to/team
.venv/bin/harbor-helper init --config configs/team.example.json
.venv/bin/harbor-helper doctor
```

`doctor` 检查 Python 内的 Harbor 版本、Docker、Compose、Hub metadata 权限、本机 runtime 镜像和模型配置；不会发模型请求。未配置模型会返回退出码 1 并明确提示 A10 未验证，但仍可提交默认 oracle。Hub 权限不足时用本项目 `.venv/bin/harbor auth login` 登录，联系数据集所有者授权。

配置文件为 `$HARBOR_HELPER_STATE/team.json`。只保存非秘密配置。示例 runtime 为本机已有 CAD runtime；其他机器需由维护者构建或载入符合 CAD 任务契约的 runtime，不能把本地 image ID 当成 registry digest。提交时解析 image ID、创建本项目的固定本地 alias，记录 ID。不会发布镜像/数据集或上传结果。

团队所有成员和所有 CLI 必须使用同一个绝对 state 路径及受信任的共享 Unix 账号；不要为每位成员单独初始化 state。调度器容量限制作用于一个 state 内 helper 管理的 Job，不包含其他项目或用户直接启动的 Harbor。首版不提供跨 Unix 用户权限隔离。不同 state 是显式独立安装，不能共同保证机器总容量。

配置默认最多 1 个活动 Job、1 个 Trial；`max_jobs` 和 `max_trials` 为团队总容量，每次提交的 `concurrency` 预留 Trial 槽位，确保最坏情况下的实际活动 Trial 不超上限。故障后未确认清理的 Job 继续占槽位，显示 `cleanup_blocked`。资源通过原生 Harbor override 设置 CPU/内存上限，磁盘/token/费用硬限额不支持。墙钟预算涵盖 worker 启动到执行完成，排队/提交前下载不计其中；尝试次数受团队上限控制，基础设施重试为 0。

## 成员操作

SSH 登录后只需配置维护者给的同一个 state（可以写入账号 shell profile）。以下命令均使用项目内 `.venv/bin/harbor-helper`；可由维护者在 PATH 设置同名入口。

```bash
export HARBOR_HELPER_STATE=/path/to/team
.venv/bin/harbor-helper submit
# 输出 run_id 后可以退出 SSH；运行不依赖当前连接。
.venv/bin/harbor-helper list
.venv/bin/harbor-helper status hh-替换为真实ID
.venv/bin/harbor-helper logs hh-替换为真实ID
.venv/bin/harbor-helper report hh-替换为真实ID
.venv/bin/harbor-helper rerun hh-替换为真实ID
.venv/bin/harbor-helper compare hh-基线ID hh-重跑ID
.venv/bin/harbor-helper cancel hh-替换为真实ID
```

`submit --task 'generation--box'` 可只跑一题；`--attempts`、`--concurrency`、`--wall-seconds` 在团队上限内覆盖默认值。`--dataset` 只接受显式数字 revision 或 sha256 digest，拒绝 latest。成功提交前实际解析并下载 Hub 任务，保存 agent 和 verifier 全部原始输入文件。提交失败不给一个假成功 run ID。

`cancel` 返回取消请求；最终 `cancelled` 才确认本次工作停止和限定本次 Compose project 的容器/网络/volume 清理。不会使用全局 prune。结果保留。worker 硬退出由调度器识别并清理，失败后提示整体 rerun；不恢复中途会话。调度器故障后 `recover`（或 status/list/新提交）启动唯一调度进程并协调旧 worker，不重复执行。PID 和 Linux 启动时间共同识别进程；flock 防多个调度器和同一次 worker 重复。

报告仅将无异常且含有限数字 reward 的 Trial 算有效，基础设施异常、缺失/损坏结果单列，不能当有效零分。低分本身不等于执行失败。对比要求相同的固定题目/评分来源、模型和采样/资源/版本条件；不兼容输出原因并返回退出码 2。bundle 可以不同并显示 digest 变化。逐任务 delta 为右减左，整体为同指标的任务均值；不完整实验不生成改进结论。

rerun 创建新 ID，复制原 run 的题目、评分输入和 bundle，保留有效配置与镜像 ID。验证快照完整性，拒绝缺失或被改过的内容；旧结果不覆盖。rerun 是整体重跑，不支持只重试失败 Trial。模型声明版本保留，实际 checkpoint 无法观察时记录 unknown；随机模型不保证逐字重现。

## Bundle

```text
candidate/
  skills/<skill-name>/SKILL.md
  sdk/                         # Python SDK 源码；运行时 PYTHONPATH 指向它
  config/opencode.json          # 非秘密 opencode 原生配置
  bootstrap.sh                 # 可选，agent 容器内执行安装/准备
```

```bash
.venv/bin/harbor-helper submit --bundle ./candidate
.venv/bin/harbor-helper submit --preset model --bundle ./candidate
```

提交时复制 bundle 并计算包含路径、文件内容及执行位的 SHA-256，源目录后续修改不影响排队/运行/rerun。拒绝符号链接与特殊文件。Harbor 原生 skills 注入技能，整个快照上传到 `/opt/harbor-helper-bundle`；bootstrap 在 agent 容器内以 root 执行，失败会成为 Trial 异常。SDK 可从该目录导入，bootstrap 可将 SDK 安装到环境；仅加入源码不代表任意 SDK 已自动 pip install。`bundle-setup.txt` 保存准备证据。oracle 同样可以执行 bootstrap 证明 payload 实际执行，解题及 verifier 仍走原生 oracle。opencode config 合并到 agent 真正使用的配置，仅允许维护者所选 vLLM provider，不能改模型 endpoint。不要放凭据、私钥或 .env 文件到 bundle。

## vLLM 模型配置（需要维护者提供）

将 `team.json` 的 `model: null` 改为以下非秘密对象：

```json
{
  "endpoint": "http://MAINTAINER_VLLM_HOST:8000/v1",
  "name": "DEPLOYED_MODEL_ID",
  "declared_version": "MAINTAINER_CHECKPOINT_REVISION",
  "credential_env": "VLLM_API_KEY",
  "opencode_version": "PINNED_OPENCODE_VERSION"
}
```

无认证 endpoint 可将 `credential_env` 设置为 null。opencode 版本必须固定，由 Harbor 在 agent 容器内安装。维护者只把必要凭据显式导出到当前 shell 的 `VLLM_API_KEY`；不要写到 argv、配置或 README。调度器仅继承白名单环境和这个明确的变量，不搜索相邻项目秘密，也不会选择付费 provider。凭据配置变更前等所有任务终止，执行 `stop`，重新在正确环境执行 `recover`。已有后台调度器不会因后续提交而取得新的 shell 环境。

```bash
.venv/bin/harbor-helper stop
# 由维护者安全设置 VLLM_API_KEY（不要将值写入命令历史）
.venv/bin/harbor-helper recover
.venv/bin/harbor-helper doctor
.venv/bin/harbor-helper submit --preset model --task generation--box
```

A10 必须以真实模型完成 task 与评分验证。无模型时默认 oracle 不代表模型通过。Harbor 原始证据保存在受保护 run 目录；框架使用环境占位符序列化敏感 env，helper 对 worker 输出和已完成文本证据做凭据脱敏。不能保证任意恶意 bundle/模型主动泄露凭据；团队需信任输入。

## 产物与验证

每次 run 位于 `$HARBOR_HELPER_STATE/runs/<run-id>/`，包含 `manifest.json`、固定 `tasks/`、可选 `bundle/`、有效原生 `job.json`、worker runtime/日志、原始 `harbor/` Trial 结果与 verifier/产物、`projects.json` 精确资源归属、`cleanup.json`、可重新生成的 `report.json`。helper 报告不读取 CAD 指标文件或重写评分器。

```bash
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
```

实现证据及当前未验证项见 `docs/implementation-evidence.md`。独立检查由 checker 维护 `docs/checker-report.md`。真实未参与搭建成员需自行完成提交、断开/重连、报告、候选对比及 rerun，A11 与机器测试分别记录。

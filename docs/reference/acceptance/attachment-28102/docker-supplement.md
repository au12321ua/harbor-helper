# 附件生命周期独立验收：Docker / Harbor / Oracle 增量补证

## 结论

本补充对固定候选 `28102da47acfae696cf8cce1e8f42dee057944a9` 的本地 Docker / Harbor / Oracle 小验证为 **PASS**。它补上原报告唯一明确缺失的真实任务容器执行证据；原报告 `report.md` 保持原样、原结论仍为 **PARTIAL**。这不是下一阶段整体验收，也不证明 Hub 下载、生产管理员注册、研究 agent/LLM 效果或附件带来能力提升。

## 固定任务、预算和来源边界

- detached worktree `/tmp/hh-attachment-docker-check-28102` 的 `HEAD` 为固定候选，worktree 与主树 Git 状态均 clean。未改产品或静态文件。
- 运行前逐项核仓库跟踪任务文件：`task.toml`、`instruction.md`、`environment/Dockerfile`、`solution/solve.sh`、`tests/test.sh`；摘要分别为 `1ee925e349d5e0c2adc2a833a6b0e40386e3246a0286524d83b641f9dba39133`、`54d03f1b84798ed9da48e871bd8c6527e3e82f6b86579fb2d83c880567a23749`、`b2031f8eb7ddedb614bf2a6469db3ababa691a1cc22fe4e5e1d1f354c2009c31`、`c7737ccbf4fdc7c159b89a9686f4a1c8c9c30a02c5440be02e6986bea1bbe6c8`、`5e989d46db2e377ce5cfae974db1b8db45bbd5103304356e34674d6e305e97c2`。
- 来源是候选已跟踪的 `au12321ua/harbor-helper-switch-answer` 固定任务快照。临时 harness 仅在 Harbor Helper `source_call` 的 Hub 获取边界复制该目录；不请求 Hub、不传 Hub key。三份 run manifest 记录相同任务快照摘要 `sha256:b0cf0d2a2e24dbaf487a2a733a8321c35091968a8f20dfe1c2954a353e770711`，并带有 `_fixture_boundary: local candidate Git task copy; not Hub-verified`。
- 预算登记在 `evidence/budget-and-ownership.json`：agent `oracle`，无附件/v1/v2 各 1 attempt、并发 1、`wall_seconds=120`，最多 360 run-seconds；无金额模型请求。实际三次 worker 时长约 25.2 / 23.3 / 33.3 秒。
- 本地保护清单所列 Python 基础镜像在执行前核为 `sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a`，标签含 `python:3.12-slim`；执行后该镜像仍在。没有显式 pull、镜像删除或 prune。Harbor 0.23.0 使用本地 Docker/Compose 和作者 Dockerfile；任务网络模式为 `no-network`，作者 build/agent/verifier 时限分别 30 秒。候选有效配置的 build/start wait multiplier 是 10，因此本次冻结的 start wait 上限为 300 秒；这只是候选当前配置的观察值，不是任务作者的 30 秒 build 时限或新增业务限制。

## 真实执行结果

三次均经过候选 `Application.accept`、真实 attachment create/publish 与 version binding、`prepare_one`、Harbor 0.23.0 `Job/Trial`、Docker Compose build/up/down、容器内 Oracle、原作者 verifier、候选评分/报告、credential audit 和候选清理。没有 mock 容器、安装、评分或清理。

| 条件 | run | 冻结附件 | bundle digest | 状态 / audit | 有效评分 |
|---|---|---|---|---|---|
| 无附件 | `hh-9635cf287a194d7b` | none | none | succeeded / clean | reward=1.0 |
| v1 | `hh-ec95e12cae0a4af4` | `av-41fc61b121ed4f159c1e25557fb18c97` | `sha256:f22230fe9dade4a53d499420ab104c9206d0e538263a7094ef9d1e27a74191de` | succeeded / clean | reward=1.0 |
| v2 | `hh-7194b7fa9f7d42dd` | `av-fddfc36910734d46bd6a03ae480fd5ae` | `sha256:572066048b66a675e9b98a417d580b98298a61a89f54e3516a9d47d9e4d7749b` | succeeded / clean | reward=1.0 |

实际容器观察分别记录主环境 image ID `sha256:9d6eba3f6a63056a0455eb0ea98da7dd30a83f767ff09c35b67c8b9ec7443f94`、`sha256:318eaa9a35ef82065be8eb683007a2e4719ef9c10d41afb7e8566c2d49ccb2cb`、`sha256:83ee0234666cc31fb7c6017a056786a52bc2260231a604712d91e3152d1bedaa`，共享 egress-control sidecar image ID 均为 `sha256:9e32b92c35d3b9a138479d123dc5d0e76daccf8d633824291b925f9399748430`。

v1/v2 都使用仅含 `bootstrap.sh` 的无凭据观察附件。候选 agent 在 `/opt/harbor-helper-bundle` 输出目录内容、版本标记及其中 bootstrap 文件 SHA-256：v1 为 `2921b6a9fb6cccd2d80558e0f0ebe96ac5c142bfe4703810573b256c8355b93a`，v2 为 `6096d5606fb1f39e898e7e6878530797f0a69f7241faa2b3a8add5b1e77ee8e4`；分别与两个冻结 run 的 bundle 文件逐字摘要相同。这证明所选版本字节进入 agent 环境并执行 bootstrap。Oracle 固定答案与评分器未改，三组均 reward=1，不能把这个安装观察解释为能力变化。

候选 `compare` 对无附件/v1、无附件/v2、v1/v2 均判 comparable，配置差异和拒绝理由为空；`bundle_change` 显示对应 `null` 与 v1/v2 digest，三项 reward delta 均为 `0.0`。这与附件输入谱系相符，不构成效果提升证据。

## 清理与网络观察

- 每个 run 的 `cleanup.json` 都记录 `confirmed=true`、精确 Compose project 和零匿名卷。随后按这些精确 project label 分别查询 Docker containers/networks/volumes，均为空；执行后全局容器列表也为空。没有停止或删除其他容器、网络、卷。
- 未启动 HTTP 服务或 supervisor daemon；三个 worker 均终止。隔离 state、临时假账户和外置测试 master 留在 `/tmp/hh-attachment-docker` 供本报告复核；该目录不是正式 state。派生镜像/build cache 保留，未清共享 cache；受保护 Python 镜像身份仍可 inspect。
- worker 日志显示 LiteLLM 依赖曾尝试获取公开静态 `model_prices_and_context_window.json`，请求超时后回退本地数据。这不是 Hub 或模型 endpoint 请求，没有模型配置/凭据、prompt 或付费模型调用；仍作为观察到的非任务元数据网络尝试保留在 `evidence/dependency-network-note.log`，不声称此次进程完全无任何外网尝试。

## 证据与复现

完整队列/run/report/Trial、冻结快照、`bundle-setup.txt`、compose phases 与清理证据保留在 `/tmp/hh-attachment-docker/state/`。精简可审阅索引在 `/tmp/hh-attachment-docker/evidence/`：

- `budget-and-ownership.json`：任务、测试预算和资源归属登记。
- `preflight.json`、`post-cleanup.json`：候选/输入摘要、镜像身份及精确资源清理前后观察。
- `oracle-runs.json`、`comparison.json`：三次结果、冻结版本、安装摘要及候选比较输出。
- `oracle-harness.stdout.json`、`oracle-harness.stderr.log`、`dependency-network-note.log`：直接运行结果及依赖网络告警。
- `run_oracle_extension.py`：一次性 harness。唯一 seam 是替换 `service.sources.source_call` 以复制仓库固定 task；其余受理、附件冻结、Harbor/Docker、Oracle/verifier、报告和清理均调用候选固定代码。

复现命令（候选 worktree 与临时目录已保留）：

```bash
timeout 390s env -i \
  PATH="/tmp/hh-attachment-docker-check-28102/.venv/bin:/usr/bin:/bin" \
  HOME=/tmp/hh-attachment-docker/home \
  XDG_CONFIG_HOME=/tmp/hh-attachment-docker/home/.config \
  TMPDIR=/tmp/hh-attachment-docker LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  PYTHONPATH=/tmp/hh-attachment-docker-check-28102/src \
  /tmp/hh-attachment-docker-check-28102/.venv/bin/python \
  /tmp/hh-attachment-docker/run_oracle_extension.py
```

未由此补证的范围：Hub 下载/权限和生产数据集登记；自动化签发、三轴、额度维护、skill；研究 agent/LLM 效果；先前报告列明的其它未覆盖事项。原 PARTIAL 结论不改写。

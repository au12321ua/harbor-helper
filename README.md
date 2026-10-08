# harbor-helper

统一 Linux/Docker 机器上的 Harbor 实验 CLI：提交模型任务、后台排队、查看评分、比较候选与整体重跑。输入、运行环境与结果按 run 固定，任务执行和评分使用 Harbor 0.23.0。

## 在已部署团队环境运行模型

使用维护者提供的项目目录、统一 state 和受保护的 key 文件。已部署成员直接使用这些入口，无需 `init`。下面示例使用团队项目目录；key 文件路径须替换为维护者给定的绝对路径。

```bash
cd /path/to/harbor-helper
export HARBOR_HELPER_STATE=/path/to/team
export HARBOR_HELPER_KEY_FILE=/absolute/path/to/protected/model-key

hh_model() {
  : "${HARBOR_HELPER_STATE:?请设置团队 state 的绝对路径}"
  : "${HARBOR_HELPER_KEY_FILE:?请设置 key 文件的绝对路径}"
  .venv/bin/python scripts/with_model_key.py \
    --key-file "$HARBOR_HELPER_KEY_FILE" -- \
    --state "$HARBOR_HELPER_STATE" "$@"
}
```

`HARBOR_HELPER_KEY_FILE` 保存**文件路径**，文件内才是 key **值**；文件须由当前账号拥有、权限 `0600`、为普通文件且不是符号链接。不要将 key 值填入环境变量示例、命令或 `team.json`。准备方法见[配置指南](docs/configuration.md#key-文件准备)。

SSH 重连后重新执行上面的环境变量与函数定义，或将其保存到受信任的 shell profile；执行时保持在项目目录。`hh_model` 让新启动的调度器继承凭据。

```bash
hh_model doctor --preset model
```

`doctor` 检查工具、数据集访问和非秘密配置，不发送模型请求，也不证明 key、认证或 provider 实际可用。

首次模型使用、更新 key 或旧调度器由普通 CLI 启动时，先按[刷新步骤](docs/configuration.md#刷新调度器凭据)等待全部任务终止、停止旧实例并确认其退出。`recover` 不会更新已经运行的调度器的环境。

维护者完成一次配置/刷新后，日常提交无需每次 stop/recover。在已有模型运行授权范围内显式提交一题：

```bash
hh_model submit --preset model --task generation--box \
  --attempts 1 --concurrency 1 --wall-seconds 1200
```

记下返回的 `run_id`。任务在后台运行，退出 SSH 后继续执行。裸 `submit` 使用默认 oracle；模型运行须明确写 `--preset model`。

## 重连、状态与报告

重连后恢复上面的 `hh_model` 定义，再将示例 ID 替换为真实 ID：

```bash
hh_model list
hh_model status hh-替换为真实ID
```

任务进入终态后查看评分：

```bash
hh_model report hh-替换为真实ID
```

`list`、`status`、`recover`、`submit`、`rerun` 与活动任务的 `cancel` 都可能启动调度器，模型操作统一经 `hh_model`。

报告保留原始评分与异常。低分本身有效，缺失结果或执行异常不能当作有效零分。原始日志和产物在统一 state 的 `runs/<run-id>/`；读取或转发前按[操作指南](docs/operations.md#日志与证据交接)完成停写与扫描。

查看报告时关注：

| 字段 | 含义 |
| --- | --- |
| `status` | 排队、运行或最终成功/失败/取消状态 |
| `complete` | 是否取得全部预期的有效评分 |
| `valid_attempts` | 有效尝试数；缺失或异常另列 |

```bash
hh_model compare hh-基线ID hh-候选ID
```

`compare` 要求题目、模型、运行环境等条件一致，不可比时返回原因。候选 bundle 用法见[详细操作](docs/operations.md#候选-bundle)。

需要重跑时，先确认预算与授权：`rerun` 会新建实验并完整执行，模型 rerun 会再次发请求。

```bash
hh_model rerun hh-替换为真实ID
```

需要取消时单独执行；这是取消请求，终态 `cancelled` 才确认任务停止和本次资源清理：

```bash
hh_model cancel hh-替换为真实ID
```

墙钟预算不限制 token 或费用；实际费用未知时保留 unknown，工具报告的 cost=0 不代表免费。

## 环境与首次部署

需要 Python 3.12–3.13、uv、Docker daemon、Compose 插件、Harbor Hub 数据集访问权限，以及维护者配置好的兼容 runtime。始终使用项目 `.venv` 中固定的 Harbor 0.23.0。

新部署由维护者完成安装、一次初始化、模型与镜像配置；完整步骤见[配置指南](docs/configuration.md)。所有成员使用同一个绝对 state 路径和受信任的共享 Unix 账号。

容量限制覆盖该 state 内 helper 管理的 Job。`cleanup_blocked` 表示尚未确认收尾，继续占容量；处理方法见[故障处理](docs/operations.md#故障处理)。

## Oracle 自检

需要无模型自检时，显式选择 oracle；这一步不加载 key、不请求模型：

```bash
.venv/bin/harbor-helper --state "$HARBOR_HELPER_STATE" doctor
.venv/bin/harbor-helper --state "$HARBOR_HELPER_STATE" submit \
  --agent oracle --task generation--box --attempts 1 --concurrency 1
```

如果普通 CLI 新启动了 oracle 调度器，待任务终止后按配置指南刷新，再提交模型。自检评分验证运行环境；模型工具行为与产物须通过实际模型任务核对。

## 文档导航

- [配置指南](docs/configuration.md)：首次部署、团队配置、模型与 key 文件、调度器刷新。
- [操作指南](docs/operations.md)：bundle、镜像维护、报告比较、恢复、扫描与故障处理。
- [成员验收](docs/member-acceptance.md)：真人提交、断开重连、对比与 rerun。
- [设计与范围](docs/v0-design.md)、[验收条件](docs/acceptance.md)。
- 实现证据、独立检查报告：固定版本、来源、耗时和已知限制。
- [CLI 源码](src/harbor_helper/cli.py)、[配置示例](configs/team.example.json)。

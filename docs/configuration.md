# 环境、团队与模型配置

已部署成员从 [README 的模型入口](../README.md#在已部署团队环境运行模型)开始，直接使用维护者给定的统一 state，不重复初始化。本文的安装和配置步骤由维护者在空闲窗口执行。

## 环境与一次初始化

需要 Linux、Python 3.12–3.13、uv、Docker daemon 和 Compose 插件，以及 Harbor Hub 数据集权限。使用项目 `.venv` 的 Harbor 0.23.0，不使用系统中其他版本。

```bash
cd /path/to/harbor-helper
uv sync --locked
export HARBOR_HELPER_STATE=/path/to/team
# 仅新部署、team.json 尚不存在时执行一次。
.venv/bin/harbor-helper --state "$HARBOR_HELPER_STATE" init \
  --config configs/team.example.json
```

`init` 不覆盖已有配置。已部署环境应检查现有 `$HARBOR_HELPER_STATE/team.json`，由维护者修改非秘密字段。所有 CLI 使用同一绝对 state；不同 state 是独立安装，不能共同保证整机容量。共享 Unix 账号须受信任，首版没有跨用户权限隔离。

先构建或载入兼容 runtime，再诊断环境（[镜像维护](operations.md#维护构建与复用)）：

```bash
.venv/bin/harbor-helper --state "$HARBOR_HELPER_STATE" doctor
```

Hub 权限不足时使用 `.venv/bin/harbor auth login`，并向数据集所有者申请权限。`doctor` 可访问 Hub metadata、检查 Docker/镜像，但不发模型请求。

## 团队非秘密配置

`team.json` 只保存模型名称、endpoint、固定工具版本、runtime 与容量设置，不保存 key 值。

| 字段 | 用法 |
| --- | --- |
| `dataset` | 固定数字 revision 或 sha256 digest，拒绝 latest |
| `runtime_image` | 维护者已验证的本机兼容镜像；预装 OpenCode 可避免每次重复安装 |
| `runtime_image_env` | 接收固定 image alias 的原生环境变量，CAD 使用 agent/verifier 两种角色 |
| `max_jobs` / `max_trials` | 统一 state 总 Job/Trial 容量，每次 concurrency 预留 Trial 槽位 |
| `max_attempts` / `max_wall_seconds` | 成员提交上限；墙钟从 worker 开始计算，排队和提交前下载不计入 |
| `max_cpus_per_trial` / `max_memory_mb_per_trial` | 原生 Harbor CPU/内存覆盖值 |
| `presets.default` | 保持 oracle；不要静默将默认提交改为收费模型 |
| `presets.model` | agent=opencode；成员仍显式 `submit --preset model` |
| `model` | 维护者明确选择并授权的兼容服务配置 |

镜像变更只影响新 submit。旧 run/rerun 使用冻结镜像与输入；新旧镜像可能不可比，见[报告与比较](operations.md#报告比较与整体重跑)。基础设施重试固定为 0；磁盘/token/费用硬限额不支持。

## 模型配置

将现有 `model: null` 换成以下对象；endpoint 与模型名称用维护者选定值替换：

```json
{
  "endpoint": "https://MAINTAINER_SELECTED_HOST/v1",
  "name": "SERVED_MODEL_ID",
  "declared_version": "unknown",
  "credential_env": "VLLM_API_KEY",
  "opencode_version": "1.18.35"
}
```

服务须支持 OpenCode 所需流式响应和工具调用，可以托管或自部署。内部 provider 名 `vllm` 和变量 `VLLM_API_KEY` 是兼容标识，不要求服务运行 vLLM；使用 `@ai-sdk/openai-compatible`。未观测实际 checkpoint 时记录 unknown。

OpenCode 版本固定。实际 install 核对已安装版本，匹配则复用；缺失或不匹配时安装指定版本，再核对，不符直接失败。`--model` 只能选择同一 endpoint 的 served model ID；改选模型时声明版本置为 unknown，不改变 endpoint。

无认证服务可将 `credential_env` 设为 null，并使用普通 CLI 的显式 `--preset model`。以下文件包装方法适用于需要认证的团队服务。

## Key 文件准备

先设置维护者指定的**文件路径**，不要在此变量中放 key 值：

```bash
export HARBOR_HELPER_KEY_FILE=/absolute/path/to/protected/model-key
```

已有受保护文件直接复用，不另建密钥或复制到其它配置。文件须由执行账号拥有、权限 `0600`，内容为一个非空且无空白的 key 值，可带结尾换行；普通文件、非符号链接。只查看元信息：

```bash
test ! -L "$HARBOR_HELPER_KEY_FILE" && \
  stat -c '%a %U %F' -- "$HARBOR_HELPER_KEY_FILE"
```

若维护者需要首次保存已取得的 key，可在交互终端隐藏输入；下面不覆盖已有文件、不将值放进 shell 历史或 argv。目录和路径先由维护者确认，禁止把真实值发到消息或证据中。

```bash
.venv/bin/python - <<'PY'
import getpass
import os
import warnings
from pathlib import Path

warnings.simplefilter("error", getpass.GetPassWarning)  # 无法隐藏输入时直接失败
os.umask(0o077)
path = Path(os.environ["HARBOR_HELPER_KEY_FILE"]).expanduser()
if not path.is_absolute():
    raise SystemExit("请使用绝对文件路径")
path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
key = getpass.getpass("API key（隐藏输入）: ").strip()
if not key or any(c.isspace() or ord(c) < 32 for c in key):
    raise SystemExit("需要一个非空、无空白的 key 值")
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "w") as output:
    output.write(key + "\n")
PY
```

已有文件权限不符时，由其拥有者在确认文件身份后设为 `0600`。不使用 `cat`、shell `export VLLM_API_KEY=<值>`、环境文件、bundle 或 `team.json` 保存/转发 key。启动器仅在进程内读取，运行时转给受控子进程；Docker argv 只传环境变量名。

## 每次登录的模型包装

在项目目录中，恢复团队 state、key 文件路径和函数；可将这一段加入受信任的 shell profile，重连后也必须有效：

```bash
export HARBOR_HELPER_STATE=/path/to/team
export HARBOR_HELPER_KEY_FILE=/absolute/path/to/protected/model-key
hh_model() {
  : "${HARBOR_HELPER_STATE:?请设置团队 state 的绝对路径}"
  : "${HARBOR_HELPER_KEY_FILE:?请设置 key 文件的绝对路径}"
  .venv/bin/python scripts/with_model_key.py \
    --key-file "$HARBOR_HELPER_KEY_FILE" -- \
    --state "$HARBOR_HELPER_STATE" "$@"
}
hh_model doctor --preset model
```

`doctor` 即使成功也不验证 key/provider 认证或工具调用；只能在已授权真实任务中确认。`hh_model` 加载的是显式文件内容，路径本身不是 key 值。

## 刷新调度器凭据

已有 scheduler 的环境不会被后续 `recover` 或 submit 更新。首次模型使用、更新 key、服务配置，或普通 CLI 启动过无凭据 scheduler 时，应刷新。先通过 `hh_model list/status` 等待所有任务进入 succeeded/failed/cancelled；queued/running/cancelling/cleanup_blocked 都不能直接 `stop`。维护者协调空闲窗口，其他成员暂停可启动调度器的命令。

维护者先定义下面的函数。`hh_stop_idle` 调用现有 `stop`，使用 `scheduler.json` 的 PID 和 Linux 启动标识 `birth` 确认旧实例退出；轮询检查退出条件，超时或出现其它活动 scheduler 则失败，不继续 recover。`stop` 的返回只代表发出停止请求。

```bash
hh_stop_idle() {
  .venv/bin/python - "$HARBOR_HELPER_STATE" <<'PY' || return
import subprocess
import sys
import time
from pathlib import Path
from harbor_helper.storage import read_json
from harbor_helper.worker import process_birth

state = Path(sys.argv[1])
identity_file = state / "scheduler.json"
old = read_json(identity_file) if identity_file.exists() else None
subprocess.run(
    [sys.executable, "-m", "harbor_helper.cli", "--state", str(state), "stop"],
    check=True,
)
deadline = time.monotonic() + 10
while old and process_birth(old["pid"]) == old["birth"]:
    if time.monotonic() >= deadline:
        raise SystemExit("旧 scheduler 尚未退出；不要 recover，请维护者检查")
    time.sleep(0.1)
current = read_json(identity_file) if identity_file.exists() else None
if current and process_birth(current["pid"]) == current["birth"]:
    raise SystemExit("检测到活动 scheduler；协调空闲窗口后重新刷新")
print("旧 scheduler 已停止")
PY
}
hh_refresh_model() {
  hh_stop_idle && hh_model recover
}
```

需要刷新时执行一次；日常提交无需重复 stop/recover：

```bash
hh_refresh_model
```

刷新期间不要再运行 `list/status/submit/recover`，以免另起实例。确认退出后才由 `hh_model recover` 启动新实例；之后模型的 recover/submit/status/list/rerun/cancel 均用 `hh_model`。普通 oracle 不加载该文件；普通 CLI 若新起调度器，下一次模型使用前重新刷新。需要仅停止以扫描证据时，只执行 `hh_stop_idle`。

遇到 cleanup_blocked 时，先按[故障处理](operations.md#故障处理)定位；不要把状态改成终态来绕过 stop。使用现有 key 的文件启动器恢复已死调度器可执行收尾，不会重执行模型。

## 配置验证与后续

环境/模型配置诊断不代替真实评分。提交与预算示例见 [README](../README.md)，bundle、镜像来源、报告和安全扫描见[操作指南](operations.md)。设计、验收与独立证据见[文档导航](../README.md#文档导航)。

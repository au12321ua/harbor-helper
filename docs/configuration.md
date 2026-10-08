# 环境、团队与模型配置

已部署成员从 [README](../README.md#一次登录)开始，使用维护者给定的统一 state，不重复初始化。安装与非秘密配置由维护者在空闲窗口完成。

## 环境与一次初始化

需要 Linux、Python 3.12–3.13、uv、Docker daemon/Compose 插件、Harbor Hub 数据集权限。使用项目固定 Harbor 0.23.0。

```bash
uv sync --locked
# 仅新部署、team.json 尚不存在时执行。
.venv/bin/harbor-helper --state /absolute/path/to/team init \
  --config configs/team.example.json
.venv/bin/harbor-helper doctor
```

init 不覆盖已有配置，并将该绝对 state 记录为本账号选中的 team。已部署环境直接登录已有 team；登录也记录选择。重连无需 shell 函数或 export。解析顺序：显式 `--state` > `HARBOR_HELPER_STATE` > 本账号已选 team > 已有项目 `.state/team` 自动发现 > 系统默认 `~/.local/state/harbor-helper`。自动发现的 state 在登录输入前显示。

所有成员使用同一绝对 state 和受信任的 Unix 账号；不同 state 不能共同保证整机容量，本版没有跨账号身份/权限平台。Hub 权限不足时使用 `.venv/bin/harbor auth login` 并申请数据集权限；它与 helper 的模型登录是两个独立入口。

## 团队非秘密配置

team.json 只保存服务、工具、镜像与容量字段，禁止 key 值。初始化后的变更由维护者明确编辑，不由 auth login 静默修改。

| 字段 | 用法 |
| --- | --- |
| dataset | 固定数字 revision 或 sha256 digest，拒绝 latest |
| runtime_image | 已验证的本机兼容镜像；固定预装 OpenCode 可避免重复安装 |
| runtime_image_env | 原生 agent/verifier 接收固定 image alias 的变量 |
| max_jobs / max_trials | 同一 state 的总 Job/Trial 容量 |
| max_attempts / max_wall_seconds | 提交上限；墙钟从 worker 开始，排队/提交下载不计入 |
| max_cpus_per_trial / max_memory_mb_per_trial | Harbor 原生资源覆盖值 |
| presets.default / presets.model | 保留共享原值；CLI 裸 submit 选择 model，oracle 须显式选择 |
| model | 维护者选定的兼容服务，见下方 |

```json
{
  "endpoint": "https://MAINTAINER_SELECTED_HOST/v1",
  "name": "SERVED_MODEL_ID",
  "declared_version": "unknown",
  "credential_env": "VLLM_API_KEY",
  "opencode_version": "1.18.35"
}
```

将 model:null 替换为该对象，并使用已选服务的真实非秘密名称。服务须支持 OpenCode 流式响应/工具调用；内部 vllm 与 VLLM_API_KEY 是兼容标识，不要求服务运行 vLLM，使用 @ai-sdk/openai-compatible。无认证服务可设 credential_env:null，仍需一次本地登录以绑定服务与 TTL，不输入 key。

OpenCode 实际 install 核对版本，匹配复用；缺失或不匹配安装固定版本并再次核对。`submit --model` 只选择同一 endpoint 的 served model，改选后 declared_version=unknown；不可观测 checkpoint 仍 unknown。

切镜像只影响新 submit，旧 run/rerun 保留固定输入和环境身份。维护构建与成员提交耗时分开，镜像来源验证见[操作指南](operations.md#维护构建与复用)。基础设施 retry=0；磁盘/token/费用硬上限不支持。

## Key 输入与文件引用

交互终端由产品隐藏输入，不需要准备文件或内嵌 Python：

```bash
.venv/bin/harbor-helper --state /absolute/path/to/team auth login --ttl 8h
```

输入前显示 state、endpoint、model。隐藏输入不可用时失败，不能回退可见输入。值缓存于当前账号 `~/.config/harbor-helper/auth/` 的 team 私有区；目录 0700、文件 0600，核对所有者/类型/链接，与实验 state 和报告隔离。本地权限保护不承诺加密，也不防同账号进程。

已经指定的受保护文件只引用，不复制值：

```bash
.venv/bin/harbor-helper --state /absolute/path/to/team auth login \
  --key-file /absolute/path/to/protected/model-key --ttl 8h
stat -c '%a %U %F' -- /absolute/path/to/protected/model-key
```

参数是文件路径；文件内才是 key 值，文件不得位于实验 state 内。要求当前账号拥有、0600、普通文件、非符号链接、一个非空且无空白的值（可有结尾换行）。权限修正由拥有者确认文件身份后执行。不要 cat 文件、把 key 放进 argv/环境文件/team.json/bundle，或发到消息。

引用记录保存路径与身份指纹；期间删除、改权限或换值可能使旧 run 无法恢复审计。请保留关联 run 的原文件；新 key 用另一文件，并在全部任务终态后重新登录。

## 登录与调度器刷新

```bash
.venv/bin/harbor-helper auth status
.venv/bin/harbor-helper auth logout
```

默认 TTL8h，可用正秒数或 s/m/h/d，如 --ttl 30m。登录只保存本地使用授权，不发 provider 探测，authentication_verified=false。doctor 也不证明 key/provider 可用。

login 内部协调空闲调度器：以 PID+birth 验证旧身份，发送停止请求，等待旧实例确实退出后恢复；stop 超时则诊断失败，不假设 sleep 后已退出。存在任意未终态 Job（含 queued/cleanup_blocked）时，拒绝轮换/logout，保留原会话并提示等待或取消。

日常 submit/list/status/cancel/recover/rerun 自动加载当前授权与审计来源，并内部脱敏，无需手动 stop/recover 刷新。TTL 在提交及真实出队检查；旧 scheduler 环境和历史 key 不能启动新模型 worker。过期排队任务明确 failed/未执行；已启动任务可继续执行、取消和收尾。过期不妨碍安全状态查询。

logout 撤销当前新执行授权，不删除已使用的历史审计材料；TTL8h 同样限制新执行，**不是审计材料删除期限**。关联 run/日志仍保留时，其来源留对应 team 私有区，仅用于脱敏和 scan；未使用的旧会话会清除。外部 key 始终仅引用。删除历史来源会使相关扫描不完整，不能维持全 clean 承诺；本版没有通用 purge/密钥服务。

无关旧来源缺失不影响新 run 执行/收尾，但对应原始日志拒读，全state scan 返回 audit incomplete/clean=false。安全摘要仍可看。恢复与证据操作见[操作指南](operations.md#故障处理)。

## 配置验证与兼容维护

普通 submit 默认模型且缺登录即失败，无凭据不回退 oracle；自检明确 `submit --agent oracle`，也支持 `--preset oracle`。旧 team.json 的 default 不改，旧 manifest/rerun 的有效配置不改。

旧 scripts/with_model_key.py 保留给维护者处理原生登录引入前的历史审计来源，不再是新模型提交主路径，不能代替 native auth 的 TTL。自动化需显式 --json；默认终端摘要，logs 默认可读字符串、--json 时为合法 JSON 字符串。更多操作见 [README](../README.md) 与[操作指南](operations.md)。

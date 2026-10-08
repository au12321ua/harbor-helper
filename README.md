# harbor-helper

统一 Linux/Docker 机器上的 Harbor 实验 CLI：模型任务后台排队、评分报告、候选比较与整体重跑。每次实验冻结输入和运行环境，执行与评分使用 Harbor 0.23.0。

## 安装与环境

需要 Linux、Python 3.12–3.13、uv、Docker daemon/Compose 插件、Harbor Hub 数据集权限，以及维护者已配置的兼容 runtime 和模型服务。

```bash
uv sync --locked
```

以下命令使用项目 `.venv/bin/harbor-helper`。维护者新部署按[配置指南](docs/configuration.md#环境与一次初始化)初始化一次；已部署成员直接使用统一 state，**不重复 init**。

## 一次登录

已有项目的 `.state/team` 可自动发现。首次明确选择维护者提供的团队目录并登录；命令在输入前显示 state、endpoint 和模型：

```bash
.venv/bin/harbor-helper --state /absolute/path/to/team auth login
```

key 值由隐藏输入读取，默认本地执行授权 8 小时。已有受保护文件可直接引用；下面参数是**文件路径**，不是 key 值：

```bash
.venv/bin/harbor-helper --state /absolute/path/to/team auth login \
  --key-file /absolute/path/to/protected/model-key --ttl 8h
```

文件须由当前账号拥有、权限 `0600`，为普通文件且不是符号链接；产品不复制引用文件的值。不要把 key 放入命令、消息、team.json 或 bundle。交互输入会保存于账号私有区，目录 `0700`、文件 `0600`。

成功登录记住团队目录，SSH 重连后直接运行命令，无需 export、函数或手动刷新调度器。登录仅保存本地授权，不请求 provider、不证明认证可用。配置与自动刷新边界见[配置指南](docs/configuration.md#登录与调度器刷新)。

```bash
.venv/bin/harbor-helper auth status
.venv/bin/harbor-helper doctor --preset model
```

doctor 检查依赖、镜像、Hub 访问和非秘密配置，不发送模型请求，也不验证 key/provider。

## 提交模型任务

普通 `submit` **默认 model**，包括共享配置的旧 default=oracle 情况；缺模型配置或有效登录时，在下载任务、创建 run、启动 worker 前失败，不回退 oracle。下例选择一题、一次尝试、一个并发、1200 秒墙钟预算：

```bash
.venv/bin/harbor-helper submit --task generation--box \
  --attempts 1 --concurrency 1 --wall-seconds 1200
```

提交返回 run ID，后台任务在退出 SSH 后继续。登录 TTL 在实际出队时再次校验：过期排队任务明确失败且不启动模型；已运行任务继续执行与审计收尾。

团队配置中的 dataset 是默认值；`--dataset` 可为本次实验切换到其他 Hub 数据集，不修改默认值。选择数字 revision 或 sha256 digest，每次实验和 rerun 固定所选版本。例如用单题测试集做无模型自检：

```bash
.venv/bin/harbor-helper submit --dataset au12321ua/harbor-helper-switch-smoke@1 --agent oracle
```

省略 `--agent oracle` 即按正常模型流程提交。其他账号使用私有数据集前需取得 Hub 访问权限。

墙钟不限制 token 或费用；实际费用未知时保留 unknown，reported cost=0 不代表免费。

## 重连、状态与报告

将下方 ID 替换为真实 ID；默认输出摘要/表格，脚本使用全局或命令后的 `--json`：

```bash
.venv/bin/harbor-helper list
.venv/bin/harbor-helper status hh-替换为真实ID
.venv/bin/harbor-helper logs hh-替换为真实ID
.venv/bin/harbor-helper report hh-替换为真实ID
.venv/bin/harbor-helper status hh-替换为真实ID --json
```

模型报告等待终态凭据审计，运行中用 status/logs 观测。报告显示有效尝试数、缺评分与异常；合法低分/零分仍有效。`compare` 检查题目、模型、环境等是否可比，不可比时显示原因。bundle、报告与证据操作见[操作指南](docs/operations.md)。

需要取消时单独执行；终态 cancelled 才确认停止与清理：

```bash
.venv/bin/harbor-helper cancel hh-替换为真实ID
```

需要重新执行且已有预算授权时，`rerun` 新建 ID 并完整重跑固定输入，模型任务会再次发请求：

```bash
.venv/bin/harbor-helper rerun hh-替换为真实ID
```

## 显式 Oracle 自检

无模型自检明确选择 oracle，不需要模型登录，不请求模型：

```bash
.venv/bin/harbor-helper submit --agent oracle --task generation--box \
  --attempts 1 --concurrency 1 --wall-seconds 1200
```

oracle 自检评分不证明模型实际工具调用或产物。模型登录期间也可提交 oracle，无需随后刷新。

## 注销与证据

```bash
.venv/bin/harbor-helper auth logout
```

存在未终态任务时拒绝轮换/logout，先等待或取消。logout 撤销新执行资格；已使用的历史审计来源仍受保护保留，不等于彻底抹除 key。外部引用失效时对应历史审计不完整；新任务按自身来源判断。

证据交接前等待全部终态，再用原生 `stop` 确认调度器退出、`scan` 扫描整个 state。缺来源、扫描错误或命中不能宣称 clean；详见[操作指南](docs/operations.md#日志与证据交接)。

## 文档导航

- [配置指南](docs/configuration.md)：首次部署、team/model、隐藏输入、文件引用、TTL与刷新。
- [操作指南](docs/operations.md)：bundle、镜像维护、比较、恢复、扫描及故障处理。
- [原生入口设计](docs/usability-design.md)、[设计与范围](docs/v0-design.md)、[验收条件](docs/acceptance.md)。
- [CLI + Web 服务设计](docs/service-design.md)、[服务验收标准](docs/service-acceptance.md)、[服务部署与使用](docs/service-operations.md)：受邀团队共享 HTTP 服务，本地账户、团队模型方案和统一队列。
- [成员验收](docs/member-acceptance.md)：真人提交、重连、比较与 rerun。
- 实现证据、独立检查报告：来源、验证和限制。
- [CLI 源码](src/harbor_helper/cli.py)、[配置示例](configs/team.example.json)。

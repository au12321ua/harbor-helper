# 详细操作与维护

模型命令先按 [README](../README.md#一次登录)完成原生 auth login；已部署成员使用统一 state，不重新 init。本文中的模型 submit/rerun 都会发请求，只在已有授权与预算范围内执行。

## 日常提交与容量

```bash
.venv/bin/harbor-helper submit --preset model --task generation--box \
  --attempts 1 --concurrency 1 --wall-seconds 1200
.venv/bin/harbor-helper list
.venv/bin/harbor-helper status hh-替换为真实ID
```

`--task` 支持任务名 glob，不给则选择本次所选数据集的全部任务。`--attempts/--concurrency/--wall-seconds` 在团队上限内覆盖 preset。`--dataset` 覆盖本次提交的数据集，不修改 team.json 中的默认值；只接受数字 revision 或 sha256 digest。`--model` 选择维护者 endpoint 已服务的模型 ID。提交成功前实际解析并下载 Hub 任务，保存 agent/verifier 原始输入；失败不会返回假成功 ID。

```bash
.venv/bin/harbor-helper submit --dataset au12321ua/harbor-helper-switch-smoke@1 --agent oracle
```

该私有单题数据集的源码见 [切换示例](../examples/harbor-helper-switch-smoke/README.md)，其他账号需取得 Hub 访问权限。后续不带 `--dataset` 的新提交继续使用团队默认值；rerun 使用原实验的数据集与任务快照。更改团队长期默认值由维护者编辑 team.json 的 dataset 字段，仅影响新提交。不同数据集的报告不能汇总为可比改进。

当前支持 Hub package 的任务集选择；数据集级自定义 metrics/files 与本地数据集目录尚不支持。实际 Hub/Docker 切换与重跑结果见 验证记录。

输出 run ID 后可以断开 SSH；重连后直接使用 CLI 查询。Job/Trial 槽位作用于统一 state，无法限制其它项目、独立 state 或直接运行的 Harbor；未确认收尾的 Job 保持 cleanup_blocked 并占槽位。墙钟预算从 worker 开始，队列和提交前下载不计入；基础设施重试为 0，CPU/内存由原生 override 设置，磁盘/token/费用硬限额不支持。

需要取消时单独执行：

```bash
.venv/bin/harbor-helper cancel hh-替换为真实ID
```

取消先记录请求，最终 cancelled 才确认进程停止与归属资源清理。queued 取消无需起容器；running 取消保留结果，不影响其它 Job。不使用全局 Docker prune。

## 候选 Bundle

```text
candidate/
  skills/<skill-name>/SKILL.md
  sdk/                         # 源码通过运行时 PYTHONPATH 提供
  config/opencode.json          # 非秘密的 OpenCode 原生配置
  bootstrap.sh                 # 可选准备脚本
```

```bash
.venv/bin/harbor-helper submit --preset model --bundle ./candidate --task generation--box \
  --attempts 1 --concurrency 1 --wall-seconds 1200
```

提交时复制 bundle 并计算包括路径、文件内容和执行位的 SHA-256。源目录后续修改不影响排队/运行/rerun；拒绝符号链接与特殊文件。Harbor 原生 skills 注入技能，整个快照上传至 `/opt/harbor-helper-bundle`。bootstrap 在 agent 容器以 root 执行，失败记录为 Trial 异常；`bundle-setup.txt` 保存准备证据。

仅放入 SDK 源码不代表自动 pip install；bootstrap 可安装 SDK/准备环境，运行时 PYTHONPATH 指向 bundle/sdk。OpenCode 配置合并到真正使用的配置，仅允许维护者已选 compatible provider，不能改变模型 endpoint。不要放 key、私钥、`.env` 或其它凭据到 bundle。oracle 也可显式 `--agent oracle --bundle ./candidate` 验证准备过程；任务与 verifier 仍使用原生流程。

## 报告、比较与整体重跑

任务终态后查看报告；比较时等待两组实验都结束：

```bash
.venv/bin/harbor-helper report hh-替换为真实ID
.venv/bin/harbor-helper compare hh-基线ID hh-候选ID
```

报告只将无异常且含有限数字 reward 的 Trial 计为有效。基础设施错误、缺失/损坏结果单列，不能当有效零分；低分本身不等于执行失败。helper 不读取 CAD 私有指标文件，也不重写评分器。

compare 要求固定题目/评分来源、模型、尝试/并发/资源/版本条件一致。bundle 可不同并显示摘要变化。逐任务 delta 是右减左，整体为同指标任务均值；不可比时说明原因、退出码 2，不输出聚合改进结论。runtime_image 与实际 image ID 都参与核对；更换预装镜像后不能无条件比较旧冷启动实验。

rerun 创建新 ID，复制旧 run 的固定题目/评分、bundle、有效配置和镜像身份。旧文件保留；快照缺失或被改动时拒绝。它是完整重跑，不支持只重试失败 Trial，也不恢复中途模型会话。实际 checkpoint 不可观察时仍 unknown，随机模型不保证逐字复现；模型 rerun 须有对应请求预算授权。

确认需要重新执行后再运行：

```bash
.venv/bin/harbor-helper rerun hh-替换为真实ID
```

## 维护构建与复用

先用只读 CADIR Git checkout 中的固定 commit 构建 CAD runtime：

```bash
.venv/bin/python scripts/build_cad_runtime.py --cadir /path/to/CADIR --prepare-only
.venv/bin/python scripts/build_cad_runtime.py --cadir /path/to/CADIR
```

`configs/cad-runtime.json` 固定 CADIR 2.1.4 commit、OS base digest 和镜像命名。导出仅包括已提交 wheel 输入与 matching docs/skill，忽略 checkout 未提交修改，拒绝链接/路径穿越。记录在 `.state/runtime-build/provenance.json` 与 pip-freeze.txt；不修改相邻 CADIR/cad-bench、不发布镜像/数据集。

构建/载入其它本机已验证 CAD 镜像时，`build_cad_runtime.py --reuse-image <镜像> --reuse-manifest <来源记录>` 核对源码归档、Dockerfile、base、实际源文件/安装源码/skill，再打本项目 alias。源码与初始 OS 固定，传递依赖构建时解析，实际 pip freeze 留档，不保证无缓存重建字节一致。

维护者可一次预装固定 OpenCode，再让成员每次任务复用：

```bash
.venv/bin/python scripts/build_opencode_runtime.py
.venv/bin/python scripts/build_opencode_runtime.py \
  --reuse-image harbor-helper/cad-opencode:7eb39cd43038c7402e7b \
  --output .state/opencode-runtime-reuse
```

仅继承固定 CAD base 并预装发行版 Node/npm、opencode-ai@1.18.35，无模型请求/凭据。脚本核对全部父层、CAD source/installed/skill 文件与 Python freeze 不变；`.state/opencode-runtime-build/provenance.json` 记录基础/派生 image ID、构建输入、工具实际版本和维护耗时，APT/npm 传递依赖在构建时解析。本机 tag 以自身 provenance 为准，image ID 不是 registry 拉取 digest；其它机器须构建或载入核验的镜像。

安装路径探针使用已冻结的题目目录，只跑 Harbor 原生 install_only，输出目录必须新建：

```bash
.venv/bin/python scripts/verify_opencode_startup.py \
  --task /path/to/frozen/generation--box \
  --provenance .state/opencode-runtime-build/provenance.json \
  --output .state/opencode-startup-new
```

它拒绝携带 VLLM_API_KEY，不执行 agent.run/verifier，记录环境、agent setup、安装核对与含清理总耗时。维护构建耗时与成员任务耗时分开；该探针不代表完整模型实验耗时。实际 `HelperOpenCode.install` 匹配版本时跳过 apt/npm，缺失或旧版安装指定版本并验证，`agent/install-decision.json` 留档。

维护者验证镜像来源、安装入口和 oracle 评分后，在所有任务终止的空闲窗口修改 team.json 的 runtime_image；后续 CLI 自动加载配置与授权；必要时使用原生 stop/recover。新配置只用于新实验，已有 run/rerun 镜像不改。固定来源、历史 hash/耗时和原生评分证据见实现证据与独立报告。

## 日志与证据交接

每个 run 位于 `$HARBOR_HELPER_STATE/runs/<run-id>/`，包括 manifest.json、冻结 tasks/、可选 bundle/、有效原生 job.json、worker runtime/日志、原始 harbor/ Trial 与 verifier/产物、projects.json、cleanup.json、credential-audit.json 和 report.json。

交接前等待所有任务终态，再用原生 stop 等待调度器确认退出，扫描整个 state：

```bash
.venv/bin/harbor-helper stop
.venv/bin/harbor-helper scan
```

scan 只返回安全计数与结论，不输出匹配值。扫描包括大文件/二进制、SQLite 字段、原值及 URL/JSON 转义、base64 表示；专用私有凭据区与 state 分离，不作为产物扫描。活动写者存在时拒绝；缺所需历史来源返回 audit_complete=false/clean=false，不能把 K2 当前登录当作 K1 历史完整覆盖。命中、不可读、来源失效时不要读取/转发原始证据。

日志默认可读流，--json 返回 JSON 字符串；无法取得本run来源时原始日志拒读，安全 status 摘要仍可看。关联来源可用后读取：

```bash
.venv/bin/harbor-helper logs hh-替换为真实ID
.venv/bin/harbor-helper report hh-替换为真实ID
```

report 会重新生成派生报告，补写证据后交接前再次 scan。停写扫描后不要再用 list/status 启动调度器并仍称最终停写证据；继续运行用 recover。scanner 不检测任意编码或阻止恶意任务网络泄密，题目/bundle 须受信任。logout/轮换后的历史来源保留和清除限制见[配置指南](configuration.md#登录与调度器刷新)。

## 故障处理

| 现象 | 处理 |
| --- | --- |
| model 未配置、doctor 失败 | 维护者检查非秘密 team.json、Hub 权限、Docker/兼容 runtime；doctor 不证明认证可用 |
| key 文件 unavailable/invalid | 核对明确路径、当前所有者、0600、普通文件/非链接；不输出文件内容 |
| 认证、接口或工具调用不兼容 | 保存经审计的错误类型/摘要，先诊断服务与配置，不盲目 rerun |
| 新 CLI 提示模型凭据缺失 | 先 auth status 核对选中team、有效期和来源；全部终态后 auth login，CLI自动刷新idle实例 |
| cleanup_blocked | 保持占容量；核对是进程停止、归属 Docker 清理还是凭据审计失败，不修改数据库绕过 |
| scheduler 已死 | 用原生 recover 协调原 worker/收尾，不重执行模型 |
| 活动 scheduler 无审计凭据且无法收尾 | 恢复本run的原引用/权限后 recover；硬恢复缺原key将保持阻塞，不轮换/logout逃避审计；旧版历史来源可由兼容文件启动器处理 |
| worker 中断或墙钟触达 | 等清理与审计完成、保留原结果；需要新实验时另行确认预算，用整体 rerun 或新 submit |
| 快照被改、镜像 alias 身份变化 | 不改 frozen tasks/bundle；按错误来源修复，旧 run 保留供核对 |

清理按记录的精确 Compose project 执行；PID 与 Linux 启动时间一起识别，拒绝误杀复用 PID。flock 防多 scheduler/同一 worker 重复。跨 write/flush 输出脱敏、reason 入库前处理、先清洗原生再生成派生报告；SQLite 按字段检查，冻结输入不改，clean 只读日志无需写入。命中不可清洗/扫描不完成/缺所需审计凭据时仍阻塞，不放宽权限或忽略错误释放容量。

## 自动化输出

默认 Rich 摘要/表格；脚本须明确选择 JSON，全局及常用命令后均支持：

```bash
.venv/bin/harbor-helper --json list
.venv/bin/harbor-helper report hh-替换为真实ID --json
```

JSON 保留原数据字段与退出码，日志字符串为合法 JSON 编码；human 摘要不改变评分/可比性语义。不匹配比较退出2，失败诊断或 scan 不clean退出1。list/status 可能自动启动调度器，scan 前使用 stop。

## 开发检查与验收

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

范围和验收定义见[设计](v0-design.md)、[验收条件](acceptance.md)。真实模型成功、失败与未覆盖范围分别记录；真人成员须按[成员指南](member-acceptance.md)自行提交、重连、比较和 rerun，文档或机器人检查不替代真人反馈。

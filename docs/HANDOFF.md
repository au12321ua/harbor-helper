# 开发交接

本页是 Maestro 的维护入口。重写从 `9ff43b5` 开始，在 `feature/rewrite` 上按[重写目标设计](design/README.md)整体进行，2026-10-24 替换了 `dev` 上的旧实现；之后的工作从 `dev` 开始，规则见[分支、协作与发布规则](guides/development-workflow.md)。项目改名为 Maestro，新代码使用 `maestro` 包；不再使用 botmux 协调，用户决定记录在[决策记录](design/14-decisions.md)第 0 节。

## 需求与设计

- 需求基线是[需求整理与审查](design/requirements-review.md)（审计稿）；00～15 模块文档是它的延伸设计。
- 实践优先：实现中发现更好的做法或设计有问题时，先在[决策记录](design/14-decisions.md)记录，再同步修改模块文档。
- 用户决定与冲突结论见决策记录第 0 节；尚未定论的冲突，确认之前不按任何一方擅自实现。

## 进度

- M0、M1 已于 2026-10-22 完成。M1 的结论、样例与版本见[M1 验证记录](design/records/m1-validation.md)；原型代码与原始证据在主仓 `.local/`。
- M2 地基已实现（2026-10-22）：新包 `src/maestro/`、最简网页与测试；实现中的选择与未覆盖范围见[M2 实施记录](design/records/m2-foundation.md)。
- M3 执行内核已实现（2026-10-23）：独立 Runner 环境（`runner/`，锁定 Harbor 0.24.0）、协议、错误策略映射、实时步骤与日志、取消、按标签清理、重启对账和容量。选择与未覆盖范围见[M3 实施记录](design/records/m3-execution.md)。
- M6 结果与产物已实现（2026-10-23）：评分汇总与覆盖率、产物到期与回收、启动对账、批量导出、磁盘水位、两步删除与回收站。按用户安排 M5 暂时跳过，M4 在另一会话并行；M6 中依赖它们的部分（管理员确认的评分契约、删除数据集版本时回收准备缓存、凭据与运行的绑定）见[M6 实施记录](design/records/m6-results.md)。
- M4 数据集与准备已实现（2026-10-23，与 M6 并行，合并在 M6 之后）：Hub 数据源（经 Runner）、管理员导入与首次准备、按任务的准入、内容可得性与本机缓存分开记录、平台自己构建或拉取并导出原件（U-17）、共享恢复（租约、代次、等待者、pin）、恢复失败计为试次的执行尝试、手动回收、重启对账、作者参数与评分契约确认，以及数据集页。选择与未覆盖范围见[M4 实施记录](design/records/m4-datasets.md)。M5 仍待做。
- 独立审查与修复（2026-10-23，在 `302b2ff` 上审查，修复在 `fix/review-findings`）：修了 Runner 实时日志可经符号链接读宿主机文件、凭据停用后无法解密并卡死主密钥轮换、准备流程的崩溃与占用泄漏、被删或停用管理员发出的邀请仍可兑换、清除失败仍报已清除、评分指标不起作用等；Hub 检索改为仅管理员（U-20）。选择、验证范围和留给后续的问题见[独立审查与修复记录](design/records/review-2026-10-23.md)。
- 与机器和磁盘有关的数值上限进入 `config.toml`（U-21，同一分支）：归档与导出大小、构建、拉取与保存时限、同时恢复数、Hub 并发、Runner 心跳与静默时限，启动时校验，生效值见 `/capabilities`。见[部署上限记录](design/records/config-limits.md)。
- M5 分四段进行。第一段配置地基已实现（2026-10-23，`feature/m5-config`）：团队策略按修订进数据库、模型配置（三种协议）与 Harness 版本、配置解析接口（字段来源、阻塞项、`config_digest`）、凭 `resolution_id` 提交、作者参数取值，以及对应的管理页和新建运行页。第二段模型 Agent 执行已实现（同日、同一分支）：Harness 先做 Terminus-2（U-25），凭据执行时解密、只在 Runner 内存里，模型运行的 Agent 与验证阶段由平台收紧为断网，Agent 轨迹实时可读，真实模型冒烟已通过。第三段附件已实现（同日、同一分支）：成员或 experiment PAT 上传固定内容的附件包，配置解析按顺序固定附件并检查兼容与冲突，每个试次在自己的容器里于 Agent setup 中复制、逐文件比对并运行 `bootstrap.sh`（有时限和日志，失败只影响本试次，归为附件失败而非零分），以及附件页和新建运行页的附件选择。第四段已实现（同日、同一分支）：按原快照重跑（全部、未得分的任务或指定任务）与修改后运行（记录差异）、实验方案（按修订保存的部分配置，作为解析中的一层）、提交批次（全有或全无、按运行数扣 PAT 额度、整批取消），以及方案页、批次页和运行详情页的对应操作。M5 四段已全部完成，按 U-24 合入 `feature/rewrite`；之后补了可配置的准备代理与 OpenCode 适配（Harness 现有 Terminus-2 与 OpenCode）。本机默认的本地服务是 8432 端口的独立实例（配置在主仓 ignored `.local/maestro-local/`），用户自己的端到端测试也走它，开发与测试不要使用它的 state。选择与未覆盖范围见[M5 实施记录](design/records/m5-configuration-submission.md)的第一至第四阶段。
- M5 独立审查与修复（2026-10-24，`review/m5`）：修了作者参数可借默认值改写 Runner 环境、多步任务与自带网络的 compose 服务绕过网络收紧、准备代理凭据进入进程列表、附件包的内存炸弹、幂等重试在方案或上限变化后失效、重跑绕过磁盘水位等。本机 Docker 已改为 rootless；配好其代理后，真实 Docker 测试在 rootless 上全部通过（真实模型冒烟除外）。三项需要用户决定的事已定为 U-26～U-28 并实现（同日）；留给后续的问题见[M5 实施记录](design/records/m5-configuration-submission.md)的“M5 独立审查与修复记录”。
- M7 SDK 与网页已实现（2026-10-24，`feature/m7-sdk-web`）：受控的公开契约 `openapi/maestro-v1.json`（操作名稳定、错误都声明为结构化外壳），网页类型与 Python SDK 模型都从它生成，漂移由测试与 `npm run check:api` 发现；Python SDK（`sdk/`，包 `maestro_sdk`）覆盖 PAT 能做的全部操作，三个故事各有一条只经 SDK 走完的测试，并在真实 HTTP 上用演示执行器走过一遍；能力接口报告契约摘要；给 Agent 的 skill 在 `skills/maestro-sdk/`。网页按 11 整理：工作台与待处理、类似 GitHub Actions 的执行页、管理页分栏与维护页、设置页的 SDK 上手说明。删除了旧的研究客户端 skill、基线附件说明与最后的 `harbor_helper` 模块。选择与未覆盖范围见[M7 实施记录](design/records/m7-sdk-web.md)。
- 文档审计与 CI（2026-10-24，`fix/docs-ci-audit`）：决策记录只留决定与登记表，M1～M7 的实施记录移到 [`design/records/`](design/records/README.md)；按决定和代码同步了 00～03、05～07、09～12、15 与本页中过时的描述；管理员路由统一挂上路由级检查 `admin_session`，测试遍历全部管理路由；测试配置固定执行容量，不再读宿主机内存；新增 Gitea CI（`.gitea/workflows/verify.yml`）。
- M8 运维与替换已实现（2026-10-24，`feature/m8-ops`）：按 U-29（系统级布局、专用账户 `maestro` 用系统 Docker 组、压缩包发布）实现发布打包 `tools/build_release.py` 与安装管理命令 `maestroctl`（检查、安装、启停、状态、日志、同机备份恢复、更新与失败回退、保留数据的卸载与确认后的彻底清除）；补上 M5 遗留的受理时网络能力检查（服务启动时经 Runner 探测，不能限制网络时模型运行在受理时被拒绝、不扣额度）；补了验收缺口测试；删除最后的基线目录 `configs/`、`examples/`、`images/`。选择、验证范围与未覆盖项见[M8 实施记录](design/records/m8-operations.md)。

## 代码状态

- 新代码在 `src/maestro/`，Runner 在 `runner/`（单独的 uv 项目和锁文件），Python SDK 在 `sdk/`（单独的包，开发环境以可编辑方式安装），安装管理命令在 `ops/maestroctl.py`，测试在 `tests/maestro/`；分工见[源码职责](architecture/source-layout.md)。基线的 `harbor_helper` 包已全部删除。
- 重写期间按模块替换，新模块就绪后直接删除对应的基线代码和测试，不保留新旧并行、转发层或兼容分支。
- 不承诺向后兼容，不迁移旧 state，新实现从空实例初始化。对外 HTTP、SDK、CLI 契约随重写修改。
- 可移植的基线与 `dev` 代码见[实施计划](design/13-testing-plan.md)第 2.3 节。移植时先读原代码，按新设计重写接口。

## 验证入口

需要 Linux、Python 3.12–3.13 和 uv；实际执行另需 Docker/Compose、可用作者依赖与 Hub 权限。依赖由 `pyproject.toml`、`uv.lock`、`frontend/package-lock.json` 记录。

- Python：`uv sync --locked --group dev`、`uv run pytest -q`、`uv run ruff check src tests runner/src tools sdk/src ops`；新代码另跑 `uv run ruff format --check src/maestro tests/maestro runner/src tools sdk/src ops`。
- 契约：改了 API（路由、公开模型）后运行 `uv run python tools/generate_clients.py` 重写 `openapi/maestro-v1.json` 与 SDK 模型，再在 `frontend/` 执行 `npm run gen:api` 重写网页类型；三者都要提交。`tests/maestro/test_sdk.py` 会核对前两者，`npm run check:api` 核对网页类型。新增给 PAT 用的接口时，同时给 SDK 加方法并登记到 `test_sdk.py` 的 `SDK_METHODS`。
- Runner：在 `runner/` 执行 `uv sync --locked`。真实 Docker 测试需显式开启：`MAESTRO_DOCKER_TESTS=1 uv run pytest -q tests/maestro/test_harbor_docker.py`。它只用本地 Oracle 任务和已有的 `ubuntu:22.04`，需要 buildx，不调用模型和 Hub；执行资源都带每个测试独立的实例标签，准备好的镜像在每个实例自己的 `maestro-prep/<实例>` 仓库名下，结束时都核对清空。Terminus-2 的用例需要本地镜像 `maestro-test/ubuntu-tmux:22.04`（`FROM ubuntu:22.04` 加 `apt-get install tmux`，没有时跳过），模型是测试进程里的假服务，不花钱；它还要求容器能访问 example.com，用来对照 Oracle 运行能出网、模型运行出不了网。另有两项故意失败的用例核对错误分类：一个 `RUN` 步骤失败的 Dockerfile，和一个指定了不存在镜像的任务（后者会请求注册表，守护进程连不上时跳过）。运行前后建议对 `docker images`、`ps -a`、`network ls`、`volume ls` 各留快照对比。Docker 为 rootless 时，docker context 存在用户 HOME 里，隔离 HOME 会让客户端回到 `/var/run/docker.sock`，须显式设 `DOCKER_HOST=unix:///run/user/<uid>/docker.sock`；rootless 守护进程有自己的镜像库和代理设置，与原来的系统守护进程不共享。BuildKit 向镜像仓库取令牌由 docker 客户端进程完成，用 `env -i` 跑真实测试时须把宿主机代理（如 `HTTP_PROXY`/`HTTPS_PROXY=http://127.0.0.1:7890`）放进去，否则镜像库里还没有的基础镜像（如 Harbor 出口控制 sidecar 的 `gogost/gost`）会在解析时超时。真实模型冒烟默认跳过，会产生费用，需显式开启：`MAESTRO_DOCKER_TESTS=1 MAESTRO_MODEL_TESTS=1 MAESTRO_MODEL_ENDPOINT=<OpenAI 兼容地址> MAESTRO_MODEL_ID=<模型> MAESTRO_MODEL_KEY_FILE=<key 文件> uv run pytest -q -s tests/maestro/test_harbor_docker.py -k real_model`，一个试次、最多 5 轮。真实 Hub 测试另需 `MAESTRO_HUB_TESTS=1 uv run pytest -q tests/maestro/test_hub_live.py`：匿名读取公开的 `harbor/hello-world`，导入测试会真实构建（基础镜像可能被拉取）；Runner 继承代理变量，但不支持 SOCKS 代理变量（`ALL_PROXY`）。
- 数据库：`schema.py` 与最新迁移须一致（`tests/maestro/test_migrations.py` 检查）。首个发布前没有已部署的 schema，`0001` 可以随 `schema.py` 重新生成；发布后只追加迁移。并行分支都改了 `schema.py` 时，合并后在合并结果上重新生成 `0001`。
- 实例：`maestro --config <config.toml> init / db upgrade / serve / backup / restore / openapi`；示例配置与试用步骤见根目录 README。
- 安装与发布：`uv run python tools/build_release.py` 打包（要求工作树干净，测试可加 `--allow-dirty --label <名>`）；`ops/maestroctl.py` 的规则由 `tests/maestro/test_maestroctl.py` 覆盖。完整的安装、更新、失败回退、备份恢复、卸载与清除需显式开启：`MAESTRO_INSTALL_TESTS=1 uv run pytest -q tests/maestro/test_install.py`。它用隐藏参数 `--test-root` 把整个布局放进临时目录，以当前用户运行并注册一个 systemd **用户**单元（结束时删除），不需要 root；需要 uv、systemd 用户实例和可连接的 Docker（rootless 时设 `DOCKER_HOST`）。真正的系统级安装只能由有 sudo 的人执行，步骤见[部署指南](guides/deployment.md)。
- 前端：在 `frontend/` 执行 `npm ci`、`npm run build`、`npm run lint`；build 写入 `src/maestro/static/`。OpenCode 的真实测试需要先构建 `maestro-test/ubuntu-opencode:22.04`（`tests/maestro/fixtures/images/opencode/Dockerfile`，可经代理构建），用与 Terminus 真实冒烟相同的 `MAESTRO_MODEL_*` 变量运行 `test_opencode_with_a_real_model`。主机需要代理才能顺畅准备环境、安装附件时，部署配置设 `setup_proxy`（见 [12](design/12-operations.md) 第 3 节）；真实 Docker 测试同样可设 `MAESTRO_TEST_SETUP_PROXY=http://<容器可达的地址>:<端口>`。网页冒烟测试（Playwright）需要一个全新的一次性 state：`maestro --config <tmp>/config.toml init` 记下初始化令牌，`maestro --config <tmp>/config.toml serve --port 8431 --demo-executor`，再在 `frontend/` 执行 `MAESTRO_SETUP_TOKEN=<令牌> npm run test:ui`（说明见 `qa/smoke.spec.ts` 开头）。同一个 state 只能跑一次，因为第一步是初始化管理员。
- 验证使用独立 HOME、state 和主密钥，隔离 Harbor/profile，并清除继承的真实凭据环境。测试含本地子进程，不能默认没有副作用。真实 Hub、Docker、模型请求与 fixture 验证分开记录；真实模型请求须核对当前授权与预算。
- CI：`.gitea/workflows/verify.yml` 在 `HH_RUNNER_LABEL` 指定的 runner 上对每次推送运行：ruff、`tools/generate_clients.py --check`、`tools/check_doc_links.py`（Markdown 相对链接）、不含 Docker / Hub / 模型的 pytest（只传 PATH 与临时 HOME）、网页 lint、`check:api`、build，并核对 `src/maestro/static/` 与源码一致。真实 Docker、Hub 与模型测试仍按上面的开关在本机手动运行。
- 重写后的验收场景见[测试验收与实施计划](design/13-testing-plan.md)。验证命令和门禁随重写调整，以本页为准。

现场报告与原始证据只保存到主仓 ignored `.local/`；公开文档只留短的固定代码版本、实际覆盖与未覆盖范围摘要。集成后的 worktree 和短期分支按协作规则收尾。

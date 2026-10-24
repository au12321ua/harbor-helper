# M8 运维与替换实施记录

导航：[决策记录](../14-decisions.md) · [实施记录索引](README.md)

本页按记录时点保留，不随后续实现改写为“最新状态”；后来的用户决定或实现若推翻其中做法，以决策记录第 0 节和对应模块文档为准。

## M8 实施记录（安装、启停、更新、备份与卸载）

**2026-10-24。** 实现 13 的 M8：按 12 的系统级布局安装与维护一个实例，补上 M5 遗留的受理时网络能力检查，补验收缺口测试，删除最后的基线目录。部署形态先与用户讨论：用户考虑过装在个人账户下、容器化安装和专用账户用自己的 rootless Docker，最后定为 U-29。下表除 U-29 本身外，都是实现中的选择，未经用户逐条确认。

| 事项 | 原设计 | 实际做法 | 理由 |
| --- | --- | --- | --- |
| 部署形态（U-29） | 12 第 1 节、U-13：系统级布局与专用服务账户 | 保持系统级布局；`maestro` 系统账户加入系统 Docker 套接字所属的组（安装器拒绝属组为 root 的套接字）；`--docker-host` 可指向别的守护进程，此时不改组 | 用户决定。docker 组约等于 root，在可信团队前提下接受；rootless 备选需要从属 ID、linger、每账户守护进程与代理，留到以后 |
| 管理入口 | 12 第 1 节：独立管理入口；网页经受保护 IPC 请求预定义维护动作 | 单文件 `ops/maestroctl.py`，只用系统 Python 标准库（需要 3.11 以上的 `tomllib`），发布包内附一份，安装后 `/usr/local/sbin/maestroctl` 链接到当前版本的那份。不做网页发起的维护 | 安装发生在任何 Maestro 环境存在之前；U-29 不做网页一键更新 |
| 发布包 | 12 第 1 节：versions 目录、明确版本 | `tools/build_release.py` 打出 `maestro-<版本>-<提交前 12 位>.tar.gz`：服务 / Runner / SDK 的 wheel、`uv export` 出的带哈希锁定依赖、`maestroctl`、`INSTALL.md`（即部署指南）与 `RELEASE.json`（版本、提交、构建时间、数据库结构版本、Harbor 版本、Runner 修订、每个文件的 SHA-256）。工作树不干净时拒绝打包；测试用 `--allow-dirty` 与 `--label` | 网页在服务 wheel 里，安装机不需要 git 与 Node；安装前逐个核对文件摘要 |
| Python 环境 | 15 第 4 节：服务与 Harbor 各自的 uv 环境 | 版本目录下 `venv/`；Runner 环境在 `harbor/<Harbor 版本>/<Runner 修订>/venv`，修订是 Runner wheel 与其锁定依赖摘要的前 12 位，相同则不同版本共用；版本目录里的 `runner-env` 链接指向它，配置写 `current/runner-env/venv/bin/python`。`uv venv` 加 `uv pip install --require-hashes --compile-bytecode`，再 `--no-deps` 装 wheel。生产安装时 `UV_PYTHON_INSTALL_DIR=/opt/maestro/python`、`UV_CACHE_DIR=/opt/maestro/.uv-cache`；uv 从 `/` 运行，不受调用目录里的项目或虚拟环境影响 | venv 不能搬动，所以直接建在最终位置，完成后写 `.complete`；解释器不能放在 root 的家目录里，否则服务账户读不到；程序只读时预编译字节码 |
| uv 的来源 | — | `--uv`、`MAESTRO_UV`、PATH、`/opt/maestro/bin/uv`、`SUDO_USER` 的 `~/.local/bin/uv` 依次查找；安装与更新时复制为 root 所有的 `/opt/maestro/bin/uv` | sudo 的 PATH 常常没有 uv；之后以 root 运行的更新不执行用户可替换的二进制 |
| 目录与权限 | 12 第 1 节 | `/opt/maestro` root 所有；`/etc/maestro` 为 root:maestro 0750，`config.toml` 与 `environment` 0640；`secrets/`、`/var/lib/maestro`（家目录在其下 `home/`）、`/var/cache/maestro`、`/var/backups/maestro` 归 `maestro`，0700 | 主密钥代码要求密钥目录归服务账户且不可被组写（M2）；程序被攻破也改不了自己 |
| systemd 单元 | 12 第 4 节 | `Type=exec`、`User/Group=maestro`、`EnvironmentFile=-/etc/maestro/environment`、`Restart=on-failure`、`StartLimitBurst=5`/600 秒、`TimeoutStopSec=120`、`UMask=0077`、`NoNewPrivileges`、`ProtectSystem=full` 加 `ReadWritePaths=/etc/maestro/secrets`、`ProtectHome`。不用 `PrivateTmp` | 主密钥轮换要写密钥目录。Harbor 的挂载路径由 Docker 守护进程在宿主机命名空间解析，私有 /tmp 会让放在 /tmp 的挂载源错位 |
| 启动计数 | — | `maestroctl` 自己的 start / restart、更新、恢复先执行 `systemctl reset-failed` | 试装时一次恢复因为前面几次正常重启而撞上启动频率限制；该限制只为挡住崩溃循环 |
| 就绪 | 12 第 4 节：对账后 ready | 安装、启动、更新都轮询 `/health/ready`，等到 `ready`（默认 180 秒），单元变为 failed 时提前结束 | 服务只在对账之后报 ready |
| 代理 | 12 第 3 节 `setup_proxy` | `--proxy` 用于安装时下载，并写入 `/etc/maestro/environment`（大小写两种拼法，`NO_PROXY` 默认本机）；`--setup-proxy` 写入配置。守护进程没有代理时 `check` 只提醒 | BuildKit 取镜像仓库令牌、Runner 的 Hub 下载都在服务进程环境里；不替管理员改全机 Docker |
| 安装检查 | 12 OPS-01：实际验证 nftables 与动态网络切换 | 检查 systemd、uv 与 Python、Docker 守护进程、compose 与 buildx、`/sys/module/nf_tables`、数据磁盘 20 GiB、端口；失败项附修复动作并中止 | 动态网络切换要起容器，安装时不做；它由真实 Docker 测试与服务启动时的探测覆盖 |
| 初始化 | 12 OPS-03 | 以服务账户运行 `maestro init`，令牌只打印一次；已有数据时沿用配置与密钥，不发新令牌 | 卸载默认保留数据，再次安装应当接上 |
| 更新 | 12 第 5 节（P1 排空） | 先在旁边装好新版本；`maestro activity` 报告执行中的运行与非运行类 Operation（不含导出，它们会重建；不含批次，运行状态已涵盖），有则拒绝，`--interrupt-running` 则照常停服；停服、旧版本备份、新版本迁移、原子切换 `current`、重写单元、启动、等就绪；任何一步失败则停服、切回、还原旧单元、用旧版本恢复备份并迁移、启动旧版本，退出码 1。成功后保留上一个版本，删更早的版本与不再引用的 Runner 环境。从旧版本的 `maestroctl update <包>` 调用时解开包并交给新版本的 `maestroctl` 执行 | 没有排空和维护记录，是 P0 子集；新版本最清楚自己怎么安装。失败前新版本短暂运行时写入的数据随回退丢弃 |
| 失败注入 | — | 环境变量 `MAESTRO_CTL_FAIL_AT=migrate|start` 只在 `--test-root` 下生效，否则 `maestroctl` 拒绝运行 | 回退路径要能测试，又不能在生产里被误触 |
| 备份 | 12 第 6 节（P1） | `maestro backup`：SQLite 备份接口取快照，转成单文件并做完整性检查，0600；复制配置；`--include-files` 复制附件、准备原件与产物（`work`、`exports`、缓存不备份）；最后写 `manifest.json`（结构版本、实例、所需主密钥代次与文件名、数据库摘要、各目录文件数与字节、未包含项）。服务运行中也可备份，不加读 pin | 同一主机的 P0 子集；没有清单即不完整。快照之后被回收的文件由恢复后的启动对账标记 |
| 恢复 | 12 第 6 节（P1） | `maestro restore` 要求单实例锁（服务已停），先核对清单、数据库摘要、结构版本是本程序认识的、所需主密钥文件在场（否则 `MASTER_KEY_MISSING`，`--allow-missing-key` 才继续），再替换数据库（删旧 WAL / SHM），按需替换业务文件（原文件改名为 `<名>.before-restore-<时间>`）；`maestroctl restore` 之后迁移并按原状态启动 | 检查都在动手之前；不默默接受凭据丢失 |
| 卸载 | 12 第 7 节 | 普通卸载删单元、命令链接与 `/opt/maestro`，保留其余；`--remove-cache`；`--purge` 先列出目录大小与影响、本实例 Docker 资源数与账户，需 `--confirm <实例编号>`。删除只允许布局里的固定目录，拒绝符号链接与布局之外的路径 | 按实例标签与镜像仓库名删 Docker 资源，不清全机 |
| 无 root 测试 | — | 隐藏参数 `--test-root <目录>`：布局全部放进该目录，以当前用户运行，注册 systemd 用户单元 `maestro-test-<摘要>.service`（没有 `User=` 与沙箱选项） | 开发机没有免密 sudo；仍能用真实 systemd、journald 与 uv 走完整个生命周期 |
| 受理时网络能力检查 | 13 M5 退出条件：首个模型运行之前限制已在目标主机生效，能力不足时拒绝运行 | Runner 新增 `probe` 命令，返回与执行时相同的判断（`network.supported()`，即 Harbor 的内核能力检查）；服务在 Worker 开始前经 `HarborExecutor.probe()` 询问一次。结果为否时，配置解析对模型运行给出阻塞项 `NETWORK_POLICY_UNSUPPORTED`（`/execution_mode`，`CONFIG_INCOMPATIBLE`），受理前拒绝、不扣额度，Oracle 不受影响；能力接口 `features.restricted_network`。探测失败按未知处理，不阻塞，Runner 在运行开始时的检查仍是最后一道 | 受理与执行用同一个判断，不会一边放行一边拒绝。Harbor 的检查在读不到内核配置时偏乐观；限制是否真正生效由真实 Docker 测试对照 Oracle 核对（M5） |
| 验收缺口 | 13 第 4～7 节 P0 场景 | 逐条核对场景与现有测试后，补 `test_acceptance_p0.py`：取消与最终结果同时到达只留一个终态且已得分保留（两种先后）；四个 Worker 同时领取同一运行只有一个租约、每个试次只执行一次；确切内容丢失时 `/rerun` 在受理前被拒且不扣额度，拒绝信息写明预期摘要；缓存回收后 PAT 重跑无需管理员、按原件恢复一次、配置摘要与准入不变；回收缓存不使已有的配置解析失效；产物保存失败与清理失败同时出现时评分保留、两个失败维度都可见 | 审查发现拒绝信息不带 `expected_digest`（02 第 8 节、E2E-DS-05 要求列出）：`raise_if_blocked` 只带字段错误。修为字段错误的说明写成“<任务>: content <摘要> is not available”，公开模型不变 |
| 删除的基线 | 13 M8 行 | `configs/`、`examples/`、`images/`（旧 CAD / OpenCode 运行镜像、示例数据集与探针）。`scripts/` 在此之前已不存在 | 新代码没有引用；需要时查 `9ff43b5` |

### 验证

代码版本为 `feature/m8-ops` 上的 M8 提交，在本机 Ubuntu 24.04（x86_64，systemd 255，Docker 29.9.2 rootless 与系统守护进程并存）上验证。

- 默认测试：`uv run pytest -q` 全部通过，新增 `test_backup.py`（备份恢复、锁、清单与摘要、未知结构版本、缺主密钥、在途工作）、`test_maestroctl.py`（布局、单元、配置能被服务接受、环境文件、删除边界、发布摘要、切换与清理版本、失败注入只在测试根下、需要 root 的命令）、`test_network_capability.py`（执行器经 Runner 探测的三种答案、模型运行在受理时被拒且不扣额度、Oracle 照常受理、Runner 拒绝时试次记为错误而非得分）。
- 安装生命周期（opt-in）：`MAESTRO_INSTALL_TESTS=1 DOCKER_HOST=unix:///run/user/1000/docker.sock uv run pytest -q tests/maestro/test_install.py` 通过（约 16 秒，uv 缓存已热）：从包安装、初始化令牌只出现一次、建管理员、状态与日志、更新（Runner 环境复用、更新前自动备份）、迁移失败与启动失败各自回退到旧版本和旧数据库、备份后改数据再恢复、卸载保留数据、在原数据上重装不发新令牌、未确认的清除什么也不删、确认后全部清除。
- 验收缺口：`test_acceptance_p0.py` 8 项通过（含修复后的预期摘要）。核对时其余 P0 场景已有对应测试；仍只部分覆盖的见“未覆盖”。
- 真实 Runner 的探测：本机 `runner/.venv` 对 `probe` 返回 `network_restriction: true`。

### 未覆盖

- 真正的系统级安装（root、`maestro` 账户、docker 组、单元的沙箱选项）只在用户执行 sudo 安装后核对；开发机无免密 sudo，自动测试走的是 `--test-root` 与用户单元。
- 发行版与 CPU 架构的支持清单（D-010）、Python 由 uv 下载到 `/opt/maestro/python` 的路径、离线安装，均未验证。
- 计划排空、维护记录、网页维护动作、异机恢复与恢复后暂停排队（P1）；备份不加读 pin。
- 安装检查只看内核模块，不在安装时起容器验证动态网络切换；能力探测沿用 Harbor 的乐观判断。
- 受理时检查不覆盖任务自带网络设置的 compose 服务（`unrouted_services`），这类任务仍在 Runner 启动时被拒绝。
- 场景核对后仍只部分覆盖的：共享构建不进主机 CPU / 内存总账，因此“构建容量不重复计”无从验证（M4 记录的缺口）；附件安装失败后数据集准入与共享缓存不变、同一运行中只有一个试次安装失败、setup 阶段打开的连接延续到 Agent 阶段，都没有专门测试；DS-02 注入的是暂态恢复失败而非构建失败；按 D-011 建议值的 10 试次并行压测属于发布记录，未做。

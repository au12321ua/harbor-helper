# 自动化验证与离线运维

统一入口是 `python scripts/verify.py`，GitHub Actions 与 Gitea Actions 调用同一脚本。它不部署或升级服务。需要 Linux `/proc`、pidfd、Python 3.12–3.13、uv、Node 22；浏览器所需系统库须由开发环境或 runner 镜像预先安装。首次运行：

```bash
python3 scripts/verify.py --prepare \
  --browsers /absolute/private/playwright-cache \
  --output /absolute/private/verification-new-directory
```

依赖按 `uv.lock` 和 `frontend/package-lock.json` 安装。`--prepare` 安装 dev 组及测试和类型检查需要的 `mcp` extra，可以联网下载依赖/Chromium，不执行模型请求。依赖缓存可通过 `--dependency-cache` 指定，默认复用调用者 uv 缓存，运行缓存仍隔离。运行阶段使用环境白名单、独立 HOME/XDG/TMPDIR 和不含 Docker CLI 的工具 PATH，无可用 Docker socket；不会继承模型、Hub 或 CLI profile 凭据。`--browsers` 必须是绝对路径，不能位于测试临时 HOME。输出目录必须不存在；保留诊断时只选 `report.json`、`command-*.log`、`pytest.xml`、`pytest-collection.json`、`pytest-execution.json`、`playwright-collection.json` 和 `playwright.json`，不得上传整个临时 HOME、state 或备份。

`full` 与 `backend` 均先对 `src tests scripts tools` 运行 Ruff lint、`ruff format --check` 和 `ty check --python .venv --error-on-warning`。ty 精确锁定为 0.0.89；格式检查不改文件，类型警告也会阻断。默认 `full` 随后运行契约、前端类型/lint/build、全部 pytest 和独占 UI fixture，显式覆盖普通 pytest 默认的 `not browser` 选择。门禁先收集节点，要求全部 pytest 节点 setup/call/teardown passed、无 skip/xfail；browser 集合非空，并核对 helper 记录的实际成功生产脚本集合（从 `frontend/qa/production/**/*.mjs` 自动发现，包含 theme；`qa/manual/` 单独归类为手工），不依赖函数名或固定数量。Playwright 开启 forbidOnly，机器报告与收集身份必须一致、集合非空且无 skip/fixme/失败/flaky/未执行项。构建后对 tracked/untracked static 和契约检查 Git 漂移；发布物落后源码会失败。`--mode backend --python 3.13` 显式用 `-m "not browser"` 排除浏览器层和前端/UI 检查，用于 Python 3.13 兼容检查，不能代替 full。`frontend/qa/manual/live-service.mjs` 和 `frontend/qa/manual/final-integration-production.mjs` 是未接入此入口的手工脚本，不计为自动覆盖。此入口不证明真实 Docker、Hub、模型或发布环境可用。测试布局、mock 保护和扩展门禁的约定见[测试维护](testing.md)。

UI 默认独占 4173，可以用 `--ui-port` 指定；已有 listener、缺浏览器、命令失败、生成物漂移均返回非零。输出记录固定 Git SHA、脏树状态、命令/版本、pytest 用例/skip、退出状态、精确回收记录。每次运行的唯一环境标记传给子树，包括 setsid 子进程；结束和 INT/TERM 时扫描 `/proc` 标记，以 PID birth 和 pidfd 回收，不按进程名或公共端口杀进程。整个监督入口被 SIGKILL/宿主宕机时自身无法清理，须由 CI 作业容器或外部监督者兜底；不能把这类情况说成 trap 已执行。

独立模型协议 wire 测试不进入默认 pytest 收集，避免未安装的外部 OpenCode 二进制改变 full 的零跳过约束。显式执行 `HH_OPENCODE_BINARY=/absolute/verified/opencode uv run pytest -q tests/support/protocol_wire.py`，需预先核对版本1.18.35及二进制来源；仅使用本地假协议服务与假key，覆盖三协议流式文本、工具往返、参数、usage与配置覆盖负例。该检查与独立Docker微任务另行记录，不能以普通full代替。

## GitHub 与 Gitea 接入

两份工作流仅适配平台，检查内容统一由 `scripts/verify.py` 维护：

| 平台 | 工作流 | Runner | 诊断上传 |
| --- | --- | --- | --- |
| GitHub | [verify.yml](../../.github/workflows/verify.yml) | GitHub 托管 `ubuntu-latest` | `upload-artifact@v4` |
| Gitea | [verify.yml](../../.gitea/workflows/verify.yml) | 仓库变量 `HH_RUNNER_LABEL`，默认 `ubuntu-latest` | `upload-artifact@v3` |

两者对所有分支 push、pull_request 和手动 `workflow_dispatch` 运行 Python 3.12 `full`；Python 3.13 `compatibility` backend job 在 dev/master push 或手动运行时执行。普通 job 仅需仓库读权限，不配置生产凭据或部署步骤。checkout 不保留 Git 凭据。

GitHub 使用托管 runner 接受 fork PR；工作流不读取仓库 secrets，不使用 `pull_request_target`。Gitea 可能使用宿主 runner，因此 job 条件拒绝外来 fork PR。Gitea label 不代表隔离保证，管理员须核对实际容器、敏感挂载和网络后再启用。

首次接入需在仓库设置启用 Actions，并确保 runner、Action 源、PyPI/npm/Playwright CDN 与 artifact 服务可达。工作流准备 Python、Node 22、uv 0.11.31 和浏览器系统库；不能 apt-install 的 Gitea runner 应预置系统库并调整准备步骤。GitHub 的 artifact v4 服务与 Gitea 的 v3 接口不同，不直接复制上传步骤。

YAML 入库和本地通过都不代表远端运行通过。推送后核对对应提交的 run 与 artifact：`report.sha`、`status=passed`、full 的 skip=0、非空 `browser_passed`、完整 `production_scripts` 集合、无生成物漂移、Playwright 机器报告通过及 `cleanup.remaining=[]`。分支保护与必需检查另在仓库设置配置，文件本身不会启用这些保护。

## 只读巡检

使用稳定 Python 环境中的 cryptography 46.0.7；`scripts/ops.py` 不导入产品 Store/ServiceData，不做数据库迁移、启停或信号操作。

```bash
/path/to/python scripts/ops.py check --directory /absolute/instance \
  --backups /absolute/private/backups
```

实例采用 local_platform 的 `<base>/state`、`<base>/http.json` 布局。HTTP 需 PID/birth/argv/cwd 和 loopback listener 归属同时匹配才查询 health；alive 和 ready 分开报告，维护状态 alive=true、ready=false 不触发重启。scheduler 检查 birth/argv/state 和心跳年龄；无法确认标为 unknown。SQLite 仅以 `mode=ro` 和 query_only 查询；当前仅支持产品使用的 rollback journal，WAL 模式拒绝为 unsupported，避免只读连接创建/修改 shm。缺失备份时效是 null，不能推断已有备份成功。工具不会打开/展示主密钥内容，也不调用 controller start/restart/stop。目标路径必须显式指定；部署说明中的旧端口/PID不能作为当前事实。

## 在线快照与停写全量

备份输出须在 Git 和源实例之外的 owner-only 0700 目录。操作者明确提供与源配置对应的完整 release SHA（有 http.json 时还检查 code 的 release 目录名）。配置中的 `master_directory` 必须是 state 外受保护的真实目录；从固定数据库副本读取 active 的代次、basename 与 KCV，再配对校验当前 owner、0600、32 字节的文件。空凭据实例也校验 KCV。

```bash
/path/to/python scripts/ops.py backup --directory /absolute/instance \
  --release FULL_SOURCE_SHA --output /absolute/private/backups --kind online
```

在线模式允许 HTTP、scheduler、worker 活着。限时获取**已有** control.lock，SQLite backup API 产生一致数据库副本，复制 service/team/limits/web/admission 配置、bundles、author-inputs 和 audit=clean 的终态 run 证据，前后检查摘要。活动 run 证据排除；preparing submission、活动 run、缺失 bundle/终态证据以及审计受限项写入 manifest。在线复制先非阻塞取得所选终态 run 的 evidence-locks 锁；锁忙返回 deferred，释放 control 后再由操作者重试。配置或不可变证据变化、symlink、锁超时均拒绝完成；`.incomplete` 目录不是可恢复备份。在线包始终 `full_state=false`，即使没有活动任务也只证明列明范围；scope=partial 必须保留到恢复结果。运行时日志/锁和未选择的 state 内容不在在线保证内。

快照 master 是包目录旁独立的 `snapshot-ID.master`，保持 0600，不在 state、manifest 或报告中输出密钥。该文件与快照一并留在受保护的私有存储；不能上传 CI artifact。没有自动保留清理，所有备份和未知文件均保留，容量由管理员监控。

完整快照只用于人工维护窗口：先在网页关闭新增受理、等待/取消全部已受理工作，再由对应实例控制器停止 HTTP/scheduler。工具本身不启停服务。`--kind offline` 持有产品写者独占租约；所有 Store（含构造时数据库迁移）和来源准备子进程持有共享租约。只有 unit 已停、进程身份已退出、全部任务终态且已确认执行资源清理，才复制整个 state。复制前、复制后和快照的文件清单及原始数据库摘要必须一致，不允许 journal；升级在独立恢复检查和新 release 安装后、切换前再次核对 live state。

同 UID 可读取进程的 state argv/cwd/fd 引用仍阻止备份。不可读取进程记录 comm/cgroup/Uid/Gid/CapPrm，仅作为观察限制；窗口前后 `(pid,birth)` 集合变化则延期。manifest 的 `claim=product_writers_stopped_and_content_stable` 只证明产品停写、资源清理和复制内容稳定，不证明宿主没有其他写者；其他 UID 不在进程扫描范围。维护窗口必须禁止外部工具进入 state。既有不可读取的外部进程可能在窗口后写入，这是部署者需要隔离的边界。scheduler.wake、scheduler-stop.json、evidence-locks 等瞬态记录不入快照；持 FIFO 的可读进程同样阻止备份。禁止把 timer 变成自动停机工具。


## 新目标离线恢复检查

```bash
/path/to/python scripts/ops.py restore-check \
  --snapshot /absolute/private/backups/snapshot-ID \
  --master-file /absolute/private/backups/snapshot-ID.master \
  --release FULL_SOURCE_SHA --target /absolute/new-instance
```

拒绝已有目标、symlink、未完成包、错 master、摘要/版本/schema 不符。原始配置不变；新目标 master 位于 `<target>/private/<active basename>`，0600、32 字节；仅将副本 service.json 的 `master_directory` 重绑定到 `<target>/private`，数据库 basename 与业务 schema 保持原样。用只读 SQLite 验证 integrity、记录归属和凭据 AESGCM 解密，不构造应用、不迁移、不启动 scheduler 或执行任务；同一源 release 的 schema 原样保存并核对。热 journal 需要写入恢复而只读无法打开时明确拒绝，先由产品正常打开恢复；不使用 immutable 跳过未完成事务。

结果 `offline_validation=passed` 只表示列明离线内容可校验。在线包的活动/缺失项仍不完整，所有恢复结果均 `automatically_startable=false`。手工启动前应核对源 release、冻结输入里的绝对路径/外部镜像、受理状态及中断任务处置；本工具不自动重写冻结任务或恢复执行，也不把离线校验当成可运行性验收。

## 两组用户级 timer

安装器把 ops.py 按内容哈希复制到 Git 外稳定私有目录，并建立固定 cryptography 版本的独立 venv。生成实例路径哈希命名的 check/backup service+timer，不覆盖不属于它的 unit；runtime 不引用工程 worktree。安装只管理这两组 timer，不管理 HTTP/scheduler。首次配置后重复安装幂等，已有同实例 oneshot 运行时先等待其结束再更新配置。

```bash
python3 scripts/install_ops.py install --directory /absolute/instance \
  --destination /absolute/private/ops-tool --backups /absolute/private/backups \
  --release FULL_SOURCE_SHA --enable
```

默认每五分钟巡检、每日在线备份；可用 `--check-calendar`、`--backup-calendar` 调整。先对专属合成实例安装、核 `systemd-analyze --user verify`、`systemctl --user list-timers` 和 journal 中的结构化结果，不能把文件生成当运行成功。查看 `systemctl --user status hh-ops-HASH-{check,backup}.{timer,service}` 和 `journalctl --user -u hh-ops-HASH-backup.service`。用户管理器须可用；用户退出后是否继续运行由部署者的 linger 策略决定。

用同一组参数将 `install` 换为 `disable` 可停用 timer，换为 `remove` 可停用并移除四个 unit；稳定工具/备份保留，不做目录级删除。启用现有实例 timer 前重新核对目标、release、路径权限与归属。现网服务的迁移、升级、自动重启与自动部署均不在这些 timer 中。

# 自动化验证与离线运维

统一入口是 `python scripts/verify.py`，Gitea Actions 调用相同脚本。它不部署或升级服务。需要 Linux `/proc`、pidfd、Python 3.12–3.13、uv、Node 22；浏览器所需系统库须由开发环境或 runner 镜像预先安装。首次运行：

```bash
python3 scripts/verify.py --prepare \
  --browsers /absolute/private/playwright-cache \
  --output /absolute/private/verification-new-directory
```

依赖按 `uv.lock` 和 `frontend/package-lock.json` 安装。`--prepare` 可以联网下载依赖/Chromium，不执行模型请求。依赖缓存可通过 `--dependency-cache` 指定，默认复用调用者 uv 缓存，运行缓存仍隔离。运行阶段使用环境白名单、独立 HOME/XDG/TMPDIR 和不含 Docker CLI 的工具 PATH，无可用 Docker socket；不会继承模型、Hub 或 CLI profile 凭据。`--browsers` 必须是绝对路径，不能位于测试临时 HOME。输出目录必须不存在；保留诊断时只选 `report.json`、`command-*.log`、`pytest.xml`，不得上传整个临时 HOME、state 或备份。

默认 `full` 运行 Python lint、契约、前端类型/lint/build、全部 pytest 和独占 UI fixture，强制 `HH_TEST_BROWSER=1`，要求 pytest skip=0 且两条生产网页用例通过。构建后对 tracked/untracked static 和契约检查 Git 漂移；发布物落后源码会失败。`--mode backend --python 3.13` 显式排除两条浏览器用例和前端/UI 检查，用于 Python 3.13 兼容检查，不能代替 full。`frontend/qa/live-service.mjs` 和 `final-integration-production.mjs` 是未接入此入口的手工脚本，不计为自动覆盖。此入口不证明真实 Docker、Hub、模型或发布环境可用。

UI 默认独占 4173，可以用 `--ui-port` 指定；已有 listener、缺浏览器、命令失败、生成物漂移均返回非零。输出记录固定 Git SHA、脏树状态、命令/版本、pytest 用例/skip、退出状态、精确回收记录。每次运行的唯一环境标记传给子树，包括 setsid 子进程；结束和 INT/TERM 时扫描 `/proc` 标记，以 PID birth 和 pidfd 回收，不按进程名或公共端口杀进程。整个监督入口被 SIGKILL/宿主宕机时自身无法清理，须由 CI 作业容器或外部监督者兜底；不能把这类情况说成 trap 已执行。

## Gitea 接入

`.gitea/workflows/verify.yml` 当前仅手动触发：远端 CI 未验证，用户决定后续手动验证。本轮 feature push 不主动运行远端任务。核验后可在 `on` 中加入 `push: {branches: ["**"]}` 与 `pull_request: {}`，使 feature 候选在集成前也能运行；不要只限制 dev/master。外来 fork PR 在 job 条件中拒绝，不使用 `pull_request_target`。普通 job 仅需仓库读权限，无生产凭据或自动部署步骤。`HH_RUNNER_LABEL` 仓库变量选择已核实可用的 label，未设置时使用 `ubuntu-latest`。上线 CI 前核 runner 在线/本仓可用范围、实际执行方式、宿主敏感挂载以及网络；label 名称本身不能证明容器隔离。

工作流通过 setup-python/setup-node/锁定版本 uv 准备工具，并安装 Playwright 系统库。不能 apt-install 的 runner 应事先准备系统依赖并按实际镜像调整该准备步。不要在 host runner 上执行外来 PR。Action 源、PyPI/npm/Playwright CDN、artifact 服务都须可达；本配置选择 upload-artifact v3，未使用未经实测的并发语法或缓存服务。Gitea 实际支持情况须由用户后续在固定候选 SHA 上的远端 run 证明；YAML 存在或本地通过均不能充作远端验收。核验顺序：确认 Actions 已启用与 runner 本仓可用，配置 HH_RUNNER_LABEL 并确认执行方式/网络/系统库，选择候选提交手动运行（或在该 feature 上显式启用 push 触发），核对 report.sha、full、skip=0、两条 browser_passed、无生成物漂移、UI 命令成功和 cleanup.remaining=[]，再保存 run 链接与 artifact。

## 只读巡检

使用稳定 Python 环境中的 cryptography 46.0.7；`scripts/ops.py` 不导入产品 Store/ServiceData，不做数据库迁移、启停或信号操作。

```bash
/path/to/python scripts/ops.py check --directory /absolute/instance \
  --backups /absolute/private/backups
```

实例采用 local_platform 的 `<base>/state`、`<base>/http.json` 布局。HTTP 需 PID/birth/argv/cwd 和 loopback listener 归属同时匹配才查询 health；alive 和 ready 分开报告，维护状态 alive=true、ready=false 不触发重启。scheduler 检查 birth/argv/state 和心跳年龄；无法确认标为 unknown。SQLite 仅以 `mode=ro` 和 query_only 查询；当前仅支持产品使用的 rollback journal，WAL 模式拒绝为 unsupported，避免只读连接创建/修改 shm。缺失备份时效是 null，不能推断已有备份成功。工具不会打开/展示主密钥内容，也不调用 controller start/restart/stop。目标路径必须显式指定；部署说明中的旧端口/PID不能作为当前事实。

## 在线快照与停写全量

备份输出须在 Git 和源实例之外的 owner-only 0700 目录。操作者明确提供与源配置对应的完整 release SHA（有 http.json 时还检查 code 的 release 目录名）。配置里的 master_file 必须在 state 外、非 symlink、当前 owner、0600、32 字节。

```bash
/path/to/python scripts/ops.py backup --directory /absolute/instance \
  --release FULL_SOURCE_SHA --output /absolute/private/backups --kind online
```

在线模式允许 HTTP、scheduler、worker 活着。限时获取**已有** control.lock，SQLite backup API 产生一致数据库副本，复制 service/team/limits/web/admission 配置、bundles、author-inputs 和 audit=clean 的终态 run 证据，前后检查摘要。活动 run 证据排除；preparing submission、活动 run、缺失 bundle/终态证据以及审计受限项写入 manifest。在线复制先非阻塞取得所选终态 run 的 evidence-locks 锁；锁忙返回 deferred，释放 control 后再由操作者重试。配置或不可变证据变化、symlink、锁超时均拒绝完成；`.incomplete` 目录不是可恢复备份。在线包始终 `full_state=false`，即使没有活动任务也只证明列明范围；scope=partial 必须保留到恢复结果。运行时日志/锁和未选择的 state 内容不在在线保证内。

快照 master 是包目录旁独立的 `snapshot-ID.master`，保持 0600，不在 state、manifest 或报告中输出密钥。该文件与快照一并留在受保护的私有存储；不能上传 CI artifact。没有自动保留清理，所有备份和未知文件均保留，容量由管理员监控。

完整快照只用于人工维护窗口：先在网页暂停新受理、等待/取消活动工作，再由**对应源 release** 的控制器安排停写。工具本身不启停服务。显式 `--kind offline` 才执行全写者门：HTTP/scheduler 身份、run PID、同 UID 进程 state argv/cwd/fd；无法观察即 busy/unknown。门在 control 锁内复制前后重查；scheduler.wake、scheduler-stop.json 和 evidence-locks 等瞬态控制记录不入离线快照，恢复也清除运行身份。持 FIFO fd 的进程同样属于 state 写者。禁止把 timer 变成自动停机工具。该观察要求同 UID 私有实例及可读 `/proc`；有跨用户写者、容器外不可见写者或外部进程能在观察后重新进入的环境，管理员必须在维护窗口另行隔离这些写者，不能仅凭此工具宣称全局无写入。

## 新目标离线恢复检查

```bash
/path/to/python scripts/ops.py restore-check \
  --snapshot /absolute/private/backups/snapshot-ID \
  --master-file /absolute/private/backups/snapshot-ID.master \
  --release FULL_SOURCE_SHA --target /absolute/new-instance
```

拒绝已有目标、symlink、未完成包、错 master、摘要/版本/schema 不符。原始配置不变；新目标 master 位于 `<target>/private/master.key`，0600、32 字节，副本 service.json 原子重绑定该绝对路径。用只读 SQLite 验证 integrity、记录归属和凭据 AESGCM 解密，不构造应用、不迁移、不启动 scheduler 或执行任务；同一源 release 的 schema 原样保存并核对。

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

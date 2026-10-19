# 网页版本与更新

页脚版本按钮显示运行进程的包版本、固定 release、生产构建摘要与已记录来源。直接源码运行只能展示可读取的 checkout 身份；没有安装来源记录时显示“来源未记录”。安装来源不会随着下一次更新配置而改变。构建时生成页面标记，页面与服务摘要不同时提示刷新。

更新只允许管理员浏览器会话操作，自动化凭证和成员不能升级。管理员主动检查、确认固定 SHA；浏览器关闭不影响执行。检查只读 Git 元数据，显示提交关系及适配契约结果，不代表已经完成数据适配。检查失败、未知关系、落后、分叉或撤回的目标均不能当作可更新版本。

## 一次性接入

先选定并验收支持本协议的固定 X 提交，从其独立源码目录运行以下命令。实例必须由 `scripts/service.py` 安装，原有 HTTP/scheduler unit 内容必须严格匹配；不接管外部 unit 或任意源码服务。

```bash
python3 /fixed-X/scripts/service.py upgrade --directory /private/instance \
  --source /fixed-X --close-admissions --mode wait
python3 /private/instance/manager/service.py enable-updates \
  --directory /private/instance \
  --repository https://git.example.org/team/harbor-helper.git --branch master
python3 /private/instance/manager/service.py start --directory /private/instance
```

从 bc64cd8 接入 X 的第一次主机升级仍使用旧升级流程，源版本不支持升级屏障，**这个一次性窗口不受重启保护**。先关闭受理、等任务自然结束，按旧安装的备份/恢复说明操作；不要在该窗口重新启动旧进程。初次主机升级保留关闭受理状态，管理员确认服务正常后在网页恢复受理。无需、也不能用 fresh-state 绕过数据不兼容。

`enable-updates` 严格核验整套 service/path/timer 的路径、完整内容与归属，再安装并启用 timer 和 path。仅允许精确识别的上一版自有 service 模板迁移；同名外部 timer 或未知内容拒绝接管。若 path 启动因 watch 资源失败，命令明确输出 path=failed、timer=active，保留事件主路径并依靠 timer 自动执行，不把失败的 path 报为通过。旧的已接入实例在固定新管理器主机升级后再次运行 enable-updates，才能安装这套兜底 unit；配置不会被覆盖。卸载先核验全套归属，再停用 timer/path/service。

`enable-updates` 不覆盖已存在的 `private/update.toml`：

```toml
[updates]
repository = "https://git.example.org/team/harbor-helper.git"
branch = "master"
```

文件需为当前服务账号所有、0600，位于 release 之外。仅支持 master（稳定）和 dev（测试），加入 dev 即选择测试通道。同一安装器支持两者。不要求分支尖端带 tag。本地绝对路径/file URL 仅适合离线合成验证；生产配置 HTTPS 或显式 `ssh://git@host/path.git`。

启用时把主机 PATH 中可执行、归属受保护的 uv 绝对路径固定在 owner-only 启用元数据中，运行时无需个人 PATH；uv 搬迁后应由部署者核验并更新该受保护路径。

执行器使用私有 HOME、清理后的环境和超时，不继承用户模型 key、Hub token、Git 配置或远程 CLI profile。HTTPS Git/uv 仅从 `private/network.json` 接收现有代理/TLS白名单。HTTPS 可由部署者提供 owner-only 可执行 `private/git-askpass`，凭据留在主机保护机制内；拒绝 URL 内嵌用户名/密码。SSH 使用 `private/deploy-key` 与固定 `private/known_hosts`（均 owner-only），BatchMode、严格 host key、单一身份，不交互接受未知主机。SSH 不把 HTTP 代理解释成跳板。真实 SSH 信任和凭据需要部署者预配置；不在网页输入 PAT。

配置仓库即信任其完整构建与运行代码，它以服务账号权限访问数据和主密钥。契约和探测用于兼容性检查，不能防护恶意仓库；同 UID 不是操作系统沙箱。升级健康不运行 Docker、Compose、Hub 或模型实验。

## 持久协议与数据窗口

`updates/spool` 接收有界动作，独立的本实例 systemd `.path` 激活 oneshot 执行器；本实例 `.timer` 每 10 秒检查同一执行器，作为 watch 配额耗尽和重启后的持久恢复兜底。两个触发源共用同一个 service，systemd 合并正在执行的激活，实例锁与请求幂等仍生效。timer 设置 1 秒调度精度，实际延迟受宿主调度影响；空闲 ExecCondition 仅读取受保护的 spool/journal，不构造 Store，不调用 Git/systemctl、不写业务或 journal。HTTP 不运行 Git/systemctl。`updates/journal.json` 位于 state 外，协议为 1；非终态一直占有实例，进程退出或锁释放不代表任务结束。宿主变更动作与网页维护/shutdown 操作不能抢占升级。重复 request_id 返回原任务；同一 request_id 不能改动作或目标。

正常顺序为固定目标准备、在线一致快照预探测、关闭新受理并等待、持久屏障、停写者与独占租约、完整离线备份及 restore-check、离线副本权威适配、显式迁移、版本与 unit 切换、屏障内验证、恢复原维护字段与原 unit 语义、持久 commit_decided、撤屏障、正常就绪检查、成功与 manager 集合激活。等待默认不取消实验；“取消升级”保留实验，“改为取消全部任务”不可撤销。屏障后的切换不能由浏览器强行中断。

HTTP 在 Store/Application/认证之前检查屏障；scheduler 初始化和循环同样检查。屏障期间只有静态页面、布尔 health、最小构建摘要和公共阶段可用。外部 journal 也保护两次恢复 rename 中暂缺的 state，不能由普通启动创建空 state。

副本探测把 release 与 master 路径绑定到副本，将冻结的原 state 绝对路径映射到副本，仅对副本做变换；遍历记录与本地材料，验证全部密文。在线预探测不包含所有活动材料，覆盖不完整不是完整适配通过。正式离线结果以完整快照为准。入口审计守卫拒绝网络连接和子进程，并拒绝读取原 state；这不是恶意代码沙箱。

分窗口核对源 state 清单、外部配置/key和无法观察的进程集合。迁移属于显式允许的写入，结束后记录新的基线；runtime 心跳/锁仅沿既有备份排除项处理。原位恢复在同一 base 内 staging，分别记录旧 state→failed、staging→state 两次 rename，保留失败现场、原 service 配置和外置 key/KCV。冻结路径重新落在原 base/state。独立 `ops.restore` 的产物仅用于检查，不能直接作为上线 state。

**显式迁移阶段崩溃策略为 needs_manual**，保留屏障、原快照和失败现场，不自动猜测部分迁移是否完成。可证明的切换前故障可恢复原位。commit_decided 必须在撤屏障前 fsync；一旦持久决定放行，后续故障不得用旧快照覆盖后来业务。放行后的 HTTP/scheduler 就绪失败保持 needs_manual。

## 宿主处理与回退

只读状态不应抢变更锁：

```bash
python3 /private/instance/manager/service.py upgrade-status --directory /private/instance
```

非终态阻止常规 start/stop/maintain/upgrade/uninstall/enable-updates。由有主机权限的管理员检查固定 job、屏障、state、原 key 和备份指纹后，选择受控动作：

```bash
python3 /private/instance/manager/service.py upgrade-resolve --directory /private/instance --resolution stop
python3 /private/instance/manager/service.py upgrade-resolve --directory /private/instance --resolution restore
python3 /private/instance/manager/service.py upgrade-resolve --directory /private/instance --resolution accept
```

timer 发现中断的非终态任务会自动唤醒恢复执行器；提交点后的收尾、manager 激活待办不依赖 spool 仍存在。已进入 needs_manual、未知协议或损坏 journal 时不反复自动推进，保留人工处理边界；宿主排除故障后可显式运行 `update-run` 或下面的 resolve 操作。

stop 保持安全停止；restore 仅在未 commit_decided 且屏障/指纹可证明时重试本任务的原位恢复；accept 用当前固定 release 实际验证数据库、配置、密钥及 HTTP 共用构造路径后才决定放行。验证失败不会自动接受。迁移崩溃时，先用 upgrade-status 取得屏障内 state_digest，检查任务与快照、没有外部写者且外置 key/config 指纹一致，再用 `upgrade-resolve --resolution restore --expected-state-digest <刚核对的摘要>` 明确接受本任务中断迁移的当前指纹并恢复原快照。此参数仅适用于 journal 记录的中断迁移，不能绕过 commit_decided。外部指纹不符时仍拒绝恢复，不能删屏障、重新初始化或随手覆盖快照。

含屏障快照人工恢复后，即使原任务已终态，残留标记也拒绝普通业务。保留原外部 journal 与实例归属，通过本任务 `upgrade-resolve --resolution accept` 在完整验证后受控清除；缺少原 journal 时不能自动清除，需按离线恢复流程重建可审计的任务关联并人工验核。提交点后的任务只能接受/完成当前固定版本或安全停止，不能 restore。

manager 以 `manager/sets/<sha>` 保留完整集合，用普通 `current.json` 原子激活，稳定 `manager/service.py` 入口不逐文件更新。业务成功后才切换 manager；pending 激活在恢复执行器中幂等完成，未知协议停止自动推进。旧集合和唯一备份不自动回收。

本实例自有备份 timer 通过 instance.json 解析当前 release，升级 busy 时跳过。一次性启用更新时只迁移能严格识别归属与命令的旧 timer，保留原 calendar；未知命令拒绝接管，应由部署者先处理外部写者。升级不管理无归属服务或 Docker 资源。

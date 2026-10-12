# 独立验收报告：额度与维护

## 结论

**固定候选限定 PASS**：`6db930d37b7e0f78e20fe3ec8221357b286b6352`，分支 `feature/member-admission-maintenance`。结论只覆盖本报告列明的隔离检查；不代表候选全量 Python/UI/build 通过或真实外部执行成功。

产品/测试基点 `b5c409b20ba8cfe8bf3a7d7e37525ca4b7ff0c3c`；本轮核对 `src/ frontend/ tests/` 在该基点至候选的 diff 为空。受保护主树仍为 `master 9451363155674f138123c94c5e1ba51687139b36`，未合入/修改主树或部署。

## 过程和证据

- 开始前核对主树/候选引用，读取 `AGENTS.md`、`docs/HANDOFF.md`、`.local/LOCAL_ENVIRONMENT.md`；保护正式服务、旧CLI state、master、密钥和镜像。候选设计契约及两份工程报告仅用于确定检查范围/风险，不当作验收证据。
- 在 `/tmp/hh-checker-admission-6db930` 新建候选 SHA 的 detached worktree；独立 HOME、XDG、Harbor profile、uv/npm cache 和测试 state。所有命令经 `env -i` 白名单运行，未继承模型/Hub凭据、代理或 Docker 配置。假 master/PAT/团队密钥和 fixture 均由测试新建，外部调用限制为本机 HTTP、fixture source/worker；没有 Hub、Docker/Harbor 容器、Oracle 或模型请求。
- Python 3.12.3 / uv 0.11.31 按锁文件装 dev 依赖；Node 22.23.1 按 `frontend/package-lock.json` 执行 `npm ci`。浏览器使用机器上已有 Playwright Chromium，只读浏览器安装；浏览器 context 与 HOME 独立。
- `tests/test_admission.py`、`tests/test_admission_http.py`、`tests/test_admission_numbers.py`：**36 passed, 1 skipped**（跳过项是显式 opt-in 的浏览器案例，随后单独执行）；输出见 `capture/focused-pytest.*`。单独生产 UI：**1 passed**，见 `capture/browser-pytest.*` 与截图。
- 证据目录内 `capture/` 保存原命令 JSON、原 stdout/stderr 字节文件、退出码、两 HTTP 进程日志、CLI 原始捕获（测试记录的 stdout/stderr 文本）、teardown、截图及 SHA-256 索引。状态目录 `state/` 保留隔离 fixture state 供复核，未纳入哈希清单或入库。关键命令环境和外部服务界限列在各 `*.command.json`。

## 覆盖结果

| 主题 | 本轮观察 | 证据性质 |
| --- | --- | --- |
| 同成员额度、身份隔离、并发/幂等、降低额度 | Web/PAT同成员共享额度、另一成员可提交、管理员计入本人额度；8路相同键只建一个受理、8路不同键仅两项通过；降额不取消旧项，旧键仍找回 | 隔离 TestClient/fixture；非真实团队数据 |
| preparing→run发布窗口、legacy身份 | target已关联queued/active/终态run时不重复计；可靠身份缺失时不按manifest用户名猜成员，但保留全局pending/执行限制 | 合成SQLite/run/manifest fixture，未改历史真实state |
| 维护锁、跨进程可见和排空 | 两个实际本机HTTP进程读取同一隔离state；暂停后第二进程立即观测到暂停并拒新键、旧键仍返回原对象。真实 CLI subprocess 经 HTTP 受理；暂停期间 CLI 新键退出1/503；解除准备hold后 fixture scheduler/worker 排空，报告的有效分数为零；scheduler停掉时身份变 unavailable，旧键仍可查，恢复维护不能越过unready，scheduler重启后新任务完成 | 本机实际HTTP/CLI/scheduler进程；source、Harbor执行、评分 worker是 fixture，不是外部执行 |
| 重开/恢复、授权顺序 | 新 Application 重开仍读到暂停；read-only PAT不能提交；管理员PAT不能写维护但能安全读取；旧幂等键优先于暂停/就绪限制；暂停阻止 submit/rerun/retry/recover 新受理 | 隔离 fixture。实际HTTP两进程路径见上一行 |
| scheduler与readiness | 实际scheduler出生身份/heartbeat新鲜时ready；缺文件、陈旧heartbeat、错误birth、未来的有限大时间戳及 bool/NaN/±inf/±10**400 损坏数值均不能误报ready；匿名 health 仅 alive/ready；成员 readiness 不暴露路径/PID/birth/config/master/ciphertext | 真实scheduler在HTTP串联中运行；破坏/边界字段为合成 fixture |
| 数值安全 | 无效维护 retry 请求返回422且不改状态；retry_at/updated持久字段坏值返回503、health false、新受理拒绝，旧键仍能取回；`10**300`可保存读取、不施加任意上限 | 路由/序列化及隔离持久state；没有用生产state |
| 前端实际使用 | 实际生产构建静态页面由本机HTTP提供；管理员设置成员额度3、暂停/原因/建议时间、刷新后仍显示，随后恢复；成员浏览共享实验看到安全维护提示且没有恢复控件；390×844无横向溢出。截图由本轮人工查看 | 本机HTTP + Playwright Chromium；fixture账户/state |
| 旧 limits 兼容 | 合成旧 limits 缺成员额度时使用默认值并受全局限额约束；测试核对DDL、密文行、历史manifest与state外假master字节/模式不变 | 完全合成fixture；不是迁移真实旧团队state |

测试 helper 的原始 CLI 输出以 `http-cli-jsonl.txt` 保存为JSON记录（含具体参数、stdout、stderr、exit；不含PAT原值）；teardown JSON确认两个HTTP/scheduler进程退出且worker birth释放。最终独立进程扫描未发现本轮 worktree 命令或测试端口相关残留。

## 限制 / 未覆盖

- 未运行候选全量 327 Python / 29 UI、完整 frontend build/lint 或全量回归；之前工程报告的覆盖不能升格为本候选全量通过。
- 并发争用部分基于本机锁/SQLite及fixture；未验多主机共享文件锁、断电/fsync灾难恢复、大量历史记录性能或公平调度。
- 无真实 Hub、Docker、Harbor/Oracle容器、模型、网络代理、HTTPS/生产升级/备份恢复；fixture 成功只证明本地状态与契约串联。没有验证金额预算或模型效果。
- 浏览器引擎来自当前机器已有安装，不属于候选依赖锁文件；没有改全局浏览器或用户配置。
- 可表示极大有限数值无任意上限是实现约定；业务层时间合理性仍按未来时间校验，scheduler未来活动显示unknown。

## 清理审计

本次独立 worktree `/tmp/hh-checker-admission-6db930`、HOME/profile/cache 和 fixture state 均在主树外；fixture teardown 证明已终止本次 HTTP/scheduler/worker。未停止或操作任何已有服务，未触碰正式 state/master、Docker镜像/cache、用户级配置。审计 state 为假账户和假凭据，仅保留在 `/tmp/hh-checker-admission-6db930-evidence/state/`；主仓仍无本轮提交。

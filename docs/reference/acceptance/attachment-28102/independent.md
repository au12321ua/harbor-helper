# 附件版本生命周期独立验收

**结论：PARTIAL（有界代码与真实 Web HTTP 范围通过；真实 Docker/Harbor/Oracle 执行缺证据）**

## 固定版本与边界

- 候选：`28102da47acfae696cf8cce1e8f42dee057944a9`；实时 `git ls-remote` 对 `origin/feature/engineer-attachment-lifecycle` 返回同一 SHA。
- 产品实现：`5d1734b0ee8f04b1314cf614e5496c11887bbeeb`。后续 merge `d935969257c2184eb3d9514823622764e078db9e` 只改变 `docs/design/attachment-agent-contract.md`。
- 独立 detached worktree：`/tmp/hh-attachment-check-28102`；独立 HOME、uv/npm cache、HTTP state 和外置 master。所有账户、密码、附件和测试密钥为本次生成的假值。继承的环境凭据没有传入依赖、测试或服务进程。
- 没有修改产品源码，也没有使用正式 `8768`、`.state/web-service`、`.state/team`、真实密钥或真实模型请求。独立 Python 验收只运行 `tests/test_attachments.py`，不把工程报告的 274 项全回归作为本结论。

## 通过的范围

### 服务与数据契约

独立运行 `tests/test_attachments.py`：**19 passed，1 个 Starlette/httpx 弃用警告**；`ruff check src tests` 通过。覆盖包括：

- 创建/发布/派生权限；不可变 v1/v2、并发序号、相同语义不同 ZIP 压缩的幂等查回、同键冲突、跨成员查回隔离、旧 bundle 唯一登记与停用。
- 当前提交者和访问身份用于 rerun/retry/recover；继承冻结附件谱系，未知历史保持 `legacy/unknown`；停用阻止新受理，父快照和既有受理不被追认/改写。
- 当前请求原值、可识别前缀、二进制/跨读取块/历史快照泄漏检查；后台只作格式检查；错误/输出流脱敏。校验失败不污染幂等键。
- 准备阶段重新验证摘要/格式；损坏字节变为 `unavailable` 并导致准备失败，不替换旧版本。进程在事务提交前/后退出时，SQLite 可见表要么全无、要么完整；原键恢复不会产生重复版本。
- 真实 HTTP 路由测试覆盖成员共享读取、他人按键查回拒绝、非所有者发布拒绝、bundle/version 互斥，以及附件类型错误。独立 subprocess 远程 CLI 测试启动 loopback uvicorn，以假 profile 执行 HTTP `attachments create/lookup/publish/list` 和 Oracle 受理，检查 bearer 不进入 CLI 输出。
- 无附件/v1/v2 比较保留 `bundle_change` 与冻结版本身份；Oracle fixture 的同任务评分可比，改变 agent、attempts、wall time 或 verifier ref 会拒绝比较。后登记旧 bundle 不追认旧实验。

这些是隔离测试与 fixture/Oracle 服务逻辑证据，不是 Harbor 实际执行、真实评分器或模型效果证据。

### 真实隔离 HTTP 与生产构建页面

- `npm ci`、Vite production `npm run build`、`npm run lint` 均通过；构建生成 `index-DtkVgAK7.js`。构建后 `git status` clean，`static/` 与固定提交字节相同。
- 在 `127.0.0.1:18762` 用生产 static 启动独立服务；真实 Chromium 浏览器完成首次网页设置、管理员登录、邀请 Alice/Bob。Alice 在 Web 新建 v1、发布 v2 并派生；Bob 共享读取 Alice 的两个版本、没有 Alice 附件的维护按钮，并从 v1 派生自己的版本。Alice 从新建实验页选择 v2，再通过“清除附件，使用无附件基线”回到无附件。证据截图见 `evidence/`。
- 上述真实页面只完成选择与清除，没有提交实验：隔离服务未配置可用数据集，页面明确显示“团队尚无可用数据集”。远程 CLI 到 HTTP 的受理契约由前述测试覆盖，不能把它写成生产服务中的真实受理。

### 迁移与回退

以旧产品代码 `9451363155674f138123c94c5e1ba51687139b36` 创建一次性旧 schema 状态，放入 fake AES-GCM credential row 和 state 外生成的 fake master；再用候选 `ServiceData` 打开。逐表比较旧表 DDL 与内容（包含密文行），均相同；只有 `attachments`、`attachment_versions`、`attachment_operations` 三表新增；外置 master 字节保持不变。此为合成隔离迁移证明，不是正式团队 state 的备份/迁移演练。

附件指南明确旧代码忽略新表不构成安全业务回退，并禁止删新表/回放旧 WAL/用旧备份覆盖新数据。本次只审阅该说明，没有执行代码回退。

## 未覆盖与阻塞证据

**实际 Docker/Harbor/Oracle 小验证未执行。** Docker daemon 可访问（版本 29.8.2；只读 `info` 报告 20 CPU、67,128,709,120 bytes 内存；只读 `ps` 无运行容器），但本次没有可安全注册的公开固定任务与作者环境。仓库 `docs/guides/local-operations.md` 明确把唯一找到的 `au12321ua/harbor-helper-switch-smoke@1` 称为**私有**数据集，并要求其他账号取得 Hub 权限。按任务边界没有试探下载、使用已有真实 Hub 权限、拉镜像或猜测可替代任务，也没有改评分器/答案造出附件差异。

因此没有完成任务作者/作者环境的身份核验、任务级资源预算登记、Harbor 任务、无附件/v1/v2 实际对照、真实安装字节确认及安全报告/清理审计。Docker 只做只读可用性检查；未创建容器、pull/build image、改动镜像或 cache。该前置缺失使整体只能为 PARTIAL，不能声称第 6 项或产品阶段完整通过。

同时未验证真实成员的生产实验受理、损坏文件的真实 HTTP 展示、跨浏览器/规模性能、文件系统断电损坏、正式数据库/外置密钥恢复、自动化签发/三轴/额度/skill，也未验证任何真实研究 agent 或 LLM 效果。

## 清理与复现

- HTTP 服务用 Ctrl-C 正常停止；对精确隔离 state 调用 `stop_supervisor` 返回 `{"scheduler":"stopped","confirmed":true}`。
- 停止后 `127.0.0.1:18762` 无 listener；隔离 DB 中 submissions=0、runs=0；Docker `ps` 无容器。没有遗留任务需要取消。
- 构建、测试未改候选 tracked 文件；没有操作主树、正式 state、镜像、volume、全局 cache/prune 或远端 refs。
- 主要复现：在候选 detached worktree 执行 `uv sync --locked --group dev`；以 `env -i` + 隔离 HOME/cache 运行 `.venv/bin/pytest -q tests/test_attachments.py`、`.venv/bin/ruff check src tests`；在 `frontend/` 运行 `npm ci`、`npm run build`、`npm run lint`。浏览器截图是隔离服务生产 HTTP 页面；测试日志随报告保留。

## 证据索引

- `evidence/python-attachments.log`
- `evidence/ruff.log`
- `evidence/frontend-build.log`
- `evidence/frontend-lint.log`
- `evidence/real-http-new-experiment.png`
- `evidence/real-http-member-shared.png`

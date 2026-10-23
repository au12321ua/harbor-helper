# 源码职责

重写中的新代码在 `src/maestro/`；`src/harbor_helper/` 只剩尚未重写、留待后续里程碑移植的基线模块。前端源码在 `frontend/`，构建到 `src/maestro/static/`。本页描述当前代码的分工，不约束设计；设计以 [重写目标设计](../design/README.md) 为准。

## Maestro（新代码）

| 板块 | 位置 | 职责 |
| --- | --- | --- |
| 入口 | `cli.py`、`config.py`、`application.py` | `maestro init / db upgrade / serve / openapi`；读取 `config.toml`；组装数据库、边界与服务 |
| 基础 | `core/` | 不透明 ID、UTC 时间文本、规范 JSON 与 `sha256:` 摘要、统一错误、请求上下文、单实例锁 |
| 数据库 | `db/schema.py`、`db/engine.py`、`db/migrate.py`、`db/migrations/` | 01 的逻辑表；SQLite WAL / 外键 / busy_timeout；写事务一律 `BEGIN IMMEDIATE` 短事务；Alembic 迁移 |
| 领域 | `domain/states.py`、`domain/scoring.py`、`domain/limits.py` | 运行 / 试次 / 尝试 / Operation 状态与四个独立维度、聚合规则；评分契约与运行汇总（计数、覆盖率、均值、标准差、通过率、任务均值）；团队策略的内置初值（修订 0）与结构性常量 |
| 安全 | `security/` | Argon2id 密码、带前缀的随机令牌与摘要、CSRF 派生、主密钥代次与轮换、AES-GCM、基本脱敏 |
| 业务服务 | `services/` | 账户 / 初始化 / 邀请 / 会话 / 认证，PAT，凭据，权限矩阵（`principal.py`），审计，幂等，Operation，目录读取（准入、内容可得性与本机缓存分开报告，`catalog.py`），数据源搜索与数据集管理（`datasets.py`），导入、首次准备、共享缓存恢复、回收与重启对账（`preparation.py`），团队策略修订（`policy.py`），模型配置与 Harness 版本（`model_configs.py`），配置解析：分层合并、字段来源、阻塞项与受理前复核（`configuration.py`），运行受理 / 查询 / 取消，运行汇总（`results.py`），产物索引、分段读取、到期回收与启动对账（`artifacts.py`），批量导出（`exports.py`），两步删除与回收站（`recycle.py`、`deleted.py`），磁盘水位（`disk.py`），导出构建与回收的维护循环（`maintenance.py`），进程内运行级 Worker，执行容量与提供商并发（`capacity.py`），实例标识 |
| 边界 | `boundaries/` | 数据集来源、实验执行器、运行环境、文件存储四个接口；业务层只见这些平台类型 |
| 执行 | `execution/` | 模型协议、Harness 参数与配置中秘密的检查（`agents.py`）；Harbor 执行器（启动 Runner 子进程、解析协议、上传产物）、平台错误策略与 Harbor 0.24.0 异常映射、Runner 进程身份、按标签清理 Docker；Hub 数据源（经 Runner，`hub.py`）；Docker 准备环境（可复现构建或固定拉取、导出原件、载入或重建并核对镜像 ID，`preparation.py`）；按上游摘要存放并按材料摘要校验的任务材料、任务检查与作者参数发现、准备规格，以及开发用本地任务来源（`materials.py`） |
| Runner | 仓库根目录 `runner/` | 单独的 uv 项目，锁定 Harbor；一个运行对应一个 Harbor Job，经 stdout 的 JSON 行协议上报步骤、日志和每次尝试的结果；另有 Hub 目录命令（搜索、版本、解析、按 digest 下载并核对，`hub.py`） |
| 测试替身 | `testing/fakes.py` | 四个边界的假实现，供测试和 `serve --demo-executor` 演示 |
| HTTP | `api/` | FastAPI 应用、`{data, meta}` 外壳与结构化错误、会话 cookie + CSRF 与 PAT Bearer 认证、路由、公开模型、OpenAPI 导出 |

## 尚未重写的基线模块

| 位置 | 内容 | 预计由谁替换 |
| --- | --- | --- |
| `harbor_helper/execution/config.py` | 旧团队配置与模型参数校验（秘密检查已移植到 `execution/agents.py`） | M5 第二段 |
| `harbor_helper/security/`、`persistence/files.py` | 旧凭据、脱敏与文件工具 | 随上述模块一并删除 |

基线的 HTTP 服务、JSON 状态、CLI 与本机启动脚本已在 M2 删除（见 [14](../design/14-decisions.md) 的 M2 实施记录）；需要参考时读 `9ff43b5`。

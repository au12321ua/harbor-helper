# 源码职责

重写中的新代码在 `src/maestro/`；`src/harbor_helper/` 只剩尚未重写、留待后续里程碑移植的基线模块。前端源码在 `frontend/`，构建到 `src/maestro/static/`。本页描述当前代码的分工，不约束设计；设计以 [重写目标设计](../design/README.md) 为准。

## Maestro（新代码）

| 板块 | 位置 | 职责 |
| --- | --- | --- |
| 入口 | `cli.py`、`config.py`、`application.py` | `maestro init / db upgrade / serve / openapi`；读取 `config.toml`；组装数据库、边界与服务 |
| 基础 | `core/` | 不透明 ID、UTC 时间文本、规范 JSON 与 `sha256:` 摘要、统一错误、请求上下文、单实例锁 |
| 数据库 | `db/schema.py`、`db/engine.py`、`db/migrate.py`、`db/migrations/` | 01 的逻辑表；SQLite WAL / 外键 / busy_timeout；写事务一律 `BEGIN IMMEDIATE` 短事务；Alembic 迁移 |
| 领域 | `domain/states.py`、`domain/limits.py` | 运行 / 试次 / 尝试 / Operation 状态与四个独立维度、聚合规则；D-011 初值 |
| 安全 | `security/` | Argon2id 密码、带前缀的随机令牌与摘要、CSRF 派生、主密钥代次与轮换、AES-GCM、基本脱敏 |
| 业务服务 | `services/` | 账户 / 初始化 / 邀请 / 会话 / 认证，PAT，凭据，权限矩阵（`principal.py`），审计，幂等，Operation，目录读取，运行受理 / 查询 / 取消，产物索引，进程内运行级 Worker |
| 边界 | `boundaries/` | 数据集来源、实验执行器、运行环境、文件存储四个接口；业务层只见这些平台类型 |
| 测试替身 | `testing/fakes.py` | 四个边界的假实现，供测试和 `serve --demo-executor` 演示 |
| HTTP | `api/` | FastAPI 应用、`{data, meta}` 外壳与结构化错误、会话 cookie + CSRF 与 PAT Bearer 认证、路由、公开模型、OpenAPI 导出 |

## 尚未重写的基线模块

| 位置 | 内容 | 预计由谁替换 |
| --- | --- | --- |
| `harbor_helper/execution/agents.py`、`environments.py`、`agent_tools.py`、`processes.py` | Harbor Agent / Docker 环境包装、工具准备、进程身份 | M3 |
| `harbor_helper/execution/config.py`、`sources.py`、`author_inputs.py` | 任务下载、内容摘要、作者参数 | M4、M5 |
| `harbor_helper/results/` | 评分与展示 | M6 |
| `harbor_helper/security/`、`persistence/files.py` | 旧脱敏与文件工具 | 随上述模块一并删除 |

基线的 HTTP 服务、JSON 状态、CLI 与本机启动脚本已在 M2 删除（见 [14](../design/14-decisions.md) 的 M2 实施记录）；需要参考时读 `9ff43b5`。

# 开发交接

本页是重写分支 `feature/rewrite` 的维护入口。分支从 `9ff43b5` 开始，按[重写目标设计](design/README.md)整体重写，完成后替换 `dev` 上的现有实现。分支规则见[分支、协作与发布规则](guides/development-workflow.md)的“重写分支”一节。项目改名为 Maestro，新代码使用 `maestro` 包；不再使用 botmux 协调，用户决定记录在[决策记录](design/14-decisions.md)第 0 节。

## 需求与设计

- 需求基线是[需求整理与审查](design/requirements-review.md)（审计稿）；00～15 模块文档是它的延伸设计。
- 实践优先：实现中发现更好的做法或设计有问题时，先在[决策记录](design/14-decisions.md)记录，再同步修改模块文档。
- 用户决定与冲突结论见决策记录第 0 节；尚未定论的冲突，确认之前不按任何一方擅自实现。

## 进度

- M0、M1 已于 2026-10-22 完成。M1 的结论、样例与版本见[决策记录](design/14-decisions.md)的“M1 验证记录”；原型代码与原始证据在主仓 `.local/`。
- M2 地基已实现（2026-10-22）：新包 `src/maestro/`、最简网页与测试；实现中的选择与未覆盖范围见决策记录的“M2 实施记录”。
- M3 执行内核已实现（2026-10-23）：独立 Runner 环境（`runner/`，锁定 Harbor 0.24.0）、协议、错误策略映射、实时步骤与日志、取消、按标签清理、重启对账和容量。选择与未覆盖范围见决策记录的“M3 实施记录”。
- M6 结果与产物已实现（2026-10-23）：评分汇总与覆盖率、产物到期与回收、启动对账、批量导出、磁盘水位、两步删除与回收站。按用户安排 M5 暂时跳过，M4 在另一会话并行；M6 中依赖它们的部分（管理员确认的评分契约、删除数据集版本时回收准备缓存、凭据与运行的绑定）见决策记录的“M6 实施记录”。
- M4 数据集与准备已实现（2026-10-23，与 M6 并行，合并在 M6 之后）：Hub 数据源（经 Runner）、管理员导入与首次准备、按任务的准入、内容可得性与本机缓存分开记录、平台自己构建或拉取并导出原件（U-17）、共享恢复（租约、代次、等待者、pin）、恢复失败计为试次的执行尝试、手动回收、重启对账、作者参数与评分契约确认，以及数据集页。选择与未覆盖范围见决策记录的“M4 实施记录”。M5 仍待做。

## 代码状态

- 新代码在 `src/maestro/`，Runner 在 `runner/`（单独的 uv 项目和锁文件），测试在 `tests/maestro/`；分工见[源码职责](architecture/source-layout.md)。`src/harbor_helper/` 只剩 M5 要参考的旧团队配置与安全模块；服务环境已不安装 Harbor，这些文件不能再导入，也不进入发布包，参考完即删。
- 重写过程中允许无法部署。按模块替换，新模块就绪后直接删除对应的基线代码和测试，不保留新旧并行、转发层或兼容分支。
- 不承诺向后兼容，不迁移旧 state，新实现从空实例初始化。对外 HTTP、SDK、CLI 契约随重写修改。
- 可移植的基线与 `dev` 代码见[实施计划](design/13-testing-plan.md)第 2.3 节。移植时先读原代码，按新设计重写接口。

## 验证入口

需要 Linux、Python 3.12–3.13 和 uv；实际执行另需 Docker/Compose、可用作者依赖与 Hub 权限。依赖由 `pyproject.toml`、`uv.lock`、`frontend/package-lock.json` 记录。

- Python：`uv sync --locked --group dev`、`uv run pytest -q`、`uv run ruff check src tests runner/src`；新代码另跑 `uv run ruff format --check src/maestro tests/maestro runner/src`。
- Runner：在 `runner/` 执行 `uv sync --locked`。真实 Docker 测试需显式开启：`MAESTRO_DOCKER_TESTS=1 uv run pytest -q tests/maestro/test_harbor_docker.py`。它只用本地 Oracle 任务和已有的 `ubuntu:22.04`，需要 buildx，不调用模型和 Hub；执行资源都带每个测试独立的实例标签，准备好的镜像在每个实例自己的 `maestro-prep/<实例>` 仓库名下，结束时都核对清空。真实 Hub 测试另需 `MAESTRO_HUB_TESTS=1 uv run pytest -q tests/maestro/test_hub_live.py`：匿名读取公开的 `harbor/hello-world`，导入测试会真实构建（基础镜像可能被拉取）；Runner 继承代理变量，但不支持 SOCKS 代理变量（`ALL_PROXY`）。
- 数据库：`schema.py` 与最新迁移须一致（`tests/maestro/test_migrations.py` 检查）。首个发布前没有已部署的 schema，`0001` 可以随 `schema.py` 重新生成；发布后只追加迁移。并行分支都改了 `schema.py` 时，合并后在合并结果上重新生成 `0001`。
- 实例：`maestro --config <config.toml> init / db upgrade / serve / openapi`；示例配置与试用步骤见根目录 README。
- 前端：在 `frontend/` 执行 `npm ci`、`npm run build`、`npm run lint`；build 写入 `src/maestro/static/`。
- 验证使用独立 HOME、state 和主密钥，隔离 Harbor/profile，并清除继承的真实凭据环境。测试含本地子进程，不能默认没有副作用。真实 Hub、Docker、模型请求与 fixture 验证分开记录；真实模型请求须核对当前授权与预算。
- 重写后的验收场景见[测试验收与实施计划](design/13-testing-plan.md)。验证命令和门禁随重写调整，以本页为准。

现场报告与原始证据只保存到主仓 ignored `.local/`；公开文档只留短的固定代码版本、实际覆盖与未覆盖范围摘要。集成后的 worktree 和短期分支按协作规则收尾。

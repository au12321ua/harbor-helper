# 开发交接

本页是重写分支 `feature/rewrite` 的维护入口。分支从 `9ff43b5` 开始，按[重写目标设计](design/README.md)整体重写，完成后替换 `dev` 上的现有实现。分支规则见[分支、协作与发布规则](guides/development-workflow.md)的“重写分支”一节。项目改名为 Maestro，新代码使用 `maestro` 包；不再使用 botmux 协调，用户决定记录在[决策记录](design/14-decisions.md)第 0 节。

## 需求与设计

- 需求基线是[需求整理与审查](design/requirements-review.md)（审计稿）；00～15 模块文档是它的延伸设计。
- 实践优先：实现中发现更好的做法或设计有问题时，先在[决策记录](design/14-decisions.md)记录，再同步修改模块文档。
- 用户决定与冲突结论见决策记录第 0 节；尚未定论的冲突，确认之前不按任何一方擅自实现。

## 进度

- M0、M1 已于 2026-10-22 完成。M1 的结论、样例与版本见[决策记录](design/14-decisions.md)的“M1 验证记录”；原型代码与原始证据在主仓 `.local/`。下一步是 M2 地基。

## 代码状态

- `src/`、`frontend/`、`tests/` 中尚未重写的部分是基线代码，行为见[Web服务指南](guides/web-service.md)和[源码职责](architecture/source-layout.md)。这些文档随模块重写而更新或删除。
- 重写过程中允许无法部署。按模块替换，新模块就绪后直接删除对应的基线代码和测试，不保留新旧并行、转发层或兼容分支。
- 不承诺向后兼容，不迁移旧 state，新实现从空实例初始化。对外 HTTP、SDK、CLI 契约随重写修改。
- 可移植的基线与 `dev` 代码见[实施计划](design/13-testing-plan.md)第 2.3 节。移植时先读原代码，按新设计重写接口。

## 验证入口

需要 Linux、Python 3.12–3.13 和 uv；实际执行另需 Docker/Compose、可用作者依赖与 Hub 权限。依赖由 `pyproject.toml`、`uv.lock`、`frontend/package-lock.json` 记录。

- Python：`uv sync --locked --group dev`、`uv run pytest -q`、`uv run ruff check src tests`。
- 前端：在 `frontend/` 执行 `npm ci`、`npm run build`、`npm run lint`；build 会更新包内 static。
- 验证使用独立 HOME、state 和主密钥，隔离 Harbor/profile，并清除继承的真实凭据环境。测试含本地子进程，不能默认没有副作用。真实 Hub、Docker、模型请求与 fixture 验证分开记录；真实模型请求须核对当前授权与预算。
- 重写后的验收场景见[测试验收与实施计划](design/13-testing-plan.md)。验证命令和门禁随重写调整，以本页为准。

现场报告与原始证据只保存到主仓 ignored `.local/`；公开文档只留短的固定代码版本、实际覆盖与未覆盖范围摘要。集成后的 worktree 和短期分支按协作规则收尾。

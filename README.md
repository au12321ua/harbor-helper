# Maestro

> 本分支 `feature/rewrite` 正在按[重写目标设计](docs/design/README.md)把 harbor-helper 整体重写为 Maestro，尚不能用于真实实验。正式使用请以 `dev` 或发布版本为准。

Maestro 让受邀的可信团队通过网页和 SDK 提交、观察、比较和重跑基于 Harbor 的实验：数据集可选择，实验配置固定，结果全团队共享，提交身份保留。

## 当前状态

已有地基（M2）：数据库与迁移、账户 / 邀请 / 会话 / PAT、凭据与主密钥轮换、受理事务与幂等、Operation 与审计、运行级 Worker 与四个边界的测试替身、公开 OpenAPI 和最简网页。真实执行器（Harbor Runner）、数据集导入与准备、配置解析等尚未实现，见[实施计划](docs/design/13-testing-plan.md)第 2 节。

## 本机试用

需要 Linux、Python 3.12–3.13 和 uv；网页需先在 `frontend/` 执行 `npm ci && npm run build`。使用全新的独立目录，不要指向已有团队 state：

```bash
uv sync --locked
root=$(mktemp -d)
cat > "$root/config.toml" <<EOF
data_dir = "$root/data"
cache_dir = "$root/cache"
master_key_dir = "$root/secrets"
cookie_secure = false
EOF
uv run maestro --config "$root/config.toml" init      # 打印一次性初始化令牌
uv run maestro --config "$root/config.toml" serve --port 8420
```

打开 `http://127.0.0.1:8420`，用初始化令牌创建首个管理员。没有执行器时服务如实拒绝受理运行；开发演示可加隐藏参数 `--demo-executor`，它使用假执行器和一个演示数据集，结果不是真实实验。

### 用 Harbor 真实执行（Oracle 测试模式）

Harbor 装在单独的 Runner 环境里，服务本身不加载 Harbor。需要 Docker 和本机已有的 `ubuntu:22.04` 镜像：

```bash
(cd runner && uv sync --locked)                       # 锁定 Harbor 0.24.0
echo "runner_python = \"$PWD/runner/.venv/bin/python\"" >> "$root/config.toml"
uv run maestro --config "$root/config.toml" dev-local-dataset oracle tests/maestro/fixtures/harbor-tasks
uv run maestro --config "$root/config.toml" serve --port 8420
```

`dev-local-dataset` 是开发用的隐藏命令，在 M4 的 Hub 导入完成前，把本地任务目录登记为已准入数据集。目前只有 Oracle 测试模式：执行任务自带的参考解法，不调用模型。运行页能看到每个试次的步骤、耗时和实时日志。

`cookie_secure = false` 只用于本机 HTTP；对外部署由反向代理提供 HTTPS，并保持默认的 `true`。

## 文档

- [文档导航](docs/README.md)、[开发交接](docs/HANDOFF.md)、[源码职责](docs/architecture/source-layout.md)。
- 公开 API：服务的 `/api/v1/openapi.json`，或离线 `uv run maestro openapi`。

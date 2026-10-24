# Maestro Web

Vite + React + TypeScript + shadcn/ui (Radix) + Tailwind CSS。生产页面与 `/api/v1` 由同一 HTTP 服务（`maestro serve`）提供，不需要单独域名或跨域配置。

```bash
npm ci
npm run build      # tsc -b + vite build，输出到 ../src/maestro/static/（构建结果随源码提交）
npm run lint
npm run gen:api    # 由 ../openapi/maestro-v1.json 生成 src/lib/schema.d.ts
npm run check:api  # 检查生成的类型与契约一致（CI 也会检查）
```

开发时 `npm run dev` 把 `/api` 与 `/health` 转发到 `127.0.0.1:8420`。契约变化后先在仓库根目录运行 `tools/generate_clients.py` 更新 `openapi/maestro-v1.json`，再运行 `gen:api`。请求函数按路径推断参数与返回类型，例如 `api.get("/runs/{run_id}", { path: { run_id } })`。

页面（路由见 `src/App.tsx`）：

- 未登录：初始化、登录、接受邀请与重置密码（`/invite#<token>`）。
- `/` 工作台：能否受理、我的近期运行、团队近期结果、待处理事项。
- `/runs`、`/runs/new`、`/runs/:runId`：运行列表（筛选、评分与覆盖、多选导出）；新建运行（方案、检查配置、批次草稿）；运行详情（摘要与状态卡，执行 / 结果汇总 / 配置快照 / 产物标签，`?tab=`、`?trial=`；取消、重跑、修改后运行、导出、删除）。
- `/datasets`、`/attachments`、`/plans`、`/batches`、`/batches/:batchId`、`/exports`：数据集目录与导入、附件、实验方案、提交批次、导出。
- `/settings`：改密、PAT（撤销与删除分开）、SDK 快速上手。
- `/admin/<分区>`（仅管理员）：成员与邀请、凭据与主密钥、模型、Harness、团队策略、容量、数据集导入、回收站、审计、维护。

约定：

- 会话使用 HttpOnly cookie；CSRF token 只保存在内存，所有非安全请求带 `X-CSRF-Token`。
- 新建运行每次逻辑提交持有一个 `Idempotency-Key`，结果未知时重试复用同一键。
- PAT 与邀请链接只在创建后显示一次；凭据值只写，不提供查看。

页面目录：`src/pages/`；公共组件：`src/components/common.tsx`；API 客户端与类型：`src/lib/`。

## 冒烟测试

`qa/smoke.spec.ts` 针对一个全新、一次性的服务运行（绝不要指向真实团队 state）：

```bash
maestro --config /tmp/<tmp>/config.toml init        # 打印一次性初始化令牌
maestro --config /tmp/<tmp>/config.toml serve --port 8431 --demo-executor
MAESTRO_SETUP_TOKEN=<token> NO_PROXY=127.0.0.1 npm run test:ui
```

未设置 `MAESTRO_SETUP_TOKEN` 时只运行用拦截响应验证评分与状态展示的用例（仍需服务提供页面）。

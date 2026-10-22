# Maestro Web

Vite + React + TypeScript + shadcn/ui (Radix) + Tailwind CSS。生产页面与 `/api/v1` 由同一 HTTP 服务（`maestro serve`）提供，不需要单独域名或跨域配置。

```bash
npm ci
npm run build   # tsc -b + vite build，输出到 ../src/maestro/static/
npm run lint
```

开发时 `npm run dev` 把 `/api` 与 `/health` 转发到 `127.0.0.1:8420`。

页面（M2 最简页面）：初始化 / 登录 / 接受邀请与重置密码（`/invite#<token>`）、运行列表与新建运行、运行详情（四个独立状态维度、试次与执行尝试、产物下载、取消）、数据集只读目录、个人设置（改密、PAT）、管理（成员、邀请、凭据、主密钥、审计）。

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

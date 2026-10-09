# Harbor Helper Web

Vite + React + TypeScript + shadcn/ui (Radix) + Tailwind CSS 的团队共享实验工作台。生产页面与 `/api/v1` API 由同一 HTTP 服务提供，不需要单独域名或跨域配置。

```bash
npm ci
npm run build
npm run lint
```

构建输出直接进入 `../src/harbor_helper/static/`，由 Python 应用提供；不要单独部署前端开发服务器。开发时 `npm run dev` 将 `/api` 转发到 `127.0.0.1:8765`。

页面包含受保护首次设置、受邀账户登录与改密、共享实验列表、已验证数据集/任务选择、实验名称与高级参数、失败恢复、日志/报告/产物下载和可比性检查。管理员配置页包含团队来源凭据、版本化运行环境/数据集验证与默认、按名称绑定的模型与 key、编辑与账户重置。配置页在 `ConfigurationPages.tsx`，公共组件在 `shared.tsx`，加载逻辑在 `useLoad.ts`。凭据字段为只写输入，保存成功或失败后均清空；页面不使用 localStorage/sessionStorage 存储会话或密钥。

```bash
# UI 契约测试；仅测试环境使用假账户、假 key 和被拦截的 API fixture。
npx playwright install chromium
NO_PROXY=127.0.0.1,localhost npm run test:ui

# 显式指定隔离 HTTP 服务和受邀测试账户；使用真实 Hub smoke 数据集的 oracle，零模型请求。
HH_WEB_URL=http://127.0.0.1:8000 HH_WEB_USER=alice HH_WEB_PASSWORD='<isolated-test-password>' node qa/live-service.mjs
```

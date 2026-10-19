# Harbor Helper Web

Vite + React + TypeScript + shadcn/ui（Radix）+ Tailwind CSS 的团队实验工作台。需要 Node.js 20.19+ 的 20.x，或 22.12+；CI 使用 Node 22。

```bash
npm ci
npm run test:types
npm run lint
npm run build
```

构建输出进入 `../src/harbor_helper/static/`，生产页面与相对 `/api/v1` API 由同一 Python HTTP 服务提供。开发时 `npm run dev` 将 `/api` 转发到 `127.0.0.1:8765`，需要另行启动隔离后端，或按实际端口调整 `vite.config.ts`。

路由与会话在 `src/app/`，业务页面在 `src/features/`，公共组件在 `src/components/`；管理员入口为 `features/admin/Admin.tsx`。数据集只配置来源与作者参数，环境由 Harbor 按作者定义执行。凭据输入只写，提交后清空；会话与秘密不保存到 localStorage/sessionStorage，主题和时区偏好可保存在本机。

```bash
# 拦截 API 的 UI fixture，使用假账户与假 key。
npx playwright install chromium
NO_PROXY=127.0.0.1,localhost npm run test:ui
```

UI fixture 独占端口 4173，可用 `HH_UI_PORT` 修改，不复用已有服务。完整 Python/生产页面/前端检查使用仓库统一的[隔离验证入口](../docs/guides/automation-ops-ci.md)，避免继承真实凭据。`qa/live-service.mjs` 和 `qa/final-integration-production.mjs` 为手工验证脚本，需要独立实例和对应授权，不属于默认 CI。

DTO 变更、生成类型与漂移检查见[浏览器契约](../docs/guides/browser-contract.md)，源码职责见[架构入口](../docs/architecture/source-layout.md)。

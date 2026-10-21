import { fixture, run } from "./fixture";
import { expect, type Page } from "@playwright/test";
export async function holdCatalogRefresh(page: Page) {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    "**/api/v1/catalog",
    async (route) => {
      await gate;
      await route.fallback();
    },
    { times: 1 },
  );
  return release;
}

export async function expectEditorsLocked(page: Page) {
  await expect(
    page.getByRole("status").filter({ hasText: "正在保存并刷新配置" }),
  ).toBeVisible();
  await expect(
    page.locator("input:enabled, textarea:enabled, select:enabled"),
  ).toHaveCount(0);
  await expect(
    page.getByRole("tab", { name: "模型与 key", exact: true }),
  ).toBeDisabled();
}

export const designRuns = [
  { ...run, id: "run-a", name: "基线 / baseline", agent: "opencode" },
  { ...run, id: "run-b", name: "附件 / candidate", agent: "opencode" },
  { ...run, id: "run-c", name: "重复 / third", agent: "opencode" },
  {
    ...run,
    id: "run-failed",
    name: "任务失败",
    status: "failed",
    agent: "oracle",
  },
  {
    ...run,
    id: "run-running",
    name: "工具准备",
    status: "running",
    audit_status: "pending",
    agent: "opencode",
  },
  {
    ...run,
    id: "run-blocked",
    name: "清理现场",
    status: "cleanup_blocked",
    audit_status: "incomplete",
    agent: "oracle",
  },
  {
    ...run,
    id: "run-queued",
    name: "等待队列",
    status: "queued",
    audit_status: "pending",
    agent: "opencode",
  },
];

export const designComparison = {
  left: "run-a",
  right: "run-b",
  comparable: true,
  reasons: [],
  config_changes: {},
  environment_observations: { left: "unknown", right: "unknown" },
  bundle_change: { left: null, right: null },
  attachment_inputs: { left: { kind: "none" }, right: { kind: "none" } },
  tasks: [
    {
      task: "bracket-fit",
      left: { reward: 0 },
      right: { reward: 0.0000000002 },
      delta: { reward: 0.0000000002 },
    },
    {
      task: "shaft-align",
      left: { reward: 0.6 },
      right: { reward: 0.8 },
      delta: { reward: 0.2 },
    },
  ],
  mean_task_delta: { reward: 0.1 },
};

export async function redesignFixture(page: Page) {
  const calls = await fixture(page);
  await page.route("**/api/v1/runs", (route) =>
    route.fulfill({
      json: {
        runs: designRuns,
        submissions: [
          {
            id: "prep-failed",
            status: "failed",
            submitter: "test-admin",
            created: 1791460000,
            request: { name: "来源准备失败" },
            error: "来源验证失败",
          },
          {
            id: "prep-cancelled",
            status: "cancelled",
            submitter: "test-admin",
            created: 1791460000,
            request: { name: "已取消来源" },
          },
          {
            id: "prep-linked",
            status: "ready",
            run_id: "run-a",
            request: { name: "不重复显示" },
          },
        ],
      },
    }),
  );
  await page.route("**/api/v1/compare", (route) =>
    route.fulfill({ json: designComparison }),
  );
  return calls;
}

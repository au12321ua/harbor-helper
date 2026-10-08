import { test, expect, type Page } from "@playwright/test";
const user = { id: "u1", username: "test-admin", role: "admin" };
const run = {
  id: "hh-test-zero",
  submitter: "test-admin",
  status: "succeeded",
  created: 1791460000,
  audit_status: "clean",
  dataset: "team/test@1",
  model_profile: "plan1",
  concurrency: 1,
};
const catalog = {
  providers: [
    {
      id: "p1",
      name: "测试提供商",
      endpoint: "https://example.invalid/v1",
      protocol: "openai-compatible",
      enabled: true,
    },
  ],
  credentials: [
    {
      id: "c1",
      label: "测试凭据",
      provider_id: "p1",
      current_version: 1,
      enabled: true,
    },
  ],
  model_profiles: [
    {
      id: "plan1",
      name: "测试方案",
      model: "test-model",
      provider_id: "p1",
      credential_id: "c1",
      params: {},
      enabled: true,
    },
  ],
  default_dataset: "team/test@1",
  limits: {
    max_jobs: 1,
    max_trials: 2,
    max_queue: 20,
    max_wall_seconds: 1800,
    max_attempts: 3,
    max_cpus_per_trial: 2,
    max_memory_mb_per_trial: 2048,
    max_upload_bytes: 10485760,
    log_retention_days: 30,
    artifact_retention_days: 30,
  },
};
async function fixture(page: Page, role = "admin", logged = true) {
  let authenticated = logged;
  const calls: { path: string; body: any; headers: Record<string, string> }[] =
    [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname.replace("/api/v1", "");
    let body: any;
    try {
      body = request.postDataJSON();
    } catch {}
    calls.push({ path, body, headers: request.headers() });
    let value: any = {};
    let status = 200;
    if (path === "/me") {
      value = { user: { ...user, role } };
      if (!authenticated) {
        status = 401;
        value = { code: "unauthorized", message: "请登录" };
      }
    } else if (path === "/auth/login") {
      authenticated = true;
      value = { user: { ...user, role } };
    } else if (path === "/auth/logout") {
      authenticated = false;
      value = { ok: true };
    } else if (path === "/catalog") value = catalog;
    else if (path === "/usage")
      value = {
        total_runs: 1,
        total_submissions: 1,
        active_jobs: 0,
        active_trials: 0,
        queued_jobs: 0,
      };
    else if (path === "/runs")
      value = {
        runs: [
          run,
          {
            ...run,
            id: "hh-other-running",
            submitter: "another-member",
            status: "running",
            audit_status: "pending",
          },
        ],
        submissions: [],
      };
    else if (path === "/runs/hh-test-zero")
      value = {
        row: run,
        manifest: {
          source: { dataset: "team/test@1" },
          profile: { model: "test-model" },
        },
        artifacts: [{ id: "answer", name: "answer.txt", deleted: false }],
        report: {
          complete: true,
          expected_attempts: 1,
          valid_attempts: 1,
          missing_attempts: 0,
          tasks: [
            {
              task: "test-answer",
              expected_attempts: 1,
              valid_attempts: 1,
              mean_rewards: { reward: 0 },
            },
          ],
        },
      };
    else if (path === "/runs/hh-other-running")
      value = {
        row: {
          ...run,
          id: "hh-other-running",
          submitter: "another-member",
          status: "running",
          audit_status: "pending",
        },
        manifest: {},
        artifacts: [],
        report: null,
      };
    else if (path.endsWith("/logs"))
      value = {
        text: '[bold]literal markup[/bold]\n<script>window.bad=1</script>\n"quoted"',
      };
    else if (path === "/submissions") {
      value = { submission_id: "submission-test", status: "preparing" };
    } else if (path === "/submissions/submission-test")
      value = {
        id: "submission-test",
        submitter: user.username,
        status: "preparing",
      };
    else if (path === "/compare")
      value = { comparable: false, reasons: ["来源数据集不同"] };
    else if (path === "/admin/users")
      value = { users: [{ ...user, enabled: true }] };
    else if (path.startsWith("/admin/")) value = { ok: true };
    else if (path.endsWith("/rerun"))
      value = { submission_id: "submission-test" };
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(value),
    });
  });
  return calls;
}
test("shared list, actual zero report, literal safe logs and screenshot", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "共享实验", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "hh-test-zero", exact: true }).click();
  await page.getByRole("tab", { name: "评分报告" }).click();
  await expect(page.getByText("reward:")).toHaveText("reward: 0");
  await expect(page.getByText("缺失评分", { exact: true })).toHaveCount(0);
  await page.getByRole("tab", { name: "运行日志" }).click();
  await expect(page.locator(".log-view")).toContainText(
    "[bold]literal markup[/bold]",
  );
  expect(await page.evaluate(() => "bad" in window)).toBe(false);
  await page.goto("/");
  await page.screenshot({
    path: "/tmp/harbor-helper-web-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "/tmp/harbor-helper-web-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
test("invited login and dataset/profile submission use same-origin mutation header", async ({
  page,
}) => {
  const calls = await fixture(page, "admin", false);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "登录团队实验室" }),
  ).toBeVisible();
  await page.getByLabel("账户", { exact: true }).fill("test-admin");
  await page.getByLabel("密码", { exact: true }).fill("test-password-only");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("link", { name: "新建实验" }).first().click();
  await page.getByLabel("数据集", { exact: true }).fill("team/switched@2");
  await page.getByLabel("模型方案", { exact: true }).selectOption("plan1");
  await page.getByRole("button", { name: "提交实验" }).click();
  await expect(
    page.getByRole("heading", { name: "实验准备", exact: true }),
  ).toBeVisible();
  const submitted = calls.find((c) => c.path === "/submissions" && c.body);
  expect(submitted?.body.dataset).toBe("team/switched@2");
  expect(submitted?.headers["idempotency-key"]).toHaveLength(32);
  expect(submitted?.headers["x-requested-with"]).toBe("harbor-helper");
  expect(submitted?.body).not.toHaveProperty("key");
});
test("members share other runs but cannot cancel them or see admin navigation", async ({
  page,
}) => {
  await fixture(page, "member");
  await page.goto("/runs/hh-other-running");
  await expect(
    page.getByRole("heading", { name: "hh-other-running", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "取消实验" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "团队管理" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "重跑实验" })).toBeVisible();
});
test("admin key write clears input and does not use browser storage", async ({
  page,
}) => {
  const calls = await fixture(page);
  await page.goto("/admin");
  await page.getByRole("tab", { name: "凭据", exact: true }).click();
  await page.getByLabel("凭据 ID").fill("c2");
  await page.getByLabel("显示名称").fill("新的测试凭据");
  await page.getByLabel("所属提供商").selectOption("p1");
  await page.getByLabel("密钥", { exact: true }).fill("fake-key-browser-test");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByLabel("密钥", { exact: true })).toHaveValue("");
  expect(calls.find((c) => c.path === "/admin/credentials")?.body.key).toBe(
    "fake-key-browser-test",
  );
  expect(
    await page.evaluate(() =>
      JSON.stringify({ ...localStorage, ...sessionStorage }),
    ),
  ).not.toContain("fake-key-browser-test");
});

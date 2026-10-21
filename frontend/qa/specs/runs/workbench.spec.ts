import { test, fixture, run } from "../../support/fixture";
import { expect } from "@playwright/test";
import { designComparison, redesignFixture } from "../../support/ui-support";
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
    path: test.info().outputPath("harbor-helper-web-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: test.info().outputPath("harbor-helper-web-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("workbench filters restore URL, expose preparation failures and keep ordered A/B selection", async ({
  page,
}) => {
  await redesignFixture(page);
  await page.goto("/?status=active&q=工具");
  await expect(
    page.getByRole("link", { name: "工具准备", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "基线 / baseline", exact: true }),
  ).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "活动 2" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByRole("textbox", { name: "搜索实验" })).toHaveValue(
    "工具",
  );
  await page.getByRole("button", { name: "全部 7" }).click();
  await page.getByRole("textbox", { name: "搜索实验" }).fill("");
  await expect(
    page.getByRole("link", { name: "来源准备失败", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("准备失败", { exact: true })).toBeVisible();
  await expect(page.getByText("已取消来源", { exact: true })).toBeVisible();
  await expect(page.getByText("不重复显示", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("checkbox", { name: "选择实验 工具准备" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("checkbox", { name: "选择实验 清理现场" }),
  ).toBeDisabled();
  await page
    .getByRole("checkbox", { name: "选择实验 基线 / baseline" })
    .check();
  await page
    .getByRole("checkbox", { name: "选择实验 附件 / candidate" })
    .check();
  await page.getByRole("checkbox", { name: "选择实验 重复 / third" }).click();
  await expect(
    page.getByText("已选择 A/B 两次实验", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("checkbox", { name: "选择实验 重复 / third" }),
  ).not.toBeChecked();
  await page.getByRole("link", { name: "对比实验", exact: true }).click();
  await expect(page).toHaveURL(/compare\?left=run-a&right=run-b/);
  await page.reload();
  await expect(page.getByLabel("实验 A", { exact: true })).toHaveValue("run-a");
  await expect(page.getByLabel("实验 B", { exact: true })).toHaveValue("run-b");
});

test("comparison clears prior results and ignores late requests for changed conditions", async ({
  page,
}) => {
  await redesignFixture(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let count = 0;
  await page.route("**/api/v1/compare", async (route) => {
    const n = ++count;
    if (n === 2) await gate;
    await route.fulfill({
      json: {
        ...designComparison,
        mean_task_delta: { reward: n === 2 ? 999 : n },
      },
    });
  });
  await page.goto("/compare?left=run-a&right=run-b");
  await page.getByRole("button", { name: "开始对比" }).click();
  await expect(page.locator(".report-summary")).toContainText("1");
  await page.getByRole("button", { name: "开始对比" }).click();
  await expect.poll(() => count).toBe(2);
  await page.getByLabel("实验 B", { exact: true }).selectOption("run-c");
  await expect(page.locator(".report-summary")).toHaveCount(0);
  await page.getByRole("button", { name: "开始对比" }).click();
  await expect(page.locator(".report-summary")).toContainText("3");
  const oldResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/compare") &&
      response.request().postDataJSON().right === "run-b",
  );
  release();
  await oldResponse;
  await expect(page.locator(".report-summary")).toContainText("3");
  await expect(page.locator(".report-summary")).not.toContainText("999");
  await page.getByLabel("实验 A", { exact: true }).selectOption("run-b");
  await expect(page.locator(".report-summary")).toHaveCount(0);
});

test("server incomparable verdict hides every delta even if partial task results exist", async ({
  page,
}) => {
  await redesignFixture(page);
  await page.route("**/api/v1/compare", (route) =>
    route.fulfill({
      json: {
        ...designComparison,
        comparable: false,
        reasons: ["Both runs must succeed"],
        config_changes: { attempts: { left: 1, right: 2 } },
      },
    }),
  );
  await page.goto("/compare?left=run-a&right=run-failed");
  await page.getByRole("button", { name: "开始对比" }).click();
  await expect(
    page.getByText("Both runs must succeed", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".report-summary")).toHaveCount(0);
  await expect(page.locator(".compare-table")).toHaveCount(0);
  await expect(
    page.getByRole("cell", { name: "attempts", exact: true }),
  ).toBeVisible();
});

for (const code of ["report_pending", "audit_incomplete", "evidence_expired"]) {
  test(`comparison provides dedicated feedback for ${code}`, async ({
    page,
  }) => {
    await redesignFixture(page);
    await page.route("**/api/v1/compare", (route) =>
      route.fulfill({ status: 409, json: { code, message: code } }),
    );
    await page.goto("/compare?left=run-a&right=run-b");
    await page.getByRole("button", { name: "开始对比" }).click();
    await expect(page.getByText(code, { exact: true })).toBeVisible();
    await expect(
      page.getByText(
        code === "evidence_expired" ? "证据已过期" : "报告尚未发布",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(page.locator(".compare-table")).toHaveCount(0);
  });
}

test("mobile comparison shows all four columns, valid zero and nonzero tiny delta", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await redesignFixture(page);
  await page.goto("/compare?left=run-a&right=run-b");
  await page.getByRole("button", { name: "开始对比" }).click();
  const row = page.getByRole("row").filter({ hasText: "bracket-fit" });
  await expect(row.getByRole("cell").nth(1)).toHaveText("0");
  await expect(row.getByRole("cell").nth(3)).toHaveText("2e-10");
  for (const index of [0, 1, 2, 3]) {
    const box = await row.getByRole("cell").nth(index).boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("capacity uses reserved slots, maintenance reason and visibly stale refresh", async ({
  page,
}) => {
  await redesignFixture(page);
  let failed = false;
  await page.route("**/api/v1/usage", (route) =>
    route.fulfill(
      failed
        ? {
            status: 503,
            json: { code: "unavailable", message: "fixture refresh failure" },
          }
        : {
            json: {
              active_jobs: 2,
              active_trials: 5,
              queued_jobs: 1,
              total_runs: 7,
              total_submissions: 9,
            },
          },
    ),
  );
  await page.route("**/api/v1/readiness", (route) =>
    route.fulfill({
      json: {
        accepting: false,
        observed: 1791460000,
        scheduler: { state: "unknown", reason: "unknown" },
        maintenance: { paused: true, reason: "维护配置", retry_at: 1791462000 },
        pending: {
          global_pending: 2,
          global_limit: 20,
          member_pending: 1,
          member_limit: 10,
        },
      },
    }),
  );
  await page.goto("/");
  await expect(page.getByLabel("受理与容量")).toContainText("实验槽位2 / 1");
  await expect(page.getByLabel("受理与容量")).toContainText("trial 槽位5 / 2");
  await expect(page.getByText(/维护暂停：维护配置/)).toBeVisible();
  await expect(page.getByLabel("受理与容量")).toContainText("不会自动恢复");
  failed = true;
  await page.getByRole("button", { name: "刷新实验" }).click();
  await expect(page.getByText(/上次成功更新.*刷新失败/)).toBeVisible();
  await expect(page.getByLabel("受理与容量")).toHaveClass(/stale/);
});

test("mobile drawer traps focus, closes by Escape and restores focus after routing", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixture(page, "member");
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "打开导航", exact: true });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "工作空间导航" });
  await expect(dialog).toBeVisible();
  await expect(
    page.getByRole("button", { name: "关闭导航", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "退出登录" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "关闭导航", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
  await trigger.click();
  await expect(dialog.getByRole("link", { name: "团队管理" })).toHaveCount(0);
  await dialog.getByRole("link", { name: "实验对比", exact: true }).click();
  await expect(page).toHaveURL(/compare/);
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await trigger.click();
  await expect(dialog).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(dialog).toHaveCount(0);
  await expect(page.locator("main")).not.toHaveAttribute("inert", "");
  await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(dialog).toHaveCount(0);
});

test("log refresh preserves literal text and distinguishes truncation, audit and expiry", async ({
  page,
}) => {
  await fixture(page);
  let state = "ok";
  await page.route("**/api/v1/runs/hh-test-zero/logs", (route) =>
    route.fulfill(
      state === "ok"
        ? {
            json: {
              text: "<script>window.logBad=1</script>\n原文 tail",
              truncated: true,
            },
          }
        : { status: 409, json: { code: state, message: state } },
    ),
  );
  await page.goto("/runs/hh-test-zero");
  await page.getByRole("tab", { name: "运行日志" }).click();
  await expect(
    page.getByText("仅显示末尾最多 256 KiB（已截断）", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".log-view")).toContainText("<script>");
  expect(await page.evaluate(() => "logBad" in window)).toBe(false);
  state = "audit_incomplete";
  await page.getByRole("button", { name: "刷新日志" }).click();
  await expect(
    page.getByText("日志安全审计异常", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".log-view")).toHaveCount(0);
  state = "evidence_expired";
  await page.getByRole("button", { name: "刷新日志" }).click();
  await expect(page.getByText("日志证据已过期", { exact: true })).toBeVisible();
  await expect(page.locator(".log-view")).toHaveCount(0);
});

test("empty list, no matches and refresh failure retain distinct recovery paths", async ({
  page,
}) => {
  await fixture(page);
  let mode = "error";
  await page.route("**/api/v1/runs", (route) =>
    route.fulfill(
      mode === "error"
        ? {
            status: 503,
            json: { code: "unavailable", message: "记录暂不可用" },
          }
        : { json: { runs: mode === "empty" ? [] : [run], submissions: [] } },
    ),
  );
  await page.goto("/");
  await expect(page.getByText("记录暂不可用", { exact: true })).toBeVisible();
  mode = "empty";
  await page.getByRole("button", { name: "重试加载", exact: true }).click();
  await expect(page.getByText("暂无实验", { exact: true })).toBeVisible();
  mode = "normal";
  await page.getByRole("button", { name: "刷新实验" }).click();
  await expect(
    page.getByRole("link", { name: run.id, exact: true }),
  ).toBeVisible();
  await page.getByRole("textbox", { name: "搜索实验" }).fill("no matches");
  await expect(page.getByText("没有匹配的实验", { exact: true })).toBeVisible();
  await expect(page.getByText("暂无实验", { exact: true })).toHaveCount(0);
});

test("report keeps zero, missing score and failed attempt distinct; diagnostics stay inside overview", async ({
  page,
}) => {
  await fixture(page);
  const diagnosis = {
    hint: "phase evidence",
    phase: "agent_setup",
    startup_multiplier: 10,
    model_status: "not_reached",
    phases: [
      { phase: "environment_setup", reached: true, seconds: null },
      { phase: "agent_setup", reached: true, seconds: 0 },
      { phase: "agent_execution", reached: false, seconds: null },
    ],
    compose: null,
  };
  await page.route("**/api/v1/runs/hh-test-zero", (route) =>
    route.fulfill({
      json: {
        row: { ...run, status: "failed" },
        manifest: { effective: { wall_seconds: 1800 } },
        artifacts: [],
        report: {
          complete: false,
          expected_attempts: 3,
          valid_attempts: 1,
          invalid_attempts: 1,
          missing_attempts: 1,
          tasks: [
            {
              task: "zero",
              valid_attempts: 1,
              expected_attempts: 1,
              mean_rewards: { reward: 0 },
              attempts: [
                { task: "zero", trial: "trial-zero", valid: true, diagnosis },
              ],
            },
            {
              task: "failed",
              valid_attempts: 0,
              expected_attempts: 1,
              mean_rewards: null,
              attempts: [
                {
                  task: "failed",
                  trial: "trial-failed",
                  valid: false,
                  exception: { type: "setup_error" },
                  diagnosis,
                },
              ],
            },
            {
              task: "missing",
              valid_attempts: 0,
              expected_attempts: 1,
              mean_rewards: null,
              attempts: [],
            },
          ],
        },
      },
    }),
  );
  await page.goto("/runs/hh-test-zero");
  await expect(
    page.locator(".diagnosis").filter({ hasText: "失败定位" }),
  ).toHaveAttribute("open", "");
  await expect(
    page.locator(".diagnosis").filter({ hasText: "执行阶段与耗时" }),
  ).not.toHaveAttribute("open", "");
  await expect(
    page.locator(".diagnosis[open]").getByText(/环境启动：耗时未知/),
  ).toBeVisible();
  await expect(
    page.locator(".diagnosis[open]").getByText(/代理准备：0.000秒/),
  ).toBeVisible();
  await expect(
    page.locator(".diagnosis[open]").getByText(/执行：未到达/),
  ).toBeVisible();
  await page.getByRole("tab", { name: "评分报告", exact: true }).click();
  await expect(page.locator(".diagnosis")).toHaveCount(0);
  await expect(
    page
      .getByRole("row")
      .filter({ has: page.getByRole("cell", { name: "zero", exact: true }) }),
  ).toContainText("reward: 0");
  await expect(
    page
      .getByRole("row")
      .filter({ has: page.getByRole("cell", { name: "failed 执行失败" }) }),
  ).toContainText("缺失评分");
  await expect(
    page.getByRole("row").filter({
      has: page.getByRole("cell", { name: "missing", exact: true }),
    }),
  ).toContainText("缺失评分");
});

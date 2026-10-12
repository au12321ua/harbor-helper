import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import fs from "node:fs";
const evidence = process.env.HH_BROWSER_EVIDENCE;
const inputs = JSON.parse(fs.readFileSync(evidence + "/browser-inputs.json"));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
  });
  const errors = [],
    failures = [],
    consoleErrors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (e) => {
    if (e.type() === "error") consoleErrors.push(e.text());
  });
  page.on("response", (r) => {
    if (r.status() >= 400)
      failures.push({ path: new URL(r.url()).pathname, status: r.status() });
  });
  await page.goto(inputs.url);
  assert.equal(await page.title(), "Harbor Helper · 团队实验室");
  await page.getByLabel("账户").fill("fixture-member");
  await page
    .getByLabel("密码", { exact: true })
    .fill("Fixture-only-member-password-2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  const accepted = [];
  for (const [index, version] of ["", ...inputs.versions].entries()) {
    await page
      .getByRole("navigation", { name: "主导航" })
      .getByRole("link", { name: "新建实验", exact: true })
      .click();
    await page
      .getByLabel("数据集", { exact: true })
      .selectOption(inputs.dataset_id);
    await page.getByLabel("执行方案", { exact: true }).selectOption("oracle");
    await page.getByLabel("团队附件版本（可选）").selectOption(version);
    if (!version)
      await page
        .getByRole("button", { name: "清除附件，使用无附件基线" })
        .click();
    await page.locator("details summary").click();
    await page.locator("[name=attempts]").fill("1");
    await page.locator("[name=concurrency]").fill("1");
    await page.locator("[name=wall_seconds]").fill("120");
    const response = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/v1/submissions") &&
        r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "提交实验", exact: true }).click();
    const r = await response;
    assert.equal(r.status(), 202);
    const value = await r.json();
    assert.equal(value.attachment.attachment_version_id, version || null);
    accepted.push(value);
    await page.waitForURL(/\/submissions\/sub-/);
    await page.screenshot({
      path: evidence + `/browser-submit-${index}.png`,
      fullPage: true,
    });
  }
  const runIds = [];
  for (const row of accepted) {
    const deadline = Date.now() + 60000;
    let state;
    do {
      const response = await page.request.get(
        inputs.url + `/api/v1/machine/submissions/${row.id}`,
      );
      assert.equal(response.status(), 200);
      state = await response.json();
      if (state.report.state === "available") break;
      assert(Date.now() < deadline, "bounded browser observation timed out");
      await page.waitForTimeout(100);
    } while (true);
    runIds.push(state.run_id);
    await page.goto(inputs.url + `/runs/${state.run_id}`);
    await page.getByRole("tab", { name: "评分报告", exact: true }).click();
    await page
      .getByRole("button", { name: "下载评分报告", exact: true })
      .waitFor();
    await page.getByText("reward", { exact: false }).first().waitFor();
  }
  assert.equal(
    await page.getByRole("link", { name: "团队管理", exact: true }).count(),
    0,
  );
  await page.getByRole("link", { name: "实验对比", exact: true }).click();
  await page.getByLabel("实验 A", { exact: true }).selectOption(runIds[0]);
  await page.getByLabel("实验 B", { exact: true }).selectOption(runIds[1]);
  const compared = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/compare") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "开始对比", exact: true }).click();
  const comparison = await (await compared).json();
  assert.equal(comparison.comparable, true);
  assert.equal(comparison.mean_task_delta.reward, 1);
  await page.getByText("对比结果", { exact: true }).waitFor();
  await page.getByText("实验 A 附件：无附件", { exact: true }).waitFor();
  await page.getByText(inputs.versions[0], { exact: false }).first().waitFor();
  await page.screenshot({
    path: evidence + "/browser-comparison-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("link", { name: "共享实验", exact: true }).click();
  await page.getByRole("heading", { name: "共享实验", exact: true }).waitFor();
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 2,
    ),
  );
  assert.equal(await page.locator("vite-error-overlay").count(), 0);
  assert.deepEqual(errors, []);
  assert.deepEqual(consoleErrors, [
    "Failed to load resource: the server responded with a status of 401 (Unauthorized)",
  ]);
  assert.deepEqual(failures, [{ path: "/api/v1/me", status: 401 }]);
  await page.screenshot({
    path: evidence + "/browser-shared-mobile.png",
    fullPage: true,
  });
  fs.writeFileSync(
    evidence + "/browser-submissions.json",
    JSON.stringify(accepted, null, 2),
  );
  console.log(
    "production browser: login -> actual no-attachment/v1/v2 submit -> safe report -> comparable browser result -> shared mobile list; identity/content/overlay/interaction/pageerror checks passed; expected initial anonymous 401 only",
  );
} finally {
  await browser.close();
}

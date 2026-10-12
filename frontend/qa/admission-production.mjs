import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
  });
  const errors = [];
  const httpFailures = [];
  page.on("response", (r) => {
    if (r.status() >= 400)
      httpFailures.push({
        path: new URL(r.url()).pathname,
        status: r.status(),
      });
  });
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (e) => {
    if (e.type() === "error") errors.push(e.text());
  });
  await page.goto(process.env.HH_BROWSER_URL);
  assert.equal(await page.title(), "Harbor Helper · 团队实验室");
  await page.getByLabel("账户").fill("admin");
  await page
    .getByLabel("密码", { exact: true })
    .fill("Fake-process-password-2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("link", { name: "团队管理" }).click();
  await page.getByRole("tab", { name: "容量与保留" }).click();
  await page.getByLabel("每成员待处理额度（有效值不超过全局上限）").fill("3");
  const form = page
    .getByText("容量与保留", { exact: true })
    .filter({ hasNot: page.locator("*") })
    .locator("../..");
  const limitsResponse = page.waitForResponse(
    (r) =>
      r.url().endsWith("/admin/limits") && r.request().method() === "PATCH",
  );
  await form.getByRole("button", { name: "保存", exact: true }).click();
  assert.equal((await (await limitsResponse).json()).max_pending_per_member, 3);
  await page.getByLabel("维护原因").fill("browser maintenance");
  await page
    .getByLabel("建议重试时间（可选）")
    .fill(new Date(Date.now() + 86400000).toISOString().slice(0, 16));
  const pause = page.waitForResponse(
    (r) =>
      r.url().endsWith("/admin/maintenance") &&
      r.request().method() === "PATCH",
  );
  await page.getByRole("button", { name: "暂停新受理", exact: true }).click();
  assert.equal((await (await pause).json()).paused, true);
  await page.getByText("维护暂停：browser maintenance").waitFor();
  await page.reload();
  await page.getByRole("tab", { name: "容量与保留" }).click();
  assert.equal(
    await page
      .getByLabel("每成员待处理额度（有效值不超过全局上限）")
      .inputValue(),
    "3",
  );
  await page.getByText("维护暂停：browser maintenance").waitFor();
  await page.screenshot({
    path: process.env.HH_BROWSER_EVIDENCE + "/admission-admin.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "退出登录" }).click();
  await page.getByLabel("账户").fill("alice");
  await page
    .getByLabel("密码", { exact: true })
    .fill("Fake-process-password-2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("link", { name: "共享实验", exact: true }).click();
  await page.getByText("维护暂停：browser maintenance").waitFor();
  assert.equal(
    await page.getByRole("button", { name: "恢复新受理", exact: true }).count(),
    0,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 2,
    ),
    true,
  );
  await page.screenshot({
    path: process.env.HH_BROWSER_EVIDENCE + "/admission-member-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "退出登录" }).click();
  await page.getByLabel("账户").fill("admin");
  await page
    .getByLabel("密码", { exact: true })
    .fill("Fake-process-password-2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("link", { name: "团队管理" }).click();
  await page.getByRole("tab", { name: "容量与保留" }).click();
  const resume = page.waitForResponse(
    (r) =>
      r.url().endsWith("/admin/maintenance") &&
      r.request().method() === "PATCH",
  );
  await page.getByRole("button", { name: "恢复新受理", exact: true }).click();
  assert.equal((await (await resume).json()).paused, false);
  await page.getByText("允许新受理", { exact: true }).waitFor();
  assert.equal(await page.locator("vite-error-overlay").count(), 0);
  assert.deepEqual(httpFailures, [{ path: "/api/v1/me", status: 401 }]);
  assert.deepEqual(errors, [
    "Failed to load resource: the server responded with a status of 401 (Unauthorized)",
  ]);
  console.log(
    "production admission UI passed; desktop/mobile; no page errors; only expected anonymous /me 401 console entry; pause/reload/resume and member read verified",
  );
} finally {
  await browser.close();
}

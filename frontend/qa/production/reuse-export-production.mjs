import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
const url = process.env.HH_BROWSER_URL,
  root = process.env.HH_BROWSER_EVIDENCE,
  source = process.env.HH_SOURCE_RUN;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
  });
  const errors = [],
    bootstrapErrors = [];
  let loggedIn = false;
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (e) => {
    if (e.type() === "error")
      (loggedIn ? errors : bootstrapErrors).push(e.text());
  });
  await page.goto(url);
  assert.equal(await page.title(), "Harbor Helper · 团队实验室");
  await page.getByLabel("账户", { exact: true }).fill("alice");
  await page
    .getByLabel("密码", { exact: true })
    .fill("Fake-process-password-2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.locator(".app-shell").waitFor();
  loggedIn = true;
  assert(
    bootstrapErrors.every((e) => e.includes("401 (Unauthorized)")),
    JSON.stringify(bootstrapErrors),
  );
  await page.goto(`${url}/runs/${source}`);
  await page.getByRole("link", { name: "复制配置新建" }).click();
  assert.equal(
    await page.getByLabel("数据集", { exact: true }).inputValue(),
    "source-dataset",
  );
  assert.equal(
    await page.getByLabel("模型方案", { exact: true }).inputValue(),
    "m1",
  );
  await page.getByLabel("实验总时长上限（秒，含准备）").fill("800");
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/submissions") &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "提交实验", exact: true }).click();
  const acceptedResponse = await response;
  const accepted = await acceptedResponse.json();
  assert.equal(acceptedResponse.status(), 202);
  const request = acceptedResponse.request().postDataJSON();
  await page.goto(`${url}/submissions/sub-inherited-failure`);
  await page.getByRole("button", { name: "修改输入后新提交" }).click();
  assert.equal(
    await page.getByLabel("数据集", { exact: true }).inputValue(),
    "source-dataset",
  );
  assert.equal(
    await page.getByLabel("模型方案", { exact: true }).inputValue(),
    "m1",
  );
  assert.equal(
    await page.getByLabel("实验总时长上限（秒，含准备）").inputValue(),
    "900",
  );
  await page.screenshot({
    path: path.join(root, "http-parent-reuse.png"),
    fullPage: true,
  });
  // Wait for the existing zero-score executor fixture's new run/report.
  let newRun;
  for (let i = 0; i < 100; i++) {
    const r = await page.request.get(
      `${url}/api/v1/submissions/${accepted.id}`,
    );
    newRun = (await r.json()).run_id;
    if (newRun) {
      const report = await page.request.get(`${url}/api/v1/runs/${newRun}`);
      const detail = await report.json();
      if (detail.row.audit_status === "clean" && detail.report) break;
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  assert(newRun);
  await page.goto(`${url}/compare?left=${source}&right=${newRun}`);
  const comparing = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/compare") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "开始对比" }).click();
  const actual = await (await comparing).json();
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载 JSON" }).click();
  const download = await downloading;
  const filename = path.join(root, "http-comparison.json");
  await download.saveAs(filename);
  const parsed = JSON.parse(await readFile(filename, "utf8"));
  assert.deepEqual(parsed.comparison, actual);
  assert.equal(parsed.format_version, 1);
  await writeFile(
    path.join(root, "http-compare-response.json"),
    JSON.stringify(actual, null, 2),
  );
  await page.screenshot({
    path: path.join(root, "http-compare.png"),
    fullPage: true,
  });
  assert.deepEqual(errors, []);
  await writeFile(
    path.join(root, "reuse-http-proof.json"),
    JSON.stringify(
      {
        url,
        status: acceptedResponse.status(),
        accepted,
        request,
        parent: {
          dataset_id: "source-dataset",
          model_profile: "m1",
          wall_seconds: 900,
        },
        console_errors: errors,
        expected_prelogin_console: bootstrapErrors,
        page_title: await page.title(),
      },
      null,
      2,
    ),
  );
  console.log("production reuse/export three wiring checks passed");
} finally {
  await browser.close();
}

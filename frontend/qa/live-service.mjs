// Explicit isolated service only. Never uses a model provider or personal key.
import { chromium } from "@playwright/test";
import { writeFile } from "node:fs/promises";
const url = process.env.HH_WEB_URL,
  password = process.env.HH_WEB_PASSWORD,
  username = process.env.HH_WEB_USER;
if (!url || !password || !username)
  throw new Error(
    "Set HH_WEB_URL, HH_WEB_USER, HH_WEB_PASSWORD for the isolated service",
  );
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
try {
  await page.goto(url);
  await page.getByLabel("账户", { exact: true }).fill(username);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("heading", { name: "共享实验", exact: true }).waitFor();
  await page.screenshot({
    path: "/tmp/harbor-helper-web-live-desktop.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "新建实验" }).first().click();
  await page.getByLabel("执行方案", { exact: true }).selectOption("oracle");
  await page
    .getByLabel("数据集", { exact: true })
    .fill("au12321ua/harbor-helper-switch-smoke@1");
  await page.getByLabel("最长运行秒数", { exact: true }).fill("180");
  await page.getByRole("button", { name: "提交实验", exact: true }).click();
  await page.waitForURL(/\/runs\//, { timeout: 180000 });
  const runId = page.url().split("/").at(-1);
  console.log(
    JSON.stringify({ phase: "submitted", runId, submitter: username }),
  );
  await page
    .getByText("成功", { exact: true })
    .first()
    .waitFor({ timeout: 180000 });
  await page.getByRole("tab", { name: "评分报告", exact: true }).click();
  await page.getByText("reward:").waitFor({ timeout: 60000 });
  const reportText = await page.locator("main").innerText();
  if (!/reward:\s*1/.test(reportText))
    throw new Error("Real oracle report must contain reward 1");
  await page.screenshot({
    path: "/tmp/harbor-helper-web-live-report.png",
    fullPage: true,
  });
  await page.getByRole("tab", { name: "实验产物" }).click();
  const artifacts = await page.locator("main").innerText();
  await page.goto(url);
  await page.getByRole("heading", { name: "共享实验", exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "/tmp/harbor-helper-web-live-mobile.png",
    fullPage: true,
  });
  if (
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    )
  )
    throw new Error("Mobile document overflow");
  if (errors.length) throw new Error(errors.join("\n"));
  const evidence = {
    url,
    username,
    runId,
    result: "passed",
    score: 1,
    providerCalls: 0,
    desktop: [1440, 1000],
    mobile: [390, 844],
    consoleErrors: errors,
    artifactsView: artifacts,
    screenshots: [
      "/tmp/harbor-helper-web-live-desktop.png",
      "/tmp/harbor-helper-web-live-report.png",
      "/tmp/harbor-helper-web-live-mobile.png",
    ],
  };
  await writeFile(
    "/tmp/harbor-helper-web-live-evidence.json",
    JSON.stringify(evidence, null, 2),
  );
  console.log(
    JSON.stringify({
      phase: "passed",
      runId,
      score: 1,
      consoleErrors: errors.length,
    }),
  );
} finally {
  await browser.close();
}

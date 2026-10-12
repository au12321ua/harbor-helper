import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.goto(process.env.HH_BROWSER_URL);
  await page.getByLabel("账户").fill("alice");
  await page
    .getByLabel("密码", { exact: true })
    .fill("Fake-process-password-2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("link", { name: "自动化凭证" }).click();
  await page.getByLabel("用途名称").fill("browser research");
  await page.getByLabel("当前密码").fill("wrong");
  await page.getByRole("button", { name: "签发凭证", exact: true }).click();
  await page.getByText("Invalid login", { exact: false }).waitFor();
  assert.equal(await page.getByLabel("当前密码").inputValue(), "");
  await page.getByLabel("当前密码").fill("Fake-process-password-2026");
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/access-credentials") &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "签发凭证", exact: true }).click();
  const issuance = await (await response).json();
  assert.deepEqual(issuance.credential.scopes, ["read"]);
  const raw = await page.getByLabel("新签发凭证").inputValue();
  assert.match(raw, /^hh_pat_v1_[A-Za-z0-9_-]{43}$/);
  await page.getByRole("button", { name: "已安全保存，关闭原值" }).click();
  await page.reload();
  await page.getByRole("heading", { name: "自动化访问凭证" }).waitFor();
  assert.equal(await page.getByLabel("新签发凭证").count(), 0);
  assert(!(await page.content()).includes(raw));
  await page.getByRole("button", { name: "撤销 browser research" }).click();
  await page.getByText("已撤销", { exact: false }).waitFor();
  await page.screenshot({
    path: process.env.HH_BROWSER_EVIDENCE + "/credential-ui.png",
    fullPage: true,
  });
  assert.equal(
    await page.evaluate(() =>
      Object.values(localStorage).some((v) => v.includes("hh_pat_v1_")),
    ),
    false,
  );
  console.log("production credential UI passed");
} finally {
  await browser.close();
}

// C: real production backend, fresh isolated state, synthetic account. No scheduler.
// Required: HH_THEME_URL, HH_THEME_PRIVATE, HH_THEME_EVIDENCE. Never use team state.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { randomBytes } from "node:crypto";
const url = process.env.HH_THEME_URL,
  out = process.env.HH_THEME_EVIDENCE;
assert(
  url?.startsWith("http://127.0.0.1:") && out && process.env.HH_THEME_PRIVATE,
);
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const evidence = {
  source: "C: real backend, synthetic account, production static",
  pages: [],
  requests: [],
  firstPaint: [],
};
const errors = [];
const context = await browser.newContext(),
  page = await context.newPage();
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => {
  if (m.type() === "error" && !m.text().includes("401 (Unauthorized)"))
    errors.push(m.text());
});
page.on("request", (r) => {
  if (r.url().includes("/api/"))
    evidence.requests.push({
      method: r.method(),
      path: new URL(r.url()).pathname,
    });
});
const toggle = () => page.getByRole("button", { name: /切换到[明暗]主题/ });
async function checkTheme(theme) {
  await page.waitForFunction(
    (t) => document.documentElement.dataset.theme === t,
    theme,
  );
  assert.equal(
    await page.evaluate(
      () => getComputedStyle(document.documentElement).colorScheme,
    ),
    theme,
  );
}
async function shot(name) {
  // Existing controls animate colors for 150ms; capture the settled palette.
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
  assert.equal(await page.locator("vite-error-overlay").count(), 0);
  assert.match(await page.title(), /Harbor/);
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  evidence.pages.push({ name, path: new URL(page.url()).pathname });
}
try {
  assert.equal(
    (await (await page.request.get(`${url}/api/v1/setup`)).json()).initialized,
    false,
    "requires fresh isolated state",
  );
  const resource = await page.request.get(`${url}/assets/theme-init.js`);
  evidence.resource = {
    status: resource.status(),
    headers: resource.headers(),
  };
  assert.equal(resource.status(), 200);
  assert.match(resource.headers()["content-type"], /javascript/);
  assert.equal(resource.headers()["x-content-type-options"], "nosniff");
  assert.match(
    resource.headers()["content-security-policy"],
    /script-src 'self'/,
  );
  for (const scriptFails of [false, true]) {
    const pre = await browser.newContext();
    await pre.addInitScript(() => {
      localStorage.setItem("harbor-helper.theme", "light");
      window.themeCsp = [];
      document.addEventListener("securitypolicyviolation", (e) =>
        window.themeCsp.push(e.violatedDirective),
      );
    });
    const p = await pre.newPage();
    if (scriptFails) await p.route("**/assets/theme-init.js", (r) => r.abort());
    let release, requested;
    const gate = new Promise((r) => {
        release = r;
      }),
      pending = new Promise((r) => {
        requested = r;
      });
    await p.route(/\/assets\/index-.*\.js$/, async (r) => {
      requested();
      await gate;
      await r.continue();
    });
    await p.goto(url, { waitUntil: "commit" });
    await pending;
    const started = Date.now();
    await p.waitForFunction(
      () =>
        document.body &&
        getComputedStyle(document.body).backgroundColor !== "rgba(0, 0, 0, 0)",
    );
    await p.waitForTimeout(2300);
    assert.equal(await p.locator("#root").innerHTML(), "");
    const state = await p.evaluate(() => ({
      theme: document.documentElement.dataset.theme,
      background: getComputedStyle(document.body).backgroundColor,
      csp: window.themeCsp,
    }));
    if (!scriptFails) {
      assert.equal(state.theme, "light");
      assert.equal(state.background, "rgb(247, 249, 250)");
    }
    const delayMs = Date.now() - started;
    await p.screenshot({
      path: `${out}/pre-react-script-${scriptFails ? "failed" : "ok"}.png`,
    });
    release();
    await p.getByRole("button", { name: "切换到暗主题" }).waitFor();
    assert.equal(
      await p.evaluate(() => document.documentElement.dataset.theme),
      "light",
    );
    assert.deepEqual(await p.evaluate(() => window.themeCsp), []);
    evidence.firstPaint.push({
      scriptFails,
      delayMs,
      preReact: state,
      recovery: "light",
    });
    await pre.close();
  }
  await page.goto(url);
  await page.getByText("首次网站设置", { exact: true }).waitFor();
  async function authShots(name) {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 960 });
      for (const theme of ["dark", "light"]) {
        if ((await page.locator("html").getAttribute("data-theme")) !== theme)
          await toggle().click();
        await checkTheme(theme);
        await shot(`${name}-${theme}-${width}`);
      }
    }
  }
  await authShots("setup");
  const password = "Synthetic-" + randomBytes(18).toString("hex"),
    username = "theme-admin";
  await page
    .getByLabel("部署引导凭证", { exact: true })
    .fill(
      (
        await readFile(`${process.env.HH_THEME_PRIVATE}/setup-token`, "utf8")
      ).trim(),
    );
  await page
    .getByLabel("团队名称", { exact: true })
    .fill("用于主题验证的非常长的合成研究团队名称".repeat(3));
  await page.getByLabel("首管理员用户名", { exact: true }).fill(username);
  await page
    .getByLabel("管理员密码（至少12位）", { exact: true })
    .fill(password);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("heading", { name: "登录团队实验室" }).waitFor();
  await authShots("login");
  async function login() {
    await page.getByLabel("账户", { exact: true }).fill(username);
    await page.getByLabel("密码", { exact: true }).fill(password);
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.locator("main h1").waitFor();
  }
  await login();
  await checkTheme("light");
  // Exercise real credential creation without persisting or screenshotting its raw value.
  await page.goto(url + "/access-credentials");
  await page
    .getByLabel("用途名称", { exact: true })
    .fill("Theme synthetic credential");
  await page.getByLabel("当前密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "签发凭证", exact: true }).click();
  await page.getByLabel("新签发凭证", { exact: true }).waitFor();
  await toggle().click();
  assert(await page.getByLabel("新签发凭证", { exact: true }).inputValue());
  await toggle().click();
  await page
    .getByRole("button", { name: "已安全保存，关闭原值", exact: true })
    .click();

  for (const width of [1440, 390])
    for (const theme of ["dark", "light"]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 960 });
      if ((await page.locator("html").getAttribute("data-theme")) !== theme)
        await toggle().click();
      for (const [name, path] of [
        ["empty-list", "/"],
        ["new", "/new"],
        ["history", "/operations"],
        ["compare", "/compare"],
        ["attachments", "/attachments"],
        ["account", "/account"],
        ["credentials", "/access-credentials"],
        ...[
          "readiness",
          "runtime",
          "dataset",
          "models",
          "users",
          "security",
          "limits",
        ].map((s) => [`admin-${s}`, `/admin?section=${s}`]),
      ]) {
        await page.goto(url + path);
        await page.locator("main h1").waitFor();
        await checkTheme(theme);
        await shot(`${name}-${theme}-${width}`);
        if (name === "attachments") {
          await page.locator('input[type="file"]').setInputFiles({
            name: "synthetic.zip",
            mimeType: "application/zip",
            buffer: Buffer.from("not uploaded"),
          });
          const before = evidence.requests.length;
          await toggle().click();
          await page
            .getByRole("button", {
              name: theme === "dark" ? "切换到暗主题" : "切换到明主题",
            })
            .waitFor();
          assert.equal(
            await page
              .locator('input[type="file"]')
              .evaluate((el) => el.files[0].name),
            "synthetic.zip",
          );
          assert.deepEqual(evidence.requests.slice(before), []);
          await toggle().click();
        }
        if (name === "empty-list" && width === 390) {
          await page
            .getByRole("button", { name: "打开导航", exact: true })
            .click();
          await shot(`drawer-${theme}-${width}`);
          await page.keyboard.press("Escape");
        }
      }
    }
  await page.goto(url + "/admin");
  const form = page
    .locator("form")
    .filter({ has: page.getByLabel("名称", { exact: true }) });
  await form.getByLabel("名称", { exact: true }).fill("Theme synthetic team");
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await page.locator("[data-sonner-toast]").first().waitFor();
  await shot("real-success-toast-light");
  await toggle().click();
  await shot("real-success-toast-dark");
  await toggle().click();
  // Logout on mobile is inside navigation.
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await page.getByRole("heading", { name: "登录团队实验室" }).waitFor();
  await checkTheme("light");
  await page.reload();
  await page.getByRole("heading", { name: "登录团队实验室" }).waitFor();
  await checkTheme("light");
  await login();
  await checkTheme("light");
  assert.deepEqual(errors, []);
  evidence.errors = errors;
  evidence.limitations = [
    "No real experiments, Hub, model or Docker operations",
    "OS popup color is browser controlled",
    "Help absent from baseline",
  ];
  await writeFile(`${out}/production.json`, JSON.stringify(evidence, null, 2));
  console.log(
    JSON.stringify({
      success: true,
      pages: evidence.pages.length,
      firstPaint: evidence.firstPaint,
      output: out,
    }),
  );
} finally {
  await browser.close();
}

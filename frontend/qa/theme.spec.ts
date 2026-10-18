import { test, expect, type Page } from "@playwright/test";
import { fixture } from "./fixture";

const key = "harbor-helper.theme";
const themeRoot = (page: Page) => page.locator("html");
const toggle = (page: Page) =>
  page.getByRole("button", { name: /切换到[明暗]主题/ });

test("theme preserves mounted form, file, focus and URL without business requests", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/attachments");
  const file = page.locator('input[type="file"]');
  await file.setInputFiles({
    name: "theme.zip",
    mimeType: "application/zip",
    buffer: Buffer.from("fixture"),
  });
  const input = page
    .locator('input:not([type="file"]):not([type="checkbox"])')
    .first();
  await input.fill("未保存附件草稿");
  // Mark the live nodes: remounting must not silently recreate them.
  await file.evaluate((node) => node.setAttribute("data-retained", "yes"));
  const url = page.url();
  const requests: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/")) requests.push(`${r.method()} ${r.url()}`);
  });
  await toggle(page).focus();
  await page.keyboard.press("Enter");
  await expect(themeRoot(page)).toHaveAttribute("data-theme", "light");
  await expect(toggle(page)).toBeFocused();
  await expect(input).toHaveValue("未保存附件草稿");
  await expect(file).toHaveAttribute("data-retained", "yes");
  expect(
    await file.evaluate((node: HTMLInputElement) => node.files?.[0]?.name),
  ).toBe("theme.zip");
  expect(page.url()).toBe(url);
  expect(requests).toEqual([]);
  expect(
    await page.evaluate(() => localStorage.getItem("harbor-helper.theme")),
  ).toBe("light");
  await toggle(page).click();
  await expect(themeRoot(page)).toHaveAttribute("data-theme", "dark");
});

test("preference survives routes, reload and logout; other tabs synchronize changes and clearing", async ({
  page,
  context,
}) => {
  await fixture(page);
  await page.goto("/");
  await toggle(page).click();
  await page.getByRole("link", { name: "账户与密码", exact: true }).click();
  await expect(themeRoot(page)).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(themeRoot(page)).toHaveAttribute("data-theme", "light");
  const other = await context.newPage();
  await fixture(other, "member");
  await other.goto("/");
  await expect(themeRoot(other)).toHaveAttribute("data-theme", "light");
  await toggle(other).click();
  await expect(themeRoot(page)).toHaveAttribute("data-theme", "dark");
  await toggle(page).click();
  await expect(themeRoot(other)).toHaveAttribute("data-theme", "light");
  await other.evaluate(() => localStorage.clear());
  await expect(themeRoot(page)).toHaveAttribute("data-theme", "dark");
  await toggle(page).click();
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "登录团队实验室" }),
  ).toBeVisible();
  await expect(themeRoot(page)).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(themeRoot(page)).toHaveAttribute("data-theme", "light");
});

for (const saved of [null, "dark", "light", "invalid", "LIGHT", ""]) {
  for (const scriptFails of [false, true]) {
    test(`early script / React agree for ${JSON.stringify(saved)}, scriptFails=${scriptFails}`, async ({
      page,
    }) => {
      await fixture(page, "member", false);
      await page.addInitScript(
        ({ key, saved }) => {
          if (saved === null) localStorage.removeItem(key);
          else localStorage.setItem(key, saved);
        },
        { key, saved },
      );
      if (scriptFails)
        await page.route("**/assets/theme-init.js", (route) => route.abort());
      let release!: () => void;
      const gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      await page.route("**/src/main.tsx", async (route) => {
        await gate;
        await route.continue();
      });
      await page.goto("/", { waitUntil: "commit" });
      const expected = saved === "light" ? "light" : "dark";
      if (!scriptFails)
        await expect(themeRoot(page)).toHaveAttribute("data-theme", expected);
      release();
      await expect(toggle(page)).toBeVisible();
      await expect(themeRoot(page)).toHaveAttribute("data-theme", expected);
      expect(
        await page.evaluate(
          () => getComputedStyle(document.documentElement).colorScheme,
        ),
      ).toBe(expected);
    });
  }
}

for (const failure of ["read", "write", "both"]) {
  test(`storage ${failure} failure keeps auth and theme control usable`, async ({
    page,
  }) => {
    await fixture(page, "admin", false);
    await page.addInitScript((failure) => {
      if (failure !== "write")
        Storage.prototype.getItem = () => {
          throw new DOMException("Blocked", "SecurityError");
        };
      if (failure !== "read")
        Storage.prototype.setItem = () => {
          throw new DOMException("Full", "QuotaExceededError");
        };
    }, failure);
    await page.goto("/");
    await expect(toggle(page)).toBeVisible();
    await page.getByLabel("账户", { exact: true }).fill("draft");
    await toggle(page).click();
    await expect(themeRoot(page)).toHaveAttribute("data-theme", "light");
    await expect(page.getByLabel("账户", { exact: true })).toHaveValue("draft");
    await toggle(page).click();
    await expect(themeRoot(page)).toHaveAttribute("data-theme", "dark");
  });
}

test("setup entry and mobile long team name keep the theme control visible", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixture(page);
  await page.route("**/api/v1/setup", (route) =>
    route.fulfill({ json: { initialized: false } }),
  );
  await page.goto("/");
  await expect(page.getByText("首次网站设置", { exact: true })).toBeVisible();
  await toggle(page).click();
  await expect(themeRoot(page)).toHaveAttribute("data-theme", "light");
  await page.unroute("**/api/v1/setup");
  await page.route("**/api/v1/catalog", async (route) => {
    const { catalog } = await import("./fixture");
    await route.fulfill({
      json: {
        ...catalog,
        settings: { team_name: "非常长的团队名称".repeat(20) },
      },
    });
  });
  await page.goto("/");
  await expect(page.locator(".topbar .theme-toggle")).toBeInViewport();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "打开导航", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "工作空间导航" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await toggle(page).click();
  await expect(themeRoot(page)).toHaveAttribute("data-theme", "dark");
});

test("existing toast follows theme and native confirmation remains usable", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/admin");
  const form = page
    .locator("form")
    .filter({ has: page.getByLabel("名称", { exact: true }) });
  await form.getByLabel("名称", { exact: true }).fill("Synthetic theme team");
  await form.getByRole("button", { name: "保存", exact: true }).click();
  const toaster = page.locator("[data-sonner-toaster]");
  await expect(
    page.locator('[data-sonner-toast][data-type="success"]').first(),
  ).toBeVisible();
  await toggle(page).click();
  await expect(toaster).toHaveAttribute("data-sonner-theme", "light");
  await expect(
    page.locator('[data-sonner-toast][data-type="success"]').first(),
  ).toBeVisible();
  await page.goto("/runs/hh-other-running");
  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.method() !== "GET" && r.url().includes("/api/")) writes.push(r.url());
  });
  page.once("dialog", async (dialog) => {
    expect(dialog.type()).toBe("confirm");
    await dialog.dismiss();
  });
  await page.getByRole("button", { name: "取消实验", exact: true }).click();
  expect(writes).toEqual([]);
  await page.route("**/api/v1/runs/hh-other-running/rerun", (r) =>
    r.fulfill({
      status: 409,
      json: { code: "theme_fixture_error", message: "合成重跑错误" },
    }),
  );
  await page.getByRole("button", { name: "按原条件重跑", exact: true }).click();
  await expect(
    page.locator('[data-sonner-toast][data-type="error"]').first(),
  ).toBeVisible();
  await toggle(page).click();
  await expect(toaster).toHaveAttribute("data-sonner-theme", "dark");
  await expect(
    page.locator('[data-sonner-toast][data-type="error"]').first(),
  ).toBeVisible();
});

for (const width of [1440, 390])
  test(`body help portal follows cross-tab theme without resetting compare ${width}`, async ({
    page,
    context,
  }) => {
    await fixture(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/compare");
    await page
      .getByLabel("实验 A", { exact: true })
      .selectOption("hh-test-zero");
    const other = await context.newPage();
    await fixture(other);
    await other.goto("/");
    const help = page.getByRole("button", { name: "实验 A帮助", exact: true });
    await help.click();
    const portal = page.getByRole("dialog");
    await expect(portal).toBeVisible();
    expect(
      await portal.evaluate(
        (el) => !document.getElementById("root")!.contains(el),
      ),
    ).toBe(true);
    const before = await portal.evaluate(
      (el) => getComputedStyle(el).backgroundColor,
    );
    const calls: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/")) calls.push(r.url());
    });
    await other.getByRole("button", { name: "切换到明主题" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(portal).toBeVisible();
    await expect
      .poll(() => portal.evaluate((el) => getComputedStyle(el).backgroundColor))
      .not.toBe(before);
    await expect(
      page.getByRole("combobox", { name: "实验 A", exact: true }),
    ).toHaveValue("hh-test-zero");
    expect(calls).toEqual([]);
    await page.keyboard.press("Escape");
  });

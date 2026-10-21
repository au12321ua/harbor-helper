import { test, fixture, catalog, run } from "../../support/fixture";
import { expect } from "@playwright/test";
import { redesignFixture } from "../../support/ui-support";
test("workbench visual evidence at approved desktop laptop and mobile dimensions", async ({
  page,
}) => {
  await redesignFixture(page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.route("**/api/v1/catalog", (route) =>
    route.fulfill({
      json: {
        ...catalog,
        settings: {
          ...catalog.settings,
          team_name: "研究团队",
          default_model_profile: "plan1",
        },
      },
    }),
  );
  await page.route("**/api/v1/runs/hh-test-zero", (route) =>
    route.fulfill({
      json: {
        row: {
          ...run,
          name: "cad-baseline / tool-preparation",
          status: "running",
          audit_status: "pending",
          agent: "opencode",
        },
        manifest: {
          source: { dataset: "team/test@1" },
          effective: {
            agent: "opencode",
            wall_seconds: 1800,
            attempts: 1,
            concurrency: 2,
            environment_build_timeout_multiplier: 10,
            agent_tool_preparation: "offline-npm-binary-v1",
          },
          service: { attachment_version_id: null },
          startup_policy: { multiplier: 10, tasks: [] },
        },
        report: null,
        artifacts: [],
      },
    }),
  );
  for (const [width, height] of [
    [1440, 960],
    [1280, 800],
    [390, 844],
  ]) {
    await page.setViewportSize({ width, height });
    for (const [name, url] of [
      ["list", "/"],
      ["detail", "/runs/hh-test-zero"],
      ["compare", "/compare?left=run-a&right=run-b"],
      ["new", "/new"],
      ["admin", "/admin?section=models"],
      ["attachments", "/attachments"],
      ["account", "/account"],
      ["credentials", "/access-credentials"],
    ]) {
      await page.goto(url);
      await expect(page.locator("main h1")).toBeVisible();
      if (name === "compare") {
        await page.getByRole("button", { name: "开始对比" }).click();
        await expect(page.locator(".compare-table")).toBeVisible();
      }
      if (name === "admin") {
        await page
          .getByRole("button", { name: "编辑方案", exact: true })
          .click();
        await page
          .locator(".models-workspace .table-shell div")
          .evaluateAll((nodes) =>
            nodes.forEach((node) => {
              node.scrollLeft = 0;
            }),
          );
      }
      if (name === "detail")
        await expect(page.locator(".log-view")).toBeVisible();
      expect(await page.title()).toContain("Harbor");
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      const tiny = await page.locator("main").evaluate((root) =>
        Array.from(root.querySelectorAll("*"))
          .filter(
            (el) =>
              Array.from(el.childNodes).some(
                (node) =>
                  node.nodeType === Node.TEXT_NODE && node.textContent?.trim(),
              ) &&
              el.getBoundingClientRect().width > 2 &&
              el.getBoundingClientRect().height > 2 &&
              getComputedStyle(el).visibility !== "hidden" &&
              parseFloat(getComputedStyle(el).fontSize) < 11,
          )
          .map((el) => `${el.tagName} ${el.textContent?.slice(0, 50)}`),
      );
      expect(tiny).toEqual([]);
      await page.screenshot({
        path: test.info().outputPath(`${name}-${width}.png`),
        fullPage: false,
      });
    }
  }
  expect(errors).toEqual([]);
});

test("login setup and empty error surfaces use the same workbench visual system", async ({
  page,
}) => {
  await fixture(page, "member", false);
  for (const width of [1440, 1280, 390]) {
    await page.setViewportSize({
      width,
      height: width === 390 ? 844 : width === 1280 ? 800 : 960,
    });
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "登录团队实验室" }),
    ).toBeVisible();
    await page.screenshot({
      path: test.info().outputPath(`login-${width}.png`),
    });
  }
  await page.route("**/api/v1/setup", (route) =>
    route.fulfill({ json: { initialized: false } }),
  );
  for (const width of [1440, 1280, 390]) {
    await page.setViewportSize({
      width,
      height: width === 390 ? 844 : width === 1280 ? 800 : 960,
    });
    await page.goto("/");
    await expect(page.getByLabel("部署引导凭证")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: test.info().outputPath(`setup-${width}.png`),
    });
  }
});

for (const width of [1440, 1024, 390]) {
  test(`网页体验：对齐、问号与跨页巡检 ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    await fixture(page);
    await page.route("**/api/v1/runs", route => route.fulfill({json:{runs:[{...run,id:"long-a",name:"非常长的实验名称".repeat(12),dataset:"team/"+"long".repeat(80)},{...run,id:"long-b",name:"实验B"}],total:2}}));
    await page.goto("/compare");
    for (const pair of [["", ""], ["long-a", ""], ["", "long-b"], ["long-a", "long-b"]]) {
      await page.getByLabel("实验 A",{exact:true}).selectOption(pair[0]);
      await page.getByLabel("实验 B",{exact:true}).selectOption(pair[1]);
      const a = await page.getByLabel("实验 A",{exact:true}).boundingBox(), b = await page.getByLabel("实验 B",{exact:true}).boundingBox();
      if (width > 600) expect(Math.abs(a!.y-b!.y)).toBeLessThan(2);
      expect(a!.width).toBeLessThan(width);
    }
    await page.screenshot({path:test.info().outputPath(`compare-${width}.png`),fullPage:true});
    const help = page.getByRole("button",{name:"实验 A帮助",exact:true});
    await help.hover();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.locator("h1").click();
    await help.focus();
    await expect(page.getByRole("dialog")).toBeVisible();
    await help.click();
    await expect(page.getByRole("dialog")).toBeVisible();
    const box = await page.getByRole("dialog").boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.x+box!.width).toBeLessThanOrEqual(width);
    await page.screenshot({path:test.info().outputPath(`help-${width}.png`)});
    await page.locator("h1").click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    for (const url of ["/new", "/runs/hh-test-zero", "/attachments", "/admin?section=models", "/admin?section=readiness", "/admin?section=limits", "/admin?section=users", "/access-credentials"]) {
      await page.route("**/api/v1/access-credentials", route => route.fulfill({json:[]}));
      await page.goto(url);
      await expect(page.locator("main h1")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width+1);
      const triggers = page.getByRole("button",{name:/帮助$/});
      if (await triggers.count()) {
        await triggers.first().click(); await expect(page.getByRole("dialog")).toBeVisible();
        await page.keyboard.press("Escape"); await expect(page.getByRole("dialog")).toHaveCount(0);
      }
      await page.screenshot({path:test.info().outputPath(`${url.replace(/[^a-z]/g,"-")}-${width}.png`),fullPage:true});
    }
    expect(errors).toEqual([]);
  });
}

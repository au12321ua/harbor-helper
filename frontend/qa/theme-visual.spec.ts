import { test, expect, type Page } from "@playwright/test";
import { fixture, catalog, run } from "./fixture";
import { contrastSamples } from "./theme-contrast";
import { writeFile } from "node:fs/promises";

async function themeFixture(page: Page) {
  await fixture(page);
  await page.route("**/api/v1/catalog", (r) =>
    r.fulfill({
      json: {
        ...catalog,
        settings: {
          ...catalog.settings,
          team_name: "一个很长的研究团队名称用于验证手机主题入口仍然可达",
        },
      },
    }),
  );
  await page.route("**/api/v1/runs", (r) =>
    r.fulfill({
      json: {
        runs: [
          run,
          ...[
            "queued",
            "preparing",
            "running",
            "starting",
            "cancelling",
            "failed",
            "cleanup_blocked",
            "incomplete",
            "cancelled",
          ].map((status, i) => ({
            ...run,
            id: `state-${i}`,
            status,
            name: `状态示例 ${status}`,
          })),
        ],
        submissions: [],
      },
    }),
  );
  await page.route("**/api/v1/attachments", (r) =>
    r.fulfill({ json: { attachments: [] } }),
  );
  await page.route("**/api/v1/access-credentials", (r) =>
    r.fulfill({ json: [] }),
  );
  await page.route("**/api/v1/admin/access-credentials", (r) =>
    r.fulfill({ json: [] }),
  );
  await page.route("**/api/v1/admin/master-key", (r) =>
    r.fulfill({ json: { generation: 1, available: true } }),
  );
  await page.route("**/api/v1/operations?**", (r) =>
    r.fulfill({
      json: {
        operations: [
          {
            id: "op-theme",
            operation: "submit",
            status: "rejected",
            attempts: 2,
            idem: "theme-fixture",
            user_id: "u1",
            summarized_attempts: 0,
            request: { name: "合成请求" },
            error: { code: "queue_full" },
            recent: [],
          },
        ],
        total: 1,
        next_offset: null,
      },
    }),
  );
  await page.route("**/api/v1/runs/hh-test-zero/evidence", (r) =>
    r.fulfill({
      json: {
        state: "available",
        scope: "合成资料范围",
        limitations: ["无真实执行"],
        files: [
          {
            id: "f1",
            name: "fixture.log",
            category: "log",
            status: "redacted",
            bytes: 42,
            sha256: "a".repeat(64),
            processing: "合成脱敏说明",
          },
        ],
      },
    }),
  );
  await page.route("**/api/v1/compare", (r) =>
    r.fulfill({
      json: {
        comparable: true,
        reasons: [],
        left: run,
        right: run,
        attachment_inputs: { left: { kind: "none" }, right: { kind: "none" } },
        tasks: [
          {
            task: "fixture-task",
            left: { reward: 0 },
            right: { reward: 0.8 },
            delta: { reward: 0.8 },
          },
        ],
        mean_task_delta: { reward: 0.8 },
      },
    }),
  );
}

for (const width of [1440, 390])
  for (const theme of ["dark", "light"]) {
    test(`all pages and states ${theme} ${width}`, async ({ page }) => {
      test.setTimeout(90000);
      await page.setViewportSize({ width, height: width === 390 ? 844 : 960 });
      await page.addInitScript(
        (theme) => localStorage.setItem("harbor-helper.theme", theme),
        theme,
      );
      await themeFixture(page);
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      page.on("console", (m) => {
        if (["warning", "error"].includes(m.type())) errors.push(m.text());
      });
      const samples: object[] = [];
      async function capture(name: string) {
        expect(await page.title()).toContain("Harbor");
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await expect(page.locator("vite-error-overlay")).toHaveCount(0);
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        ).toBe(true);
        await page.screenshot({
          path: test.info().outputPath(`${theme}-${width}-${name}.png`),
          fullPage: true,
        });
        const colors = await contrastSamples(page);
        samples.push({ page: name, colors });
        expect(
          colors.filter((c) => c.ratio < c.minimum),
          `contrast ${name}`,
        ).toEqual([]);
      }
      for (const [name, url] of [
        ["list", "/"],
        ["new", "/new"],
        ["history", "/operations"],
        ["preparation", "/submissions/submission-test"],
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
        ["compare", "/compare?left=hh-test-zero&right=state-5"],
        ["detail", "/runs/hh-test-zero"],
        ["not-found", "/not-found"],
      ]) {
        await page.goto(url);
        if (name === "not-found")
          await expect(
            page.getByText("页面不存在", { exact: true }),
          ).toBeVisible();
        else await expect(page.locator("main h1")).toBeVisible();
        if (name === "compare") {
          await page.getByRole("button", { name: "开始对比" }).click();
          await expect(page.locator(".compare-table")).toBeVisible();
        }
        if (name === "history")
          await page.locator("main details summary").click();
        if (name === "admin-models")
          await page
            .getByRole("button", { name: "编辑方案", exact: true })
            .click();
        await page.locator(".theme-toggle").focus();
        await capture(name);
        if (name === "list") {
          await page
            .getByRole("checkbox", { name: "选择实验 hh-test-zero" })
            .check();
          await page.locator(".run-link").first().hover();
          // Allow the existing color transition to settle before auditing hover.
          await page.waitForTimeout(200);
          await capture("list-selected-hover");
        }

        if (name === "list" && width === 390) {
          await page
            .getByRole("button", { name: "打开导航", exact: true })
            .click();
          await capture("drawer");
          await page.keyboard.press("Escape");
        }
        if (name === "detail") {
          await page.locator(".raw-details summary").click();
          await capture("detail-json");
          for (const tab of ["评分报告", "运行日志", "实验产物", "完整资料"]) {
            await page.getByRole("tab", { name: tab, exact: true }).click();
            await expect(page.getByRole("tabpanel")).toBeVisible();
            await capture(`detail-${tab}`);
          }
          await page.getByRole("button", { name: "复制实验 ID" }).click();
          await expect(page.locator("[data-sonner-toast]")).toBeVisible();
          await capture("toast");
        }
      }
      // Retained data after a refresh error remains readable rather than dimmed.
      await page.goto("/");
      await expect(page.locator("main h1")).toBeVisible();
      await page.route("**/api/v1/runs", (r) =>
        r.fulfill({
          status: 503,
          json: { code: "fixture_unavailable", message: "合成刷新错误" },
        }),
      );
      await page.getByRole("button", { name: "刷新实验", exact: true }).click();
      await expect(page.locator(".table-shell.stale")).toBeVisible();
      await capture("stale-retained-list");
      // Hold the request to inspect an actual loading surface in each palette.
      let release!: () => void;
      const gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      await page.route(
        "**/api/v1/runs",
        async (r) => {
          await gate;
          await r.fulfill({ json: { runs: [], submissions: [] } });
        },
        { times: 1 },
      );
      await page.reload();
      await expect(page.locator("main .animate-pulse").first()).toBeVisible();
      await capture("loading");
      release();
      await expect(page.getByText("暂无实验", { exact: true })).toBeVisible();
      await capture("empty-list");
      await page.route("**/api/v1/runs", (r) =>
        r.fulfill({
          status: 503,
          json: {
            code: "fixture_unavailable",
            message: "合成加载错误，可重试",
          },
        }),
      );
      await page.goto("/");
      await expect(
        page.getByText("合成加载错误，可重试", { exact: true }),
      ).toBeVisible();
      await capture("error");
      // Expected HTTP 503 is the only console error in this deliberately failing request.
      expect(
        errors.filter((e) => !e.includes("503 (Service Unavailable)")),
      ).toEqual([]);
      await page.route("**/api/v1/setup", (r) =>
        r.fulfill({ json: { initialized: false } }),
      );
      await page.goto("/");
      await expect(
        page.getByText("首次网站设置", { exact: true }),
      ).toBeVisible();
      await capture("setup");
      await page.route("**/api/v1/setup", (r) =>
        r.fulfill({ json: { initialized: true } }),
      );
      await page.route("**/api/v1/me", (r) =>
        r.fulfill({
          status: 401,
          json: { code: "unauthorized", message: "请登录" },
        }),
      );
      await page.goto("/");
      await expect(
        page.getByRole("heading", { name: "登录团队实验室" }),
      ).toBeVisible();
      await capture("login");
      await writeFile(
        test.info().outputPath(`contrast-${theme}-${width}.json`),
        JSON.stringify(samples, null, 2),
      );
    });
  }

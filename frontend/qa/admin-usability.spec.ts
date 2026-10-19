import { writeFile } from "node:fs/promises";
import { test, expect, type Page } from "@playwright/test";
import { fixture, catalog } from "./fixture";
test.use({ timezoneId: "Europe/London" });

function data(large = false): any {
  const c: any = structuredClone(catalog);
  const tasks = Array.from({ length: large ? 500 : 2 }, (_, i) => ({
    name: `task-${i}-${"长任务名称".repeat(large ? 15 : 1)}`,
    package: `team/package-${i}`,
    ref: "sha256:fixed",
  }));
  c.datasets = [0, 1].map((i) => ({
    ...c.datasets[0],
    id: `dataset${i + 1}`,
    name: `数据集${i + 1}`,
    enabled: true,
    status: "verified",
    resolved: "team/test@sha256:fixed",
    tasks,
    author_parameters: {
      id: `dataset${i + 1}`,
      version: 10,
      status: "checked",
      checked: 1791460000,
      values: { VAR_0: "saved" },
      discovery: {
        source: "fixed",
        fixed_names: [],
        blocked: [],
        variables: Object.fromEntries(
          Array.from({ length: large ? 40 : 1 }, (_, v) => [
            `VAR_${v}`,
            Array.from({ length: 10 }, (_, j) => ({
              task: tasks[j % tasks.length].name,
              file: "environment/docker-compose.yaml",
              required: false,
              default: "default",
            })),
          ]),
        ),
        budgets: tasks.map((t, j) => ({
          task: t.package,
          agent_seconds: j === 0 ? 0 : j,
          verifier_seconds: j === 0 ? null : 10,
        })),
        images: Array.from({ length: large ? 100 : 1 }, (_, j) => ({
          task: tasks[j % tasks.length].name,
          role: "agent",
          reference: `example.invalid/image-${j}`,
          cached: false,
        })),
      },
      issues: [],
    },
  }));
  return c;
}
async function setup(page: Page, c = data()) {
  const calls = await fixture(page);
  await page.route("**/api/v1/catalog", (route) => route.fulfill({ json: c }));
  await page.goto("/admin?section=dataset");
  await expect(page.getByText("数据集1", { exact: true })).toBeVisible();
  return calls;
}
function card(page: Page, n: number) {
  return page
    .locator('[data-slot="card"]')
    .filter({ has: page.getByText(`数据集${n}`, { exact: true }) });
}
async function zone(page: Page, value: string) {
  await page.getByRole("button", { name: /^显示时区 .*帮助$/ }).click();
  await page.getByLabel("显示时区", { exact: true }).selectOption(value);
  await page.keyboard.press("Escape");
}

test("long check survives tabs/routes; other dataset saves and mounted drafts survive refresh and timezone", async ({
  page,
}) => {
  const c = data();
  await setup(page, c);
  let release!: () => void;
  await page.route(
    "**/api/v1/admin/datasets/dataset1/author-inputs/check",
    async (route) => {
      await new Promise<void>((r) => (release = r));
      c.datasets[0].author_parameters.version++;
      await route.fulfill({ json: c.datasets[0].author_parameters });
    },
  );
  await page.route(
    "**/api/v1/admin/datasets/dataset2/author-inputs",
    async (route) => {
      c.datasets[1].author_parameters.values = route
        .request()
        .postDataJSON().values;
      await route.fulfill({ json: c.datasets[1].author_parameters });
    },
  );
  const first = card(page, 1),
    second = card(page, 2);
  await first
    .getByRole("button", { name: "检查作者参数", exact: true })
    .click();
  await expect(first.getByLabel("VAR_0", { exact: true })).toBeDisabled();
  await expect(
    second.getByRole("button", { name: "验证", exact: true }),
  ).toBeDisabled();
  await second.getByLabel("VAR_0", { exact: true }).fill("other saved");
  await second.getByRole("button", { name: "保存", exact: true }).click();
  await expect(second.getByText(/保存完成/)).toBeVisible();
  await second.getByLabel("VAR_0", { exact: true }).fill("unsaved survives");
  await page.getByLabel("数据集名称", { exact: true }).fill("new draft");
  await zone(page, "UTC");
  release();
  await expect(first.getByText(/已收到回执/)).toBeVisible();
  await expect(second.getByLabel("VAR_0", { exact: true })).toHaveValue(
    "unsaved survives",
  );
  await expect(page.getByLabel("数据集名称", { exact: true })).toHaveValue(
    "new draft",
  );
  const ids = await page
    .locator("input[id]")
    .evaluateAll((elements) => elements.map((e) => e.id));
  expect(new Set(ids).size).toBe(ids.length);
  // A second operation remains tracked across a route unmount.
  await first.getByRole("button", { name: "验证", exact: true }).click(); // fixture response has no status -> unknown
  await expect(first.getByText(/结果未知/)).toBeVisible();
});

test("source verification stays in flight across tabs and routes", async ({
  page,
}) => {
  const c = data();
  await setup(page, c);
  let release!: () => void;
  await page.route(
    "**/api/v1/admin/catalog/dataset/dataset1/verify",
    async (route) => {
      await new Promise<void>((r) => (release = r));
      await route.fulfill({ json: c.datasets[0] });
    },
  );
  await card(page, 1)
    .getByRole("button", { name: "编辑", exact: true })
    .click();
  await card(page, 1)
    .getByRole("button", { name: "验证", exact: true })
    .click();
  await expect(
    page.getByLabel("Hub 来源（owner/name，可指定版本）", { exact: true }),
  ).toBeDisabled();
  await page.getByRole("tab", { name: "受邀账户" }).click();
  await expect(
    page
      .locator('[data-slot="card-title"]')
      .filter({ hasText: /^test-admin$/ }),
  ).toBeVisible();
  await page.getByRole("link", { name: "账户与密码", exact: true }).click();
  await page.getByRole("link", { name: "团队管理", exact: true }).click();
  await page.getByRole("tab", { name: "数据集", exact: true }).click();
  await expect(card(page, 1).getByText(/来源验证中/)).toBeVisible();
  await expect(
    card(page, 2).getByRole("button", { name: "检查作者参数", exact: true }),
  ).toBeDisabled();
  release();
  await expect(card(page, 1).getByText(/来源验证成功/)).toBeVisible();
});

test("author draft requires save or explicit discard before long operation", async ({
  page,
}) => {
  await setup(page);
  const first = card(page, 1);
  await first.getByLabel("VAR_0", { exact: true }).fill("unsaved");
  await expect(
    first.getByRole("button", { name: "检查作者参数", exact: true }),
  ).toBeDisabled();
  await expect(
    first.getByRole("button", { name: "验证", exact: true }),
  ).toBeDisabled();
  page.once("dialog", (d) => d.dismiss());
  await first.getByRole("button", { name: "放弃此数据集草稿" }).click();
  await expect(first.getByLabel("VAR_0", { exact: true })).toHaveValue(
    "unsaved",
  );
  page.once("dialog", (d) => d.accept());
  await first.getByRole("button", { name: "放弃此数据集草稿" }).click();
  await expect(first.getByLabel("VAR_0", { exact: true })).toHaveValue("saved");
  await expect(
    first.getByRole("button", { name: "验证", exact: true }),
  ).toBeEnabled();
});

for (const mode of [
  "configuration_changed",
  "source_network",
  "500",
  "disconnect",
  "blocked",
  "refresh-failure",
] as const) {
  test(`long operation feedback: ${mode}`, async ({ page }) => {
    await setup(page);
    let requests = 0;
    await page.route(
      "**/api/v1/admin/catalog/dataset/dataset1/verify",
      async (route) => {
        requests++;
        if (mode === "disconnect") {
          await route.abort("connectionfailed");
          return;
        }
        if (mode === "refresh-failure")
          await page.route("**/api/v1/catalog", (r) =>
            r.fulfill({
              status: 503,
              json: { code: "unavailable", message: "refresh failed" },
            }),
          );
        await route.fulfill(
          mode === "blocked"
            ? { json: { status: "blocked" } }
            : mode === "refresh-failure"
              ? { json: { status: "verified" } }
              : {
                  status: mode === "500" ? 500 : 409,
                  json: {
                    code: mode === "500" ? "internal" : mode,
                    message: "injected",
                  },
                },
        );
      },
    );
    const first = card(page, 1);
    await first.getByRole("button", { name: "验证", exact: true }).click();
    await expect(
      first.getByText(
        mode === "configuration_changed"
          ? /来源已变更或失效/
          : mode === "source_network"
            ? /服务拒绝（source_network）/
            : mode === "blocked"
              ? /来源验证未通过/
              : mode === "refresh-failure"
                ? /来源验证成功/
                : /结果未知/,
      ),
    ).toBeVisible();
    if (mode === "refresh-failure")
      await expect(page.getByText(/操作已完成，结果刷新失败/)).toBeVisible();
    if (mode === "500" || mode === "disconnect") {
      page.once("dialog", (d) => d.dismiss());
      await first.getByRole("button", { name: "验证", exact: true }).click();
      expect(requests).toBe(1);
      await first.getByRole("button", { name: "刷新最近已保存结果" }).click();
      await expect(first.getByText(/结果未知/)).toBeVisible();
    }
    expect(requests).toBe(1);
    await expect(first.getByText(/最近已保存结果/).first()).toBeVisible();
  });
}

test("timezone maintenance handles DST gaps, overlap, cross-day and preserves epoch", async ({
  page,
}) => {
  const calls = await fixture(page);
  await page.goto("/admin?section=limits");
  await zone(page, "America/New_York");
  const retry = page.getByLabel(/建议重试时间（可选/);
  await retry.fill("2026-03-08T02:30");
  await expect(page.getByText(/该本地时刻不存在/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "暂停新受理", exact: true }),
  ).toBeDisabled();
  await retry.fill("2026-11-01T01:30");
  await expect(page.getByText(/此时刻重复/)).toBeVisible();
  const offsets = page.getByLabel("选择重复时刻的明确偏移");
  await expect(offsets.locator("option")).toHaveCount(3);
  await offsets.selectOption(String(Date.parse("2026-11-01T06:30:00Z") / 1000));
  await zone(page, "Asia/Shanghai");
  await expect(retry).toHaveValue("2026-11-01T14:30");
  await page.getByRole("button", { name: "暂停新受理", exact: true }).click();
  await expect
    .poll(
      () =>
        calls.find((c) => c.path === "/admin/maintenance" && c.body)?.body
          .retry_at,
    )
    .toBe(Date.parse("2026-11-01T06:30:00Z") / 1000);
  await retry.fill("2026-11-02T00:30");
  await zone(page, "UTC");
  await expect(retry).toHaveValue("2026-11-01T16:30");
  await expect(page.getByText(/将提交绝对时刻/)).toContainText(
    "2026-11-01T16:30:00.000Z",
  );
});

test("timezone preference persists, updates across tabs, rejects invalid storage and survives unavailable storage", async ({
  page,
  context,
}) => {
  await setup(page);
  await zone(page, "UTC");
  await page.reload();
  await expect(
    page.getByRole("button", { name: "显示时区 UTC帮助", exact: true }),
  ).toBeVisible();
  const other = await context.newPage();
  await fixture(other);
  await other.goto("/");
  await zone(page, "Asia/Shanghai");
  await expect(
    other.getByRole("button", {
      name: "显示时区 Asia/Shanghai帮助",
      exact: true,
    }),
  ).toBeVisible();
  await page.evaluate(() =>
    localStorage.setItem("harbor-helper.timezone", "Invalid/Zone"),
  );
  await page.reload();
  await expect(
    page.getByRole("button", { name: /^显示时区 .*帮助$/ }),
  ).toBeVisible();
  await page.evaluate(() => {
    Storage.prototype.setItem = () => {
      throw new Error("unavailable");
    };
  });
  await zone(page, "America/New_York");
  await expect(
    page.getByRole("button", { name: "显示时区 America/New_York帮助" }),
  ).toBeVisible();
});

for (const attempt of [1, 2, 3])
  test(`large discovery responsiveness ${attempt}`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1440, height: 960 });
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    const c = data(true);
    c.datasets = [c.datasets[0]];
    const discovery = c.datasets[0].author_parameters.discovery;
    c.datasets[0].author_parameters.discovery = null;
    await setup(page, c);
    let release!: () => void;
    await page.route(
      "**/api/v1/admin/datasets/dataset1/author-inputs/check",
      async (route) => {
        await new Promise<void>((r) => (release = r));
        c.datasets[0].author_parameters.version++;
        c.datasets[0].author_parameters.discovery = discovery;
        await route.fulfill({ json: c.datasets[0].author_parameters });
      },
    );
    await card(page, 1)
      .getByRole("button", { name: "检查作者参数", exact: true })
      .click();
    await page.evaluate(() => {
      const w = window as any;
      w.beats = [];
      w.lastBeat = performance.now();
      w.beatTimer = setInterval(() => {
        const now = performance.now();
        w.beats.push(now - w.lastBeat);
        w.lastBeat = now;
      }, 50);
    });
    release();
    await expect(card(page, 1).getByText(/已收到回执/)).toBeVisible();
    await page.getByRole("button", { name: /展开任务与作者预算/ }).click();
    await expect(page.getByText("agent：0 秒", { exact: true })).toBeVisible();
    await expect(
      page.getByText("verifier：未知", { exact: true }),
    ).toBeVisible();
    await page.getByLabel("筛选任务名称或包名").fill("package-499");
    await expect(
      page.getByText(c.datasets[0].tasks[499].name, { exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: `${process.env.HH_EVIDENCE || info.outputDir}/large-${attempt}.png`,
      fullPage: false,
    });
    const before = Date.now();
    await page.getByRole("tab", { name: "受邀账户" }).click();
    await expect(
      page
        .locator('[data-slot="card-title"]')
        .filter({ hasText: /^test-admin$/ }),
    ).toBeVisible();
    const switchMs = Date.now() - before;
    const gaps: number[] = await page.evaluate(() => {
      const w = window as any;
      clearInterval(w.beatTimer);
      return w.beats;
    });
    const measurement = {
      attempt,
      maxHeartbeatMs: Math.max(...gaps),
      switchMs,
      beats: gaps,
      errors,
    };
    await writeFile(
      `${process.env.HH_EVIDENCE || info.outputDir}/performance-${attempt}.json`,
      JSON.stringify(measurement, null, 2),
    );
    await info.attach("responsiveness", {
      body: JSON.stringify(measurement),
      contentType: "application/json",
    });
    expect(measurement.maxHeartbeatMs).toBeLessThanOrEqual(250);
    expect(switchMs).toBeLessThanOrEqual(1000);
    expect(errors).toEqual([]);
  });

for (const theme of ["dark", "light"] as const)
  for (const width of [1440, 390])
    test(`management visual and help ${theme} ${width}`, async ({
      page,
    }, info) => {
      await page.setViewportSize({ width, height: 960 });
      await page.addInitScript(
        (t) => localStorage.setItem("harbor-helper.theme", t),
        theme,
      );
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await setup(page);
      await page.route("**/api/v1/admin/master-key", (route) =>
        route.fulfill({
          json: { generation: 3, available: true, rotated_at: 1791460000 },
        }),
      );
      expect(await page.title()).toContain("Harbor");
      expect(new URL(page.url()).pathname).toBe("/admin");
      await expect(page.locator("main")).not.toBeEmpty();
      await zone(page, "UTC");
      await expect(
        card(page, 1).getByText(/2026\/10\/8 11:46:40/),
      ).toBeVisible();
      await zone(page, "Asia/Shanghai");
      await expect(
        card(page, 1).getByText(/2026\/10\/8 19:46:40/),
      ).toBeVisible();
      await zone(page, "America/New_York");
      await expect(
        card(page, 1).getByText(/2026\/10\/8 07:46:40/),
      ).toBeVisible();
      for (const section of [
        "dataset",
        "users",
        "security",
        "limits",
      ] as const) {
        await page.goto(`/admin?section=${section}`);
        if (section === "security") {
          await expect(
            page.getByText("轮换不撤销上游 key 和已泄露的旧快照。", {
              exact: true,
            }),
          ).toBeVisible();
          await expect(
            page.getByText(
              "不擦除旧库页、WAL、日志和备份；旧主密钥文件保留。",
              { exact: true },
            ),
          ).toBeVisible();
          await page.screenshot({
            path: `${process.env.HH_EVIDENCE || info.outputDir}/security-collapsed-${theme}-${width}.png`,
            fullPage: true,
          });
          await page.getByText("展开泄露处置五步顺序", { exact: true }).click();
          const steps = await page.locator("main ol li").allTextContents();
          expect(steps).toHaveLength(5);
          expect(steps[0]).toContain("暂停新受理");
          expect(steps[4]).toContain("验证新实验");
        }
        if (section === "users") {
          const help = page.getByRole("button", {
            name: "管理员角色帮助",
            exact: true,
          });
          await help.hover();
          await expect(
            page.getByText("管理员默认拥有完整资料权限。", { exact: true }),
          ).toBeVisible();
          await page.keyboard.press("Escape");
          await help.focus();
          await expect(
            page.getByText("管理员默认拥有完整资料权限。", { exact: true }),
          ).toBeVisible();
          await page.keyboard.press("Escape");
        }
        await expect(page.locator("vite-error-overlay")).toHaveCount(0);
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= window.innerWidth,
          ),
        ).toBe(true);
        const path = `${process.env.HH_EVIDENCE || info.outputDir}/${section}-${theme}-${width}.png`;
        await page.screenshot({ path, fullPage: true });
        await info.attach(`${section}`, { path, contentType: "image/png" });
      }
      expect(errors).toEqual([]);
    });

test("role help supports touch open and close", async ({ browser }) => {
  const context = await browser.newContext({
    hasTouch: true,
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  await fixture(page);
  await page.goto("/admin?section=users");
  const help = page.getByRole("button", { name: "管理员角色帮助" });
  await help.tap();
  await expect(
    page.getByText("管理员默认拥有完整资料权限。", { exact: true }),
  ).toBeVisible();
  await help.tap();
  await expect(
    page.getByText("管理员默认拥有完整资料权限。", { exact: true }),
  ).not.toBeVisible();
  await context.close();
});

test("shutdown observations distinguish idle, execution, cleanup, audit and stale polling", async ({
  page,
}) => {
  await fixture(page);
  const status = {
    maintenance: { paused: false, reason: "", retry_at: null },
    intent: { mode: "none", phase: "idle" },
    counts: {
      preparing: 0,
      queued: 0,
      starting: 0,
      running: 0,
      cancelling: 0,
      cleanup_blocked: 0,
      audit_incomplete: 0,
    },
  };
  let fail = false;
  await page.route("**/api/v1/admin/shutdown", (route) =>
    route.fulfill(
      fail
        ? {
            status: 503,
            json: { code: "unavailable", message: "injected refresh failure" },
          }
        : { json: status },
    ),
  );
  await page.goto("/admin?section=limits");
  await expect(page.getByText("未请求停止", { exact: false })).toBeVisible();
  await expect(page.getByText(/最近观察：/)).toBeVisible();
  status.counts.running = 1;
  status.counts.cleanup_blocked = 1;
  status.counts.audit_incomplete = 1;
  await expect(page.getByText("停止尚未完成", { exact: true })).toBeVisible();
  await expect(
    page.getByText("证据审计异常单独限制相关证据展示，不占执行容量。", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.locator("dl > div").filter({ hasText: "执行中" }),
  ).toContainText("1");
  fail = true;
  await expect(page.getByText(/刷新失败，显示上次观察/)).toBeVisible();
  await expect(
    page.locator("dl > div").filter({ hasText: "执行中" }),
  ).toContainText("1");
});

import { test } from "./fixture";
import { expect } from "@playwright/test";
import { fixture } from "./fixture";

const version = {
  version: "0.2.0",
  release: "a".repeat(40),
  build: process.env.HH_QA_BUILD || "b".repeat(64),
  source: {
    repository: "https://installed.invalid/team.git",
    branch: "master",
    commit: "a".repeat(40),
  },
};
const check = {
  check_id: "c".repeat(64),
  target_sha: "d".repeat(40),
  config_digest: "e".repeat(64),
  relation: "update",
  metadata: "passed",
  message: "Synthetic target release",
};

test("administrator confirms a fixed target and installed/next sources stay distinct", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/v1/version", (route) =>
    route.fulfill({ json: version }),
  );
  const writes: unknown[] = [];
  await page.route("**/api/v1/admin/updates", async (route) => {
    if (route.request().method() === "POST") {
      writes.push(route.request().postDataJSON());
      await route.fulfill({ json: { request_id: "f".repeat(64) } });
    } else
      await route.fulfill({
        json: {
          enabled: true,
          source: {
            repository: "https://next.invalid/team.git",
            branch: "dev",
          },
          job: null,
          results: [{ request_id: check.check_id, result: check }],
        },
      });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "查看运行版本与更新" }).click();
  const dialog = page.getByRole("dialog", { name: "运行版本与更新" });
  await expect(
    dialog.getByText(/https:\/\/installed.invalid\/team.git · master/),
  ).toBeVisible();
  await expect(
    dialog.getByText(/https:\/\/next.invalid\/team.git · 测试/),
  ).toBeVisible();
  await expect(dialog.getByText(/元数据检查通过；完整适配/)).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("version-dialog.png") });
  await dialog.getByRole("button", { name: "更新到此固定提交" }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({
    action: "upgrade",
    payload: {
      check_id: check.check_id,
      target_sha: check.target_sha,
      config_digest: check.config_digest,
    },
  });
  await expect(
    dialog.getByRole("button", { name: "更新到此固定提交" }),
  ).toBeDisabled();
  await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(dialog).toHaveCount(0);
});

test("members see running identity and no administrator update controls", async ({
  page,
}) => {
  const calls = await fixture(page, "member");
  await page.route("**/api/v1/version", (route) =>
    route.fulfill({ json: { ...version, source: null } }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "查看运行版本与更新" }).click();
  await expect(page.getByText("来源未记录", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "检查更新" })).toHaveCount(0);
  expect(calls.some((call) => call.path === "/admin/updates")).toBe(false);
});

test("barrier displays reconnect notice before login without sensitive job details", async ({
  page,
}) => {
  await fixture(page, "member", false);
  await page.route("**/api/v1/setup", (route) =>
    route.fulfill({
      status: 503,
      json: { code: "upgrade_in_progress", message: "更新中" },
    }),
  );
  await page.route("**/api/v1/upgrade-phase", (route) =>
    route.fulfill({ json: { upgrading: true, phase: "backup" } }),
  );
  await page.goto("/");
  const dialog = page.getByRole("dialog", { name: "服务更新中" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "重新连接" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  await expect(dialog).not.toContainText("repository");
  await page.screenshot({
    path: test.info().outputPath("upgrade-barrier.png"),
  });
});

const configuredUpdates = {
  enabled: true,
  source: { repository: "https://next.invalid/team.git", branch: "dev" },
  job: null,
  results: [],
};

test("delayed update state stays loading and reopening fetches the actual disabled configuration", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/v1/version", (route) =>
    route.fulfill({ json: version }),
  );
  let release = () => {};
  let gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let calls = 0;
  let response: object = configuredUpdates;
  await page.route("**/api/v1/admin/updates", async (route) => {
    calls++;
    await gate;
    await route.fulfill({ json: response });
  });
  await page.goto("/");
  const footer = page.getByRole("button", { name: "查看运行版本与更新" });
  await footer.click();
  const dialog = page.getByRole("dialog", { name: "运行版本与更新" });
  await expect(dialog.getByText("正在加载更新配置与启用状态…")).toBeVisible();
  await expect.poll(() => calls).toBe(1);
  // Hold beyond one poll interval: no overlapping reads or false installation state.
  await page.waitForTimeout(2800);
  expect(calls).toBe(1);
  await expect(dialog).not.toContainText("未配置");
  await expect(dialog).not.toContainText("尚未启用");
  await expect(dialog.getByRole("button", { name: "检查更新" })).toHaveCount(0);
  await page.screenshot({
    path: test.info().outputPath("updates-loading.png"),
  });
  release();
  await expect(dialog).toContainText("https://next.invalid/team.git · 测试");
  await expect(dialog.getByRole("button", { name: "检查更新" })).toBeEnabled();
  await expect(dialog).not.toContainText("正在加载");
  await page.screenshot({ path: test.info().outputPath("updates-loaded.png") });
  await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  response = { ...configuredUpdates, enabled: false, source: null };
  await footer.click();
  await expect(dialog).toContainText("正在加载更新配置与启用状态…");
  await expect(dialog).not.toContainText("https://next.invalid");
  await expect(dialog).not.toContainText("未配置");
  release();
  await expect(dialog).toContainText("下一次更新源：未配置");
  await expect(dialog).toContainText(
    "本安装尚未启用网页更新，请由部署者完成一次性接入。",
  );
  await expect(dialog.getByRole("button", { name: "检查更新" })).toHaveCount(0);
  await page.screenshot({
    path: test.info().outputPath("updates-disabled.png"),
  });
});

test("failed update reads show an error and public progress, then recover on polling and reopening", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/v1/version", (route) =>
    route.fulfill({ json: version }),
  );
  let fail = true;
  let calls = 0;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/admin/updates", (route) => {
    calls++;
    return fail
      ? route.fulfill({
          status: 503,
          json: { message: "Synthetic update status unavailable" },
        })
      : route.fulfill({
          json: { ...configuredUpdates, job: { id: "j1", phase: "waiting" } },
        });
  });
  await page.route("**/api/v1/upgrade-phase", (route) =>
    route.fulfill({ json: { upgrading: true, phase: "preparing" } }),
  );
  await page.goto("/");
  const footer = page.getByRole("button", { name: "查看运行版本与更新" });
  await footer.click();
  const dialog = page.getByRole("dialog", { name: "运行版本与更新" });
  await expect(
    dialog.getByText("更新状态读取失败，将自动重试。"),
  ).toBeVisible();
  await expect(dialog).toContainText("准备与在线预探测。刷新页面可继续查看。");
  await expect(dialog).not.toContainText("未配置");
  await expect(dialog).not.toContainText("尚未启用");
  await expect(dialog.getByRole("button", { name: "检查更新" })).toHaveCount(0);
  await page.screenshot({
    path: test.info().outputPath("updates-error-public-progress.png"),
  });
  fail = false;
  await expect(dialog.getByText("更新状态读取失败，将自动重试。")).toHaveCount(
    0,
  );
  await expect(dialog).toContainText("https://next.invalid/team.git · 测试");
  await expect(
    dialog.getByRole("button", { name: "取消升级，保留实验" }),
  ).toBeEnabled();
  await expect(dialog).toContainText("等待实验自然结束。刷新页面可继续查看。");
  fail = true;
  await expect(
    dialog.getByText("更新状态读取失败，将自动重试。"),
  ).toBeVisible();
  await expect(dialog).not.toContainText("https://next.invalid");
  await expect(
    dialog.getByRole("button", { name: "取消升级，保留实验" }),
  ).toHaveCount(0);
  await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  const before = calls;
  await footer.click();
  await expect.poll(() => calls).toBeGreaterThan(before);
  await expect(
    dialog.getByText("更新状态读取失败，将自动重试。"),
  ).toBeVisible();
  await expect(dialog).not.toContainText("未配置");
  await expect(dialog).not.toContainText("尚未启用");
  fail = false;
  await expect(dialog).toContainText("https://next.invalid/team.git · 测试");
  await expect(
    dialog.getByRole("button", { name: "取消升级，保留实验" }),
  ).toBeEnabled();
  await expect(dialog.getByText("更新状态读取失败，将自动重试。")).toHaveCount(
    0,
  );
  expect(errors).toEqual([]);
  await page.screenshot({
    path: test.info().outputPath("updates-recovered.png"),
  });
});

test("closing an outstanding read prevents its response replacing the reopened state", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/v1/version", (route) =>
    route.fulfill({ json: version }),
  );
  let releaseOld = () => {};
  const old = new Promise<void>((resolve) => {
    releaseOld = resolve;
  });
  let calls = 0;
  await page.route("**/api/v1/admin/updates", async (route) => {
    const call = ++calls;
    if (call === 1) await old;
    await route.fulfill({
      json:
        call === 1
          ? configuredUpdates
          : { ...configuredUpdates, enabled: false, source: null },
    });
  });
  await page.goto("/");
  const footer = page.getByRole("button", { name: "查看运行版本与更新" });
  await footer.click();
  const dialog = page.getByRole("dialog", { name: "运行版本与更新" });
  await expect.poll(() => calls).toBe(1);
  await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  await footer.click();
  await expect(dialog).toContainText("下一次更新源：未配置");
  const completed = page.waitForResponse((response) =>
    response.url().endsWith("/admin/updates"),
  );
  releaseOld();
  await completed;
  await expect(dialog).toContainText("本安装尚未启用网页更新");
  await expect(dialog).not.toContainText("https://next.invalid");
  await expect(dialog.getByRole("button", { name: "检查更新" })).toHaveCount(0);
});

for (const projection of ["none", "failed", "invalid", "unknown"] as const) {
  test(`failed administrator read never reuses its cached phase when public state is ${projection}`, async ({
    page,
  }) => {
    await fixture(page);
    await page.route("**/api/v1/version", (route) =>
      route.fulfill({ json: version }),
    );
    let fail = false;
    await page.route("**/api/v1/admin/updates", (route) =>
      fail
        ? route.fulfill({
            status: 503,
            json: { message: "Synthetic admin read failed" },
          })
        : route.fulfill({
            json: { ...configuredUpdates, job: { id: "j1", phase: "waiting" } },
          }),
    );
    let publicReads = 0;
    await page.route("**/api/v1/upgrade-phase", (route) => {
      if (!fail)
        return route.fulfill({ json: { upgrading: false, phase: null } });
      publicReads++;
      return projection === "failed"
        ? route.fulfill({
            status: 503,
            json: { message: "Synthetic public read failed" },
          })
        : route.fulfill({
            json:
              projection === "none"
                ? { upgrading: false, phase: null }
                : {
                    upgrading: true,
                    phase: projection === "unknown" ? "toString" : 123,
                  },
          });
    });
    await page.goto("/");
    await page.getByRole("button", { name: "查看运行版本与更新" }).click();
    const dialog = page.getByRole("dialog", { name: "运行版本与更新" });
    await expect(dialog).toContainText(
      "等待实验自然结束。刷新页面可继续查看。",
    );
    fail = true;
    await expect(dialog).toContainText("更新状态读取失败，将自动重试。");
    await expect.poll(() => publicReads).toBeGreaterThan(0);
    await expect(dialog).not.toContainText(
      "等待实验自然结束。刷新页面可继续查看。",
    );
    await expect(dialog).not.toContainText("未配置");
    await expect(dialog).not.toContainText("尚未启用");
    await expect(
      dialog.getByRole("button", { name: "取消升级，保留实验" }),
    ).toHaveCount(0);
    await page.screenshot({
      path: test.info().outputPath(`public-${projection}-no-cached-phase.png`),
    });
  });
}

test("current phase switches between administrator, public, absent, unknown and recovered administrator state", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/v1/version", (route) =>
    route.fulfill({ json: version }),
  );
  let adminFails = false;
  let job: { id: string; phase: string } | null = {
    id: "j1",
    phase: "waiting",
  };
  let projection: "preparing" | "none" | "failed" | "waiting" = "preparing";
  await page.route("**/api/v1/admin/updates", (route) =>
    adminFails
      ? route.fulfill({
          status: 503,
          json: { message: "Synthetic admin read failed" },
        })
      : route.fulfill({ json: { ...configuredUpdates, job } }),
  );
  await page.route("**/api/v1/upgrade-phase", (route) =>
    !adminFails || projection === "none"
      ? route.fulfill({ json: { upgrading: false, phase: null } })
      : projection === "failed"
        ? route.fulfill({
            status: 503,
            json: { message: "Synthetic public read failed" },
          })
        : route.fulfill({ json: { upgrading: true, phase: projection } }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "查看运行版本与更新" }).click();
  const dialog = page.getByRole("dialog", { name: "运行版本与更新" });
  await expect(dialog).toContainText("等待实验自然结束。刷新页面可继续查看。");
  adminFails = true;
  await expect(dialog).toContainText("准备与在线预探测。刷新页面可继续查看。");
  await expect(dialog).not.toContainText(
    "等待实验自然结束。刷新页面可继续查看。",
  );
  projection = "none";
  await expect(dialog).not.toContainText(
    "准备与在线预探测。刷新页面可继续查看。",
  );
  projection = "waiting";
  await expect(dialog).toContainText("等待实验自然结束。刷新页面可继续查看。");
  projection = "failed";
  await expect(dialog).not.toContainText(
    "等待实验自然结束。刷新页面可继续查看。",
  );
  await expect(dialog).toContainText("更新状态读取失败，将自动重试。");
  projection = "preparing";
  await expect(dialog).toContainText("准备与在线预探测。刷新页面可继续查看。");
  job = null;
  adminFails = false;
  await expect(dialog.getByRole("button", { name: "检查更新" })).toBeEnabled();
  await expect(dialog).not.toContainText(
    "准备与在线预探测。刷新页面可继续查看。",
  );
  await expect(dialog).not.toContainText(
    "等待实验自然结束。刷新页面可继续查看。",
  );
  adminFails = true;
  await expect(dialog).toContainText("准备与在线预探测。刷新页面可继续查看。");
  job = { id: "j2", phase: "succeeded" };
  adminFails = false;
  await expect(dialog).toContainText("升级成功。刷新页面可继续查看。");
  await expect(dialog).not.toContainText(
    "准备与在线预探测。刷新页面可继续查看。",
  );
  await expect(dialog.getByRole("button", { name: "检查更新" })).toBeEnabled();
  await page.screenshot({
    path: test.info().outputPath("administrator-new-phase.png"),
  });
});

test("a late public projection cannot replace the reopened administrator phase", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/v1/version", (route) =>
    route.fulfill({ json: version }),
  );
  let adminFails = true;
  await page.route("**/api/v1/admin/updates", (route) =>
    adminFails
      ? route.fulfill({
          status: 503,
          json: { message: "Synthetic admin read failed" },
        })
      : route.fulfill({
          json: { ...configuredUpdates, job: { id: "j2", phase: "cancelled" } },
        }),
  );
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let publicReads = 0;
  await page.route("**/api/v1/upgrade-phase", async (route) => {
    publicReads++;
    await gate;
    await route.fulfill({ json: { upgrading: true, phase: "preparing" } });
  });
  await page.goto("/");
  const footer = page.getByRole("button", { name: "查看运行版本与更新" });
  await footer.click();
  const dialog = page.getByRole("dialog", { name: "运行版本与更新" });
  await expect(dialog).toContainText("更新状态读取失败，将自动重试。");
  await expect.poll(() => publicReads).toBeGreaterThanOrEqual(2);
  await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  adminFails = false;
  await footer.click();
  await expect(dialog).toContainText("已取消升级。刷新页面可继续查看。");
  const response = page.waitForResponse((r) =>
    r.url().endsWith("/upgrade-phase"),
  );
  release();
  await response;
  await expect(dialog).toContainText("已取消升级。刷新页面可继续查看。");
  await expect(dialog).not.toContainText(
    "准备与在线预探测。刷新页面可继续查看。",
  );
  await expect(dialog.getByRole("button", { name: "检查更新" })).toBeEnabled();
});

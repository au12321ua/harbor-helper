import { test, expect } from "@playwright/test";
import { fixture } from "./fixture";

const version = {
  version: "0.2.0",
  release: "a".repeat(40),
  build: "b".repeat(64),
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

import { test, fixture, catalog, user, run } from "../../support/fixture";
import { expect } from "@playwright/test";
test("shared attachment versions, maintenance, explicit selection and write recovery", async ({
  page,
}) => {
  const calls = await fixture(page, "member");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (e) => {
    if (e.type() === "error") errors.push(e.text());
  });
  const attachments = [
    {
      id: "att-shared",
      name: "Shared SDK",
      description: "For the team",
      creator_id: "someone-else",
      creator: "alice",
      created: 1791460000,
      enabled: true,
      versions: [
        {
          id: "av-v2",
          bundle_id: "bundle-v2",
          number: 2,
          digest: "sha256:v2",
          publisher: "alice",
          created: 1791460000,
          notes: "Updated",
          enabled: true,
          availability: "available",
        },
        {
          id: "av-v1",
          bundle_id: "bundle-v1",
          number: 1,
          digest: "sha256:v1",
          publisher: "alice",
          created: 1791450000,
          notes: "Stable",
          enabled: true,
          availability: "available",
        },
      ],
    },
  ];
  const result = {
    attachment: attachments[0],
    version: attachments[0].versions[1],
  };
  await page.route("**/api/v1/attachments", async (route) => {
    await route.fulfill({
      json: route.request().method() === "POST" ? result : { attachments },
    });
  });
  await page.route("**/api/v1/catalog", (route) =>
    route.fulfill({ json: { ...catalog, attachments } }),
  );
  await page.route("**/api/v1/attachment-operations/**", (route) =>
    route.fulfill({ json: result }),
  );
  await page.goto("/attachments");
  await expect(page.getByRole("heading", { name: "团队附件" })).toBeVisible();
  await expect(page.getByRole("button", { name: "停用附件" })).toHaveCount(0);
  await page.locator("details").filter({hasText:"sha256:v1"}).getByText("版本标识与摘要", {exact:true}).click();
  await expect(page.getByText("sha256:v1", { exact: false })).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("attachments-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "使用 v1 新建实验" }).click();
  await expect(page.getByLabel("团队附件版本（可选）")).toHaveValue("av-v1");
  await page.getByRole("button", { name: "清除附件，使用无附件基线" }).click();
  await expect(page.getByLabel("团队附件版本（可选）")).toHaveValue("");
  await expect(
    page.getByText("当前选择：无附件", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("团队附件版本（可选）").selectOption("av-v1");
  await page.getByLabel("模型方案", { exact: true }).selectOption("plan1");
  await page.getByRole("button", { name: "提交实验", exact: true }).click();
  await expect(page).toHaveURL(/submissions/);
  const accepted = calls.find((c) => c.path === "/submissions");
  expect(accepted?.body.attachment_version_id).toBe("av-v1");
  expect(accepted?.body).not.toHaveProperty("bundle_id");
  await page.goto("/attachments");
  await page.getByLabel("显示名称").fill("My shared input");
  await page.getByLabel("附件 ZIP",{exact:true}).setInputFiles({
    name: "input.zip",
    mimeType: "application/zip",
    buffer: Buffer.from("fixture"),
  });
  await page.getByRole("button", { name: "提交附件操作" }).click();
  await expect(page.getByRole("status")).toContainText("av-v1");
  await page.reload();
  await page.getByRole("button", { name: "查回上次写入" }).click();
  await expect(page.getByRole("status")).toContainText("av-v1");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: test.info().outputPath("attachments-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  expect(errors).toEqual([]);
});

test("attachment creator can disable and restore a version", async ({
  page,
}) => {
  await fixture(page);
  let enabled = true;
  await page.route("**/api/v1/attachments", (route) =>
    route.fulfill({
      json: {
        attachments: [
          {
            id: "att-own",
            name: "Own",
            creator_id: user.id,
            creator: user.username,
            enabled: true,
            versions: [
              {
                id: "av-own",
                number: 1,
                enabled,
                availability: "available",
                digest: "sha256:fixed",
                publisher: user.username,
              },
            ],
          },
        ],
      },
    }),
  );
  await page.route(
    "**/api/v1/attachments/att-own/versions/av-own",
    async (route) => {
      expect(route.request().method()).toBe("PATCH");
      enabled = route.request().postDataJSON().enabled;
      await route.fulfill({ json: { updated: true } });
    },
  );
  await page.goto("/attachments");
  await page.getByRole("button", { name: "停用版本", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "恢复版本", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "使用 v1 新建实验" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "恢复版本", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "使用 v1 新建实验" }),
  ).toBeVisible();
});

test("comparison displays baseline without attachment and fixed candidate version", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/v1/compare", (route) =>
    route.fulfill({
      json: {
        comparable: true,
        reasons: [],
        tasks: [],
        mean_task_delta: { reward: 0.25 },
        bundle_change: { left: null, right: "sha256:candidate" },
        attachment_inputs: {
          left: { kind: "none", digest: null },
          right: {
            kind: "versioned",
            attachment_version_id: "av-candidate-v1",
            digest: "sha256:candidate",
          },
        },
      },
    }),
  );
  await page.route("**/api/v1/runs", (route) =>
    route.fulfill({
      json: {
        runs: [run, { ...run, id: "hh-candidate", name: "candidate" }],
        submissions: [],
      },
    }),
  );
  await page.goto("/compare");
  await page.getByLabel("实验 A", {exact:true}).selectOption("hh-test-zero");
  await page.getByLabel("实验 B", {exact:true}).selectOption("hh-candidate");
  await page.getByRole("button", { name: "开始对比" }).click();
  await expect(
    page.getByRole("row").filter({
      has: page.getByRole("cell", { name: "附件版本", exact: true }),
    }),
  ).toContainText("无附件");
  await expect(
    page.getByRole("row").filter({
      has: page.getByRole("cell", { name: "附件版本", exact: true }),
    }),
  ).toContainText("av-candidate-v1");
  await expect(
    page.getByRole("row").filter({
      has: page.getByRole("cell", { name: "附件摘要", exact: true }),
    }),
  ).toContainText("sha256:candidate");
});

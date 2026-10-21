import { test, fixture, catalog } from "../../support/fixture";
import { expect } from "@playwright/test";
test("Hub status survives reload and distinguishes storage from access validation", async ({
  page,
}) => {
  await fixture(page);
  const current: any = structuredClone(catalog);
  current.hub = {
    state: "unset",
    mode: "anonymous",
    version: null,
    updated_at: null,
  };
  await page.route("**/api/v1/catalog", (route) =>
    route.fulfill({ json: current }),
  );
  await page.route("**/api/v1/admin/hub", async (route) => {
    current.hub = {
      state: "active",
      mode: "team",
      version: (current.hub.version || 0) + 1,
      updated_at: 1791518000,
    };
    await route.fulfill({ json: current.hub });
  });
  await page.route("**/api/v1/admin/hub/disable", async (route) => {
    current.hub = { ...current.hub, state: "disabled", mode: "anonymous" };
    await route.fulfill({ json: current.hub });
  });
  await page.goto("/admin");
  await expect(page.getByText("凭据：未设置", { exact: true })).toBeVisible();
  const form = page
    .locator("form")
    .filter({ has: page.getByLabel("Hub PAT", { exact: true }) });
  for (let version = 1; version <= 2; version++) {
    await form.getByLabel("Hub PAT", { exact: true }).fill("fake-hub-ui-pat");
    await form.getByRole("button", { name: "保存", exact: true }).click();
    await expect(
      page.getByText("凭据：已设置（启用）", { exact: true }),
    ).toBeVisible();
    await expect(form.getByLabel("Hub PAT", { exact: true })).toHaveValue("");
    await expect(page.getByText(new RegExp(`版本：v${version}`))).toBeVisible();
    await page.reload();
    await expect(
      page.getByText("凭据：已设置（启用）", { exact: true }),
    ).toBeVisible();
  }
  await page.getByRole("button", {name:"Hub 凭据状态帮助"}).click();
  await expect(
    page.getByText(
      "保存仅代表加密持久化，未验证Hub身份或数据集访问权限。访问验证结果请查看数据集条目的验证状态。",
      { exact: true },
    ),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "停用 Hub 凭据，改为匿名来源" })
    .click();
  await expect(page.getByText("凭据：已停用", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("凭据：已停用", { exact: true })).toBeVisible();
});

test("Docker inventory is read-only and source needs no runtime", async ({
  page,
}) => {
  const calls = await fixture(page);
  await page.route("**/api/v1/admin/docker", (route) =>
    route.fulfill({
      json: {
        state: "ready",
        checked_at: 1791518000,
        message: "Docker daemon 可达",
        images: [{ reference: "python:local" }],
        truncated: false,
      },
    }),
  );
  await page.goto("/admin");
  await page.getByRole("tab", { name: "Docker 诊断", exact: true }).click();
  await page
    .getByRole("button", { name: "发现本机 Docker 与镜像", exact: true })
    .click();
  await expect(
    page.getByText("Docker daemon 可达", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("python:local", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Docker 镜像引用", { exact: true })).toHaveCount(
    0,
  );
  await expect(page.getByLabel("任务镜像约定", { exact: true })).toHaveCount(0);
  await page.getByRole("tab", { name: "数据集", exact: true }).click();
  await expect(page.getByLabel("运行环境", { exact: true })).toHaveCount(0);
  expect(
    calls.filter((c) => c.path === "/admin/catalog/runtime" && c.body),
  ).toHaveLength(0);
  await page.getByRole("tab", { name: "Docker 诊断", exact: true }).click();
  await page.route("**/api/v1/admin/docker", (route) =>
    route.fulfill({
      json: {
        state: "permission_denied",
        checked_at: 1791518001,
        message: "服务账户没有daemon访问权限",
        images: [],
        truncated: false,
      },
    }),
  );
  await page
    .getByRole("button", { name: "发现本机 Docker 与镜像", exact: true })
    .click();
  await expect(
    page.getByText("服务账户没有daemon访问权限", { exact: true }),
  ).toBeVisible();
});

test("dynamic author fields save without resetting source verification", async ({
  page,
}) => {
  await fixture(page);
  const custom: any = structuredClone(catalog);
  const dataset = custom.datasets[0];
  dataset.status = "verified";
  dataset.author_parameters = {
    version: 1,
    status: "missing",
    values: {},
    source: "generic/task@sha256:fixed",
    discovery: {
      variables: {
        BUILD_IMAGE: [
          {
            task: "generic/task",
            file: "environment/docker-compose.yaml",
            required: true,
            default: "",
          },
        ],
      },
      budgets: [
        { task: "generic/task", agent_seconds: 25, verifier_seconds: 10 },
      ],
    },
    issues: [],
  };
  await page.route("**/api/v1/catalog", (route) =>
    route.fulfill({ json: custom }),
  );
  let saved: any;
  await page.route(
    "**/api/v1/admin/datasets/dataset1/author-inputs",
    async (route) => {
      saved = route.request().postDataJSON();
      dataset.author_parameters = {
        ...dataset.author_parameters,
        version: 2,
        status: "checked",
        values: saved.values,
      };
      await route.fulfill({ json: dataset.author_parameters });
    },
  );
  await page.goto("/admin");
  await page.getByRole("tab", { name: "数据集", exact: true }).click();
  await expect(page.getByText("来源已验证", { exact: false })).toBeVisible();
  await page
    .getByLabel("BUILD_IMAGE", { exact: true })
    .fill("generic/runtime:1");
  const form = page
    .locator("form")
    .filter({ has: page.getByLabel("BUILD_IMAGE", { exact: true }) });
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByText(/运行参数已检查/)).toBeVisible();
  expect(saved).toEqual({ values: { BUILD_IMAGE: "generic/runtime:1" } });
  await expect(page.getByText("来源已验证", { exact: false })).toBeVisible();
  await expect(
    page.getByLabel("CAD_BENCH_AGENT_IMAGE", { exact: true }),
  ).toHaveCount(0);
});

test("administrator checks exact selected tasks and exposes partial scope", async ({
  page,
}) => {
  await fixture(page);
  const custom: any = structuredClone(catalog);
  let body: any;
  await page.route("**/api/v1/catalog", (route) =>
    route.fulfill({ json: custom }),
  );
  await page.route(
    "**/api/v1/admin/datasets/dataset1/author-inputs/check",
    async (route) => {
      body = route.request().postDataJSON();
      custom.datasets[0].author_parameters = {
        status: "partial_checked",
        values: {},
        discovery: { variables: {}, budgets: [] },
        scope: {
          complete: false,
          tasks: [{ name: "answer", ref: "fixed" }],
          total: 225,
          unknown: 224,
        },
      };
      await route.fulfill({ json: custom.datasets[0].author_parameters });
    },
  );
  await page.goto("/admin");
  await page.getByRole("tab", { name: "数据集", exact: true }).click();
  await page.getByRole("button", { name: /展开任务与作者预算/ }).click();
  await page.getByRole("checkbox", { name: "选择任务 answer", exact: true }).check();
  await page.getByRole("button", { name: "检查选定任务", exact: true }).click();
  await expect(page.getByText(/不代表全集就绪/)).toBeVisible();
  expect(body).toEqual({ task_names: ["answer"] });
  await expect(page.getByText(/另有 224 个任务未扫描/)).toBeVisible();
});

test("administrator can check more than fifty legitimate task names", async ({
  page,
}) => {
  await fixture(page);
  const custom: any = structuredClone(catalog);
  const names = Array.from(
    { length: 52 },
    (_, i) => `task-${String(i).padStart(2, "0")}`,
  );
  custom.datasets[0].tasks = names.map((name) => ({
    name,
    package: `test/${name}`,
    ref: `sha256:${name}`,
  }));
  let submitted: any;
  await page.route("**/api/v1/catalog", (route) =>
    route.fulfill({ json: custom }),
  );
  await page.route(
    "**/api/v1/admin/datasets/dataset1/author-inputs/check",
    async (route) => {
      submitted = route.request().postDataJSON();
      await route.fulfill({ json: {} });
    },
  );
  await page.goto("/admin");
  await page.getByRole("tab", { name: "数据集", exact: true }).click();
  await page.getByRole("button", { name: /展开任务与作者预算/ }).click();
  await page.getByRole("button", { name: "再显示 20 个" }).click();
  await page.getByRole("button", { name: "再显示 20 个" }).click();
  for (const name of names.slice(0, 51)) {
    await page.getByRole("checkbox", { name: `选择任务 ${name}`, exact: true }).check();
  }
  const button = page.getByRole("button", {
    name: "检查选定任务",
    exact: true,
  });
  await expect(button).toBeEnabled();
  await button.click();
  await expect
    .poll(() => submitted)
    .toEqual({ task_names: names.slice(0, 51) });
});

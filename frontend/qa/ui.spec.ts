import { test } from "./fixture";
import { expect, type Page } from "@playwright/test";
import { fixture, catalog, user, run } from "./fixture";
// Hold the refresh until assertions finish, rather than racing an arbitrary timeout.
async function holdCatalogRefresh(page: Page) {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    "**/api/v1/catalog",
    async (route) => {
      await gate;
      await route.fallback();
    },
    { times: 1 },
  );
  return release;
}
async function expectEditorsLocked(page: Page) {
  await expect(
    page.getByRole("status").filter({ hasText: "正在保存并刷新配置" }),
  ).toBeVisible();
  await expect(
    page.locator("input:enabled, textarea:enabled, select:enabled"),
  ).toHaveCount(0);
  await expect(
    page.getByRole("tab", { name: "模型与 key", exact: true }),
  ).toBeDisabled();
}
test("model edits show current saved values and repeated save preserves them", async ({
  page,
}) => {
  const calls = await fixture(page);
  // Seed the existing version using the same stateful API fixture as the UI.
  await page.goto("/admin");
  await page.evaluate(async () => {
    await fetch("/api/v1/admin/model-profiles", {
      method: "POST",
      body: JSON.stringify({
        id: "plan1",
        name: "测试方案",
        model: "test-model",
        provider_id: "p1",
        credential_id: "c1",
        enabled: true,
        params: { temperature: 0.5, max_tokens: 100, top_p: 0.8 },
        opencode_version: "1.18.35",
      }),
    });
  });
  await page.reload();
  await page.getByRole("tab", { name: "模型与 key", exact: true }).click();
  await page.getByRole("button", { name: "编辑方案", exact: true }).click();
  const form = page
    .locator("form")
    .filter({ has: page.getByLabel("方案名称", { exact: true }) });
  await expect(page.getByLabel("Temperature（可选）")).toHaveValue("0.5");
  await page.getByLabel("方案名称", { exact: true }).fill("更新方案");
  await page.getByLabel("Temperature（可选）").fill("0");
  await page.getByLabel("最大输出 tokens（可选）").fill("200");
  await page
    .getByLabel("高级参数 JSON")
    .fill('{"temperature":0.5,"max_tokens":100,"top_p":0.9}');
  const releaseRefresh = await holdCatalogRefresh(page);
  const mutation = page.waitForResponse(
    (r) =>
      r.url().endsWith("/admin/model-profiles") &&
      r.request().method() === "POST",
  );
  await form.getByRole("button", { name: "保存", exact: true }).click();
  expect((await mutation).ok()).toBe(true);
  await expectEditorsLocked(page);
  await expect(page.locator("#model-provider")).toBeDisabled();
  await expect(form.getByLabel("方案名称")).toBeDisabled();
  releaseRefresh();
  await expect(form.getByLabel("方案名称")).toBeEnabled();
  await expect(page.locator("#model-provider")).toBeEnabled();
  await expect(page.getByText("配置已保存", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Temperature（可选）")).toHaveValue("0");
  await expect(page.getByLabel("方案名称", { exact: true })).toHaveValue(
    "更新方案",
  );
  await expect(page.getByLabel("最大输出 tokens（可选）")).toHaveValue("200");
  await expect(page.getByLabel("高级参数 JSON")).toHaveValue(
    '{"temperature":0,"max_tokens":200,"top_p":0.9}',
  );
  await expect(page.getByLabel("团队 key", { exact: true })).toHaveValue("c1");
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect
    .poll(
      () =>
        calls.filter((c) => c.path === "/admin/model-profiles" && c.body)
          .length,
    )
    .toBe(3);
  const writes = calls
    .filter((c) => c.path === "/admin/model-profiles" && c.body)
    .slice(1);
  expect(writes.map((c) => c.body)).toEqual(
    Array(2).fill({
      id: "plan1",
      name: "更新方案",
      provider_id: "p1",
      credential_id: "c1",
      model: "test-model",
      params: { temperature: 0, max_tokens: 200, top_p: 0.9 },
      opencode_version: "1.18.35",
      enabled: true,
    }),
  );
  await expect(page.getByLabel("Temperature（可选）")).toHaveValue("0");
  // Reload and reopen to check the fixture's persisted catalog, not just the DOM.
  await page.reload();
  await page.getByRole("tab", { name: "模型与 key", exact: true }).click();
  await page.getByRole("button", { name: "编辑方案", exact: true }).click();
  await expect(page.getByLabel("Temperature（可选）")).toHaveValue("0");
  await expect(page.getByLabel("高级参数 JSON")).toHaveValue(
    '{"temperature":0,"max_tokens":200,"top_p":0.9}',
  );
  // The persisted reload above completes the successful save before correction input.
  await form.getByLabel("方案名称").fill("待修正输入");
  await form.getByLabel("Temperature（可选）").fill("0.2");
  await form.getByLabel("高级参数 JSON").fill("{invalid");
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect(form.getByText("操作未完成", { exact: true })).toBeVisible();
  await expect(form.getByLabel("方案名称")).toHaveValue("待修正输入");
  await expect(form.getByLabel("Temperature（可选）")).toHaveValue("0.2");
  await expect(form.getByLabel("高级参数 JSON")).toHaveValue("{invalid");
  expect(
    calls.filter((c) => c.path === "/admin/model-profiles" && c.body),
  ).toHaveLength(3);
  // Server rejection also retains correction input after a valid JSON submission.
  await page.route("**/api/v1/admin/model-profiles", (route) =>
    route.fulfill({ status: 400, json: { detail: "测试拒绝保存" } }),
  );
  await form.getByLabel("高级参数 JSON").fill('{"top_p":0.7}');
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect(form.getByText("操作未完成", { exact: true })).toBeVisible();
  await expect(form.getByLabel("方案名称")).toHaveValue("待修正输入");
  await expect(form.getByLabel("Temperature（可选）")).toHaveValue("0.2");
  await expect(form.getByLabel("高级参数 JSON")).toHaveValue('{"top_p":0.7}');
});
test("shared list, actual zero report, literal safe logs and screenshot", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "共享实验", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "hh-test-zero", exact: true }).click();
  await page.getByRole("tab", { name: "评分报告" }).click();
  await expect(page.getByText("reward:")).toHaveText("reward: 0");
  await expect(page.getByText("缺失评分", { exact: true })).toHaveCount(0);
  await page.getByRole("tab", { name: "运行日志" }).click();
  await expect(page.locator(".log-view")).toContainText(
    "[bold]literal markup[/bold]",
  );
  expect(await page.evaluate(() => "bad" in window)).toBe(false);
  await page.goto("/");
  await page.screenshot({
    path: test.info().outputPath("harbor-helper-web-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: test.info().outputPath("harbor-helper-web-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
test("invited login and dataset/profile submission use same-origin mutation header", async ({
  page,
}) => {
  const calls = await fixture(page, "admin", false);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "登录团队实验室" }),
  ).toBeVisible();
  await page.getByLabel("账户", { exact: true }).fill("test-admin");
  await page.getByLabel("密码", { exact: true }).fill("test-password-only");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("link", { name: "新建实验" }).first().click();
  await page.getByLabel("数据集", { exact: true }).selectOption("dataset1");
  await page.getByLabel("任务", { exact: true }).selectOption("answer");
  await page.getByLabel("模型方案", { exact: true }).selectOption("plan1");
  await page.getByRole("button", { name: "提交实验" }).click();
  await expect(
    page.getByRole("heading", { name: "实验准备", exact: true }),
  ).toBeVisible();
  const submitted = calls.find((c) => c.path === "/submissions" && c.body);
  expect(submitted?.body.dataset_id).toBe("dataset1");
  expect(submitted?.body.task).toBe("answer");
  expect(submitted?.headers["idempotency-key"]).toEqual(expect.stringMatching(/\S/));
  expect(submitted?.headers["x-requested-with"]).toBe("harbor-helper");
  expect(submitted?.body).not.toHaveProperty("key");
});
test("members share other runs but cannot cancel them or see admin navigation", async ({
  page,
}) => {
  await fixture(page, "member");
  await page.goto("/runs/hh-other-running");
  await expect(
    page.getByRole("heading", { name: "hh-other-running", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "取消实验" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "团队管理" })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "按原条件重跑" }),
  ).toBeVisible();
});
test("admin key write clears input and does not use browser storage", async ({
  page,
}) => {
  const calls = await fixture(page);
  await page.goto("/admin");
  await page.getByRole("tab", { name: "模型与 key", exact: true }).click();
  await page.getByLabel("Key 名称").fill("新的测试凭据");
  await page
    .locator("form")
    .filter({ has: page.getByLabel("Key 名称") })
    .getByLabel("提供商", { exact: true })
    .selectOption("p1");
  await page.getByLabel("密钥", { exact: true }).fill("fake-key-browser-test");
  await page
    .locator("form")
    .filter({ has: page.getByLabel("Key 名称") })
    .getByRole("button", { name: "保存", exact: true })
    .click();
  await expect(page.getByLabel("密钥", { exact: true })).toHaveValue("");
  expect(calls.find((c) => c.path === "/admin/credentials")?.body.key).toBe(
    "fake-key-browser-test",
  );
  expect(
    await page.evaluate(() =>
      JSON.stringify({ ...localStorage, ...sessionStorage }),
    ),
  ).not.toContain("fake-key-browser-test");
});

test("protected setup and failed preparation offer actionable new submission", async ({
  page,
}) => {
  const calls = await fixture(page);
  let initialized = false;
  await page.route("**/api/v1/setup", async (route) => {
    if (route.request().method() === "POST") {
      initialized = true;
      await route.fulfill({ json: { initialized: true } });
    } else await route.fulfill({ json: { initialized } });
  });
  await page.goto("/");
  await page
    .getByLabel("部署引导凭证")
    .fill("fake-protected-bootstrap-material");
  await page.getByLabel("首管理员用户名").fill("admin");
  await page
    .getByLabel("管理员密码（至少12位）")
    .fill("fake-bootstrap-password");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "登录团队实验室" }),
  ).toBeVisible();
  await page.reload();
  await page.route("**/api/v1/submissions/sub-failed", (route) =>
    route.fulfill({
      json: {
        id: "sub-failed",
        submitter: "test-admin",
        status: "failed",
        error: "source_access: 检查团队来源凭据",
        request: {
          name: "失败示例",
          dataset_id: "dataset1",
          task: "answer",
          agent: "oracle",
        },
      },
    }),
  );
  await page.goto("/submissions/sub-failed");
  await expect(
    page.getByText(
      "本次准备已停止。修复配置或修改输入后重新提交，会创建新的实验。",
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "修改输入后新提交" }).click();
  await expect(page.getByLabel("实验名称（可选）")).toHaveValue("失败示例");
  await expect(page.getByLabel("任务", { exact: true })).toHaveValue("answer");
  await expect(page.getByLabel("执行方案", { exact: true })).toHaveValue(
    "oracle",
  );
  // Public request lacks numeric intent: explicitly confirm unknown values.
  await expect(page.getByRole("button", { name: "提交实验", exact: true })).toBeDisabled();
  await page.getByLabel("每任务尝试次数").fill("1");
  await page.getByLabel("实验并发数").fill("1");
  await page.getByLabel("实验总时长上限（秒，含准备）").fill("600");
  await page.getByLabel("环境启动等待倍数", { exact: true }).fill("10");
  await page.getByRole("button", { name: "提交实验", exact: true }).click();
  const submission = calls.find((c) => c.path === "/submissions" && c.body);
  expect(submission?.body.name).toBe("失败示例");
  expect(submission?.body.dataset_id).toBe("dataset1");
});

for (const kind of ["provider", "dataset"] as const) {
  test(`${kind} editor loads saved values and repeats identity`, async ({
    page,
  }) => {
    await fixture(page);
    const current: any = structuredClone(catalog);
    current.datasets[0] = {
      ...current.datasets[0],
      name: "数据集旧名",
      enabled: true,
      status: "unverified",
    };
    const spec = {
      provider: {
        tab: "模型与 key",
        button: "编辑提供商",
        label: "API 端点",
        value: "https://changed.invalid/v1",
        path: "/admin/providers",
        list: "providers",
        id: "p1",
      },
      dataset: {
        tab: "数据集",
        button: "编辑",
        label: "Hub 来源（owner/name，可指定版本）",
        value: "team/changed@2",
        path: "/admin/catalog/dataset",
        list: "datasets",
        id: "dataset1",
      },
    }[kind];
    const saves: any[] = [];
    await page.route("**/api/v1/catalog", (route) =>
      route.fulfill({ json: current }),
    );
    await page.route(`**/api/v1${spec.path}`, async (route) => {
      const v = route.request().postDataJSON();
      saves.push(v);
      const saved = {
        ...v,
        version: saves.length + 1,
        status: "unverified",
      };
      current[spec.list][0] = { ...current[spec.list][0], ...saved };
      await route.fulfill({ json: saved });
    });
    await page.goto("/admin");
    await page.getByRole("tab", { name: spec.tab, exact: true }).click();
    await page.getByRole("button", { name: spec.button, exact: true }).click();
    const input = page.getByLabel(spec.label, { exact: true });
    await input.fill(spec.value);
    const form = page.locator("form").filter({ has: input });
    const releaseRefresh = await holdCatalogRefresh(page);
    const mutation = page.waitForResponse(
      (r) => r.url().endsWith(spec.path) && r.request().method() === "POST",
    );
    await form.getByRole("button", { name: "保存", exact: true }).click();
    expect((await mutation).ok()).toBe(true);
    await expectEditorsLocked(page);
    await expect(input).toBeDisabled();
    releaseRefresh();
    await expect(input).toBeEnabled();
    await expect(input).toHaveValue(spec.value);
    await form.getByRole("button", { name: "保存", exact: true }).click();
    await expect.poll(() => saves.length).toBe(2);
    expect(saves.map((v) => v.id)).toEqual([spec.id, spec.id]);
    expect(
      saves.map((v) => (kind === "provider" ? v.endpoint : v.reference)),
    ).toEqual([spec.value, spec.value]);
  });
}
test("failed credential save retains nonsecret inputs and clears secret", async ({
  page,
}) => {
  await fixture(page);
  let releaseFailure!: () => void;
  const gate = new Promise<void>((resolve) => {
    releaseFailure = resolve;
  });
  await page.route("**/api/v1/admin/credentials", async (route) => {
    await gate;
    await route.fulfill({
      status: 422,
      json: { code: "credential_binding", message: "请修正提供商配置" },
    });
  });
  await page.goto("/admin");
  await page.getByRole("tab", { name: "模型与 key", exact: true }).click();
  const form = page
    .locator("form")
    .filter({ has: page.getByLabel("Key 名称") });
  await form.getByLabel("Key 名称").fill("待修正key名称");
  await form.getByLabel("提供商", { exact: true }).selectOption("p1");
  await form.getByLabel("密钥", { exact: true }).fill("fake-failed-save-key");
  const request = page.waitForRequest(
    (r) => r.url().endsWith("/admin/credentials") && r.method() === "POST",
  );
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await request;
  await expectEditorsLocked(page);
  await expect(form.getByLabel("密钥", { exact: true })).toBeDisabled();
  releaseFailure();
  await expect(form.getByLabel("Key 名称")).toBeEnabled();
  await expect(form.getByText("操作未完成", { exact: true })).toBeVisible();
  await expect(form.getByLabel("Key 名称")).toHaveValue("待修正key名称");
  await expect(form.getByLabel("提供商", { exact: true })).toHaveValue("p1");
  await expect(form.getByLabel("密钥", { exact: true })).toHaveValue("");
});

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

test("explicit new provider creates another object and editing preserves its peers", async ({
  page,
}) => {
  await fixture(page);
  const current: any = structuredClone(catalog);
  current.providers = [];
  const writes: any[] = [];
  await page.route("**/api/v1/catalog", (route) =>
    route.fulfill({ json: current }),
  );
  await page.route("**/api/v1/admin/providers", async (route) => {
    const v = route.request().postDataJSON();
    writes.push(v);
    const index = current.providers.findIndex((p: any) => p.id === v.id);
    const saved = {
      ...v,
      id: v.id || `provider${current.providers.length + 1}`,
      version: index < 0 ? 1 : current.providers[index].version + 1,
    };
    if (index < 0) current.providers.push(saved);
    else current.providers[index] = saved;
    await route.fulfill({ json: saved });
  });
  await page.goto("/admin");
  await page.getByRole("tab", { name: "模型与 key", exact: true }).click();
  const form = page
    .locator("form")
    .filter({ has: page.getByLabel("提供商名称", { exact: true }) });
  for (const name of ["A", "B"]) {
    await page.getByRole("button", { name: "新建提供商", exact: true }).click();
    await expect(page.getByLabel("提供商名称", { exact: true })).toHaveValue(
      "",
    );
    await page.getByLabel("提供商名称", { exact: true }).fill(name);
    await page
      .getByLabel("API 端点", { exact: true })
      .fill(`https://${name.toLowerCase()}.invalid/v1`);
    await form.getByRole("button", { name: "保存", exact: true }).click();
    await expect(
      page.getByText(`正在编辑：${name}`, { exact: false }),
    ).toBeVisible();
  }
  expect(current.providers).toHaveLength(2);
  expect(writes.map((v) => v.id)).toEqual([undefined, undefined]);
  await page
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: "A", exact: true }) })
    .getByRole("button", { name: "编辑提供商", exact: true })
    .click();
  await page
    .getByLabel("API 端点", { exact: true })
    .fill("https://a-edited.invalid/v1");
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect.poll(() => writes.length).toBe(3);
  expect(writes[2].id).toBe("provider1");
  expect(current.providers[1].name).toBe("B");
  expect(current.providers[1].endpoint).toBe("https://b.invalid/v1");
});

test("list scope is separate from model binding and exposes empty state", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/admin");
  await page.getByRole("tab", { name: "模型与 key", exact: true }).click();
  await expect(
    page.getByText(
      "列表范围只缩小配置列表，不修改新建或编辑表单的提供商与团队 key 绑定。",
      { exact: true },
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "编辑方案", exact: true }).click();
  const form = page
    .locator("form")
    .filter({ has: page.getByLabel("方案名称", { exact: true }) });
  await form.getByLabel("Temperature（可选）").fill("0");
  await page.getByLabel("列表范围：提供商", { exact: true }).selectOption("p1");
  await page
    .getByLabel("列表范围：团队 key", { exact: true })
    .selectOption("c1");
  await expect(form.getByLabel("Temperature（可选）")).toHaveValue("0");
  await expect(page.getByLabel("团队 key", { exact: true })).toHaveValue("c1");
  await page.getByRole("button", { name: "显示全部配置", exact: true }).click();
  await expect(
    page.getByLabel("列表范围：提供商", { exact: true }),
  ).toHaveValue("");
  await expect(form.getByLabel("Temperature（可选）")).toHaveValue("0");
  await page.route("**/api/v1/catalog", (route) =>
    route.fulfill({
      json: { ...catalog, credentials: [], model_profiles: [] },
    }),
  );
  await page.reload();
  await page.getByRole("tab", { name: "模型与 key", exact: true }).click();
  await expect(
    page.getByText("此范围暂无团队 key", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("此范围暂无模型方案", { exact: true }),
  ).toBeVisible();
});

test("new submit defaults to 1800 and dynamic 900 plus 900 warning", async ({
  page,
}) => {
  const calls = await fixture(page);
  const custom: any = structuredClone(catalog);
  custom.datasets[0].resolved = "public/data@sha256:fixed";
  custom.datasets[0].tasks = [
    { name: "log", package: "public/log", ref: "sha256:task" },
  ];
  custom.datasets[0].author_parameters = {
    source: custom.datasets[0].resolved,
    checked_tasks: [
      {
        name: "log",
        ref: "sha256:task",
        discovery: {
          budgets: [
            { task: "public/log", agent_seconds: 900, verifier_seconds: 900 },
          ],
        },
      },
    ],
  };
  await page.route("**/api/v1/catalog", (route) =>
    route.fulfill({ json: custom }),
  );
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/new");
  await expect(page).toHaveTitle("Harbor Helper · 团队实验室");
  await expect(page.getByText(/agent 900秒 \+ verifier 900秒/)).toBeVisible();
  await expect(page.getByText(/警告：整体上限不足/)).toBeVisible();
  await page.locator("summary").click();
  await expect(page.getByLabel("实验总时长上限（秒，含准备）")).toHaveValue(
    "1800",
  );
  await page.getByLabel("实验总时长上限（秒，含准备）").fill("1801");
  await expect(page.getByText(/警告：整体上限不足/)).toHaveCount(0);
  await page.getByLabel("实验总时长上限（秒，含准备）").fill("1800");
  await page.getByLabel("模型方案", { exact: true }).selectOption("plan1");
  await page.getByRole("button", { name: "提交实验", exact: true }).click();
  expect(
    calls.find((call) => call.path === "/submissions")?.body.wall_seconds,
  ).toBe(1800);
  expect(errors).toEqual([]);
});

test("repair retry shows parent 600 and explicitly submits 1800", async ({
  page,
}) => {
  await fixture(page);
  const body = {
    row: { ...run, status: "failed" },
    manifest: {
      effective: { agent: "oracle", wall_seconds: 600 },
      startup_policy: {
        multiplier: 1,
        tasks: [
          { task: "cad/cylinder", agent_seconds: 600, verifier_seconds: 180 },
        ],
      },
    },
    artifacts: [],
    report: null,
  };
  await page.route("**/api/v1/runs/hh-test-zero", (route) =>
    route.fulfill({ json: body }),
  );
  let submitted: any;
  await page.route("**/api/v1/runs/hh-test-zero/retry", async (route) => {
    submitted = route.request().postDataJSON();
    await route.fulfill({ json: { id: "submission-test" } });
  });
  await page.goto("/runs/hh-test-zero");
  await expect(page.getByLabel("总时长（秒；默认保留父值）")).toHaveValue(
    "600",
  );
  await expect(page.getByText(/警告：总时长不足/)).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("harbor-helper-web-retry-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: test.info().outputPath("harbor-helper-web-retry-mobile.png"),
    fullPage: true,
  });
  await page.getByLabel("总时长（秒；默认保留父值）").fill("1800");
  await expect(page.getByText(/警告：总时长不足/)).toHaveCount(0);
  await page.getByRole("button", { name: "修复后重试", exact: true }).click();
  await expect(page).toHaveURL(/submissions\/submission-test/);
  expect(submitted).toEqual({ wall_seconds: 1800 });
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

test("repair retry distinguishes unknown budgets from zero", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/v1/runs/hh-test-zero", (route) =>
    route.fulfill({
      json: {
        row: { ...run, status: "failed" },
        manifest: {
          effective: { agent: "oracle", wall_seconds: 600 },
          startup_policy: {
            tasks: [
              { task: "cylinder", agent_seconds: 600, verifier_seconds: null },
            ],
          },
        },
        artifacts: [],
        report: null,
      },
    }),
  );
  await page.goto("/runs/hh-test-zero");
  await expect(
    page.getByText(/作者预算未知，无法判断总时长是否足够/),
  ).toBeVisible();
  await expect(page.getByText(/警告：总时长不足/)).toHaveCount(0);
  await expect(page.getByLabel("总时长（秒；默认保留父值）")).toHaveValue(
    "600",
  );
});

for (const viewport of [
  { width: 390, height: 844 },
  { width: 1280, height: 900 },
]) {
  test(`long dataset digest keeps advanced controls usable at ${viewport.width}px`, async ({
    browser,
  }) => {
    const context = await browser.newContext({
      viewport,
      isMobile: viewport.width === 390,
    });
    const page = await context.newPage();
    try {
      await fixture(page);
      await page.route("**/api/v1/catalog", (route) =>
        route.fulfill({
          json: {
            ...catalog,
            datasets: [
              {
                ...catalog.datasets[0],
                id: "public-proverb",
                reference: `aider/aider-polyglot@sha256:${"a".repeat(64)}`,
                tasks: [{ name: "polyglot_python_proverb" }],
              },
            ],
            settings: { default_dataset_id: "public-proverb" },
          },
        }),
      );
      await page.goto("/new");
      await page
        .getByLabel("数据集", { exact: true })
        .selectOption("public-proverb");
      await page
        .getByLabel("任务", { exact: true })
        .selectOption("polyglot_python_proverb");
      expect(
        await page.evaluate(() => document.body.scrollWidth),
      ).toBeLessThanOrEqual(viewport.width);
      await page
        .getByText("高级参数：启动等待、尝试次数、并发与运行时长", {
          exact: true,
        })
        .click();
      await expect(page.locator("details")).toHaveAttribute("open", "");
      const wall = page.getByLabel("实验总时长上限（秒，含准备）", {
        exact: true,
      });
      await wall.fill("1600");
      await expect(wall).toHaveValue("1600");
      expect(
        await page.evaluate(() => document.body.scrollWidth),
      ).toBeLessThanOrEqual(viewport.width);
    } finally {
      await context.close();
    }
  });
}

for (const mismatch of ["none", "source", "ref"]) {
  test(`selected task budgets match source and ref: ${mismatch}`, async ({
    page,
  }) => {
    await fixture(page);
    const custom: any = structuredClone(catalog);
    custom.limits.max_wall_seconds = 7200;
    const dataset = custom.datasets[0];
    dataset.resolved = "aider/aider-polyglot@sha256:fixed";
    dataset.tasks = Array.from({ length: 225 }, (_, i) => ({
      name: i ? `task-${i}` : "polyglot_python_proverb",
      ref: `sha256:${i}`,
      package: i ? `aider/task-${i}` : "aider/polyglot_python_proverb",
    }));
    dataset.author_parameters = {
      source: mismatch === "source" ? "different/source" : dataset.resolved,
      checked_tasks: [
        {
          name: "polyglot_python_proverb",
          ref: mismatch === "ref" ? "sha256:wrong" : "sha256:0",
          discovery: {
            budgets: [
              {
                task: "aider/polyglot_python_proverb",
                agent_seconds: 1800,
                verifier_seconds: 1800,
              },
            ],
          },
        },
      ],
    };
    await page.route("**/api/v1/catalog", (route) =>
      route.fulfill({ json: custom }),
    );
    await page.goto("/new");
    await expect(
      page.getByLabel("任务", { exact: true }).locator("option"),
    ).toHaveCount(226);
    await expect(
      page.getByText(
        new RegExp(
          `另有 ${mismatch === "none" ? 224 : 225} 个所选任务作者预算未知`,
        ),
      ),
    ).toBeVisible();
    await page
      .getByLabel("任务", { exact: true })
      .selectOption("polyglot_python_proverb");
    if (mismatch !== "none") {
      await expect(
        page.getByText(/另有 1 个所选任务作者预算未知/),
      ).toBeVisible();
      await expect(page.getByText(/agent 1800秒/)).toHaveCount(0);
      await expect(page.getByText(/警告：整体上限不足/)).toHaveCount(0);
    } else {
      await expect(
        page.getByText(/agent 1800秒 \+ verifier 1800秒/),
      ).toBeVisible();
      await expect(page.getByText(/警告：整体上限不足/)).toBeVisible();
      await page.locator("summary").click();
      await page.getByLabel("实验总时长上限（秒，含准备）").fill("3600");
      await expect(page.getByText(/警告：整体上限不足/)).toBeVisible();
      await page.getByLabel("实验总时长上限（秒，含准备）").fill("5400");
      await expect(page.getByText(/警告：整体上限不足/)).toHaveCount(0);
      await page.getByLabel("任务", { exact: true }).selectOption("task-1");
      await expect(
        page.getByText(/另有 1 个所选任务作者预算未知/),
      ).toBeVisible();
      await expect(page.getByText(/agent 1800秒/)).toHaveCount(0);
    }
  });
}

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

test("automation credential explicit capabilities, password and one-time value", async ({
  page,
}) => {
  await fixture(page, "member");
  const rows: any[] = [];
  const signed: any[] = [];
  const raw = "hh_pat_v1_" + "A".repeat(43);
  await page.route("**/api/v1/access-credentials**", async (route) => {
    const req = route.request();
    let value: any = rows,
      status = 200;
    if (req.method() === "POST" && req.url().endsWith("/revoke")) {
      rows[0].revoked = 1791460100;
      value = { revoked: true };
    } else if (req.method() === "POST") {
      const body = req.postDataJSON();
      signed.push(body);
      if (body.current_password !== "correct-password") {
        status = 401;
        value = { code: "invalid_login", message: "密码复核失败" };
      } else {
        const credential = {
          id: "pat1",
          user_id: "u1",
          name: body.name,
          scopes: body.scopes,
          expires: body.expires,
          last_used: null,
          revoked: null,
        };
        rows.push(credential);
        value = { credential, token: raw };
      }
    }
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(value),
    });
  });
  await page.goto("/access-credentials");
  await expect(page.getByLabel("有效天数")).toHaveValue("30");
  await expect(
    page.getByRole("checkbox", { name: "发现与读取共享实验" }),
  ).toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "提交、重跑、修复与恢复实验" }),
  ).not.toBeChecked();
  await page.getByLabel("用途名称").fill("research");
  await page.getByLabel("当前密码").fill("wrong");
  await page.getByRole("button", { name: "签发凭证", exact: true }).click();
  await expect(page.getByText("密码复核失败")).toBeVisible();
  await expect(page.getByLabel("当前密码")).toHaveValue("");
  await page.getByLabel("当前密码").fill("correct-password");
  await page.getByLabel("有效天数").fill("730");
  await expect(page.getByLabel("有效天数")).not.toHaveAttribute("max");
  await page
    .getByRole("checkbox", { name: "提交、重跑、修复与恢复实验" })
    .check();
  await page.getByRole("button", { name: "签发凭证", exact: true }).click();
  await expect(page.getByLabel("新签发凭证")).toHaveValue(raw);
  expect(signed[1].scopes).toEqual(["read", "execute"]);
  expect(signed[1].expires - Date.now() / 1000).toBeGreaterThan(729 * 86400);
  expect(signed[1].expires - Date.now() / 1000).toBeLessThanOrEqual(
    730 * 86400,
  );
  await page.getByRole("button", { name: "已安全保存，关闭原值" }).click();
  await expect(page.getByLabel("新签发凭证")).toHaveCount(0);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "撤销 research" }),
  ).toBeVisible();
  expect(await page.content()).not.toContain(raw);
  await page.getByRole("button", { name: "撤销 research" }).click();
  await expect(
    page.getByRole("button", { name: "撤销 research" }),
  ).toBeDisabled();
});

test("管理员网页调整身份额度与维护暂停恢复", async ({ page }) => {
  const calls = await fixture(page);
  await page.goto("/admin");
  await page.getByRole("tab", { name: "容量与保留" }).click();
  const quota = page.getByLabel("每成员待处理额度（有效值不超过全局上限）");
  await quota.fill("3");
  const form = page
    .getByText("容量与保留", { exact: true })
    .filter({ hasNot: page.locator("*") })
    .locator("../..");
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await expect
    .poll(
      () =>
        calls.find((c) => c.path === "/admin/limits" && c.body)?.body
          .max_pending_per_member,
    )
    .toBe(3);
  await page.getByLabel("维护原因").fill("版本维护");
  await page.getByRole("button", { name: "暂停新受理", exact: true }).click();
  await expect(page.getByText("维护暂停：版本维护")).toBeVisible();
  await page.reload();
  await page.getByRole("tab", { name: "容量与保留" }).click();
  await expect(quota).toHaveValue("3");
  await expect(page.getByText("维护暂停：版本维护")).toBeVisible();
  await page.getByRole("button", { name: "恢复新受理", exact: true }).click();
  await expect(page.getByText("允许新受理", { exact: true })).toBeVisible();
});

test("真实调用封装绑定 PATCH 方法、动态后缀和跨段幂等查询", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/admin");
  await expect(page.getByRole("tab", { name: "容量与保留" })).toBeVisible();
  const calls: {
    path: string;
    method: string;
    body: unknown;
    requestedWith?: string;
  }[] = [];
  const responses: Record<string, unknown> = {
    "/admin/settings": { team_name: "transport-probe" },
    "/runs/dynamic-id": { row: { id: "dynamic-id" } },
    "/runs/dynamic-id/logs": { text: "transport-log" },
    "/runs/dynamic-id/report": null,
    "/attachment-operations/create/namespace/key": {
      attachment: { id: "attachment-probe" },
    },
    "/submission-operations/submit/namespace/key": { id: "submission-probe" },
  };
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    if (!(path in responses)) return route.fallback();
    calls.push({
      path,
      method: request.method(),
      body: request.postData() ? request.postDataJSON() : null,
      requestedWith: request.headers()["x-requested-with"],
    });
    await route.fulfill({ json: responses[path] });
  });
  const result = await page.evaluate(async () => {
    const { api, mutation } = await import("/src/api.ts");
    const id = "dynamic-id";
    const key = "namespace/key";
    return {
      saved: await mutation(
        "/admin/settings",
        { team_name: "transport-probe" },
        "PATCH",
      ),
      detail: await api(`/runs/${id}`),
      logs: await api(`/runs/${id}/logs`),
      report: await api(`/runs/${id}/report`),
      attachment: await api(`/attachment-operations/create/${key}`),
      submission: await api(`/submission-operations/submit/${key}`),
    };
  });
  expect(result).toEqual({
    saved: responses["/admin/settings"],
    detail: responses["/runs/dynamic-id"],
    logs: responses["/runs/dynamic-id/logs"],
    report: null,
    attachment: responses["/attachment-operations/create/namespace/key"],
    submission: responses["/submission-operations/submit/namespace/key"],
  });
  expect(calls).toHaveLength(6);
  expect(calls[0]).toEqual({
    path: "/admin/settings",
    method: "PATCH",
    body: { team_name: "transport-probe" },
    requestedWith: "harbor-helper",
  });
  expect(
    calls.slice(1).every((call) => call.method === "GET" && call.body === null),
  ).toBe(true);
});

// Redesign behavior fixtures: API interception does not exercise Hub, Docker or models.
const designRuns = [
  { ...run, id: "run-a", name: "基线 / baseline", agent: "opencode" },
  { ...run, id: "run-b", name: "附件 / candidate", agent: "opencode" },
  { ...run, id: "run-c", name: "重复 / third", agent: "opencode" },
  {
    ...run,
    id: "run-failed",
    name: "任务失败",
    status: "failed",
    agent: "oracle",
  },
  {
    ...run,
    id: "run-running",
    name: "工具准备",
    status: "running",
    audit_status: "pending",
    agent: "opencode",
  },
  {
    ...run,
    id: "run-blocked",
    name: "清理现场",
    status: "cleanup_blocked",
    audit_status: "incomplete",
    agent: "oracle",
  },
  {
    ...run,
    id: "run-queued",
    name: "等待队列",
    status: "queued",
    audit_status: "pending",
    agent: "opencode",
  },
];
const designComparison = {
  left: "run-a",
  right: "run-b",
  comparable: true,
  reasons: [],
  config_changes: {},
  environment_observations: { left: "unknown", right: "unknown" },
  bundle_change: { left: null, right: null },
  attachment_inputs: { left: { kind: "none" }, right: { kind: "none" } },
  tasks: [
    {
      task: "bracket-fit",
      left: { reward: 0 },
      right: { reward: 0.0000000002 },
      delta: { reward: 0.0000000002 },
    },
    {
      task: "shaft-align",
      left: { reward: 0.6 },
      right: { reward: 0.8 },
      delta: { reward: 0.2 },
    },
  ],
  mean_task_delta: { reward: 0.1 },
};
async function redesignFixture(page: Page) {
  const calls = await fixture(page);
  await page.route("**/api/v1/runs", (route) =>
    route.fulfill({
      json: {
        runs: designRuns,
        submissions: [
          {
            id: "prep-failed",
            status: "failed",
            submitter: "test-admin",
            created: 1791460000,
            request: { name: "来源准备失败" },
            error: "来源验证失败",
          },
          {
            id: "prep-cancelled",
            status: "cancelled",
            submitter: "test-admin",
            created: 1791460000,
            request: { name: "已取消来源" },
          },
          {
            id: "prep-linked",
            status: "ready",
            run_id: "run-a",
            request: { name: "不重复显示" },
          },
        ],
      },
    }),
  );
  await page.route("**/api/v1/compare", (route) =>
    route.fulfill({ json: designComparison }),
  );
  return calls;
}
test("workbench filters restore URL, expose preparation failures and keep ordered A/B selection", async ({
  page,
}) => {
  await redesignFixture(page);
  await page.goto("/?status=active&q=工具");
  await expect(
    page.getByRole("link", { name: "工具准备", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "基线 / baseline", exact: true }),
  ).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "活动 2" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByRole("textbox", { name: "搜索实验" })).toHaveValue(
    "工具",
  );
  await page.getByRole("button", { name: "全部 7" }).click();
  await page.getByRole("textbox", { name: "搜索实验" }).fill("");
  await expect(
    page.getByRole("link", { name: "来源准备失败", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("准备失败", { exact: true })).toBeVisible();
  await expect(page.getByText("已取消来源", { exact: true })).toBeVisible();
  await expect(page.getByText("不重复显示", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("checkbox", { name: "选择实验 工具准备" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("checkbox", { name: "选择实验 清理现场" }),
  ).toBeDisabled();
  await page
    .getByRole("checkbox", { name: "选择实验 基线 / baseline" })
    .check();
  await page
    .getByRole("checkbox", { name: "选择实验 附件 / candidate" })
    .check();
  await page.getByRole("checkbox", { name: "选择实验 重复 / third" }).click();
  await expect(
    page.getByText("已选择 A/B 两次实验", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("checkbox", { name: "选择实验 重复 / third" }),
  ).not.toBeChecked();
  await page.getByRole("link", { name: "对比实验", exact: true }).click();
  await expect(page).toHaveURL(/compare\?left=run-a&right=run-b/);
  await page.reload();
  await expect(page.getByLabel("实验 A", { exact: true })).toHaveValue("run-a");
  await expect(page.getByLabel("实验 B", { exact: true })).toHaveValue("run-b");
});
test("comparison clears prior results and ignores late requests for changed conditions", async ({
  page,
}) => {
  await redesignFixture(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let count = 0;
  await page.route("**/api/v1/compare", async (route) => {
    const n = ++count;
    if (n === 2) await gate;
    await route.fulfill({
      json: {
        ...designComparison,
        mean_task_delta: { reward: n === 2 ? 999 : n },
      },
    });
  });
  await page.goto("/compare?left=run-a&right=run-b");
  await page.getByRole("button", { name: "开始对比" }).click();
  await expect(page.locator(".report-summary")).toContainText("1");
  await page.getByRole("button", { name: "开始对比" }).click();
  await expect.poll(() => count).toBe(2);
  await page.getByLabel("实验 B", { exact: true }).selectOption("run-c");
  await expect(page.locator(".report-summary")).toHaveCount(0);
  await page.getByRole("button", { name: "开始对比" }).click();
  await expect(page.locator(".report-summary")).toContainText("3");
  const oldResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/compare") &&
      response.request().postDataJSON().right === "run-b",
  );
  release();
  await oldResponse;
  await expect(page.locator(".report-summary")).toContainText("3");
  await expect(page.locator(".report-summary")).not.toContainText("999");
  await page.getByLabel("实验 A", { exact: true }).selectOption("run-b");
  await expect(page.locator(".report-summary")).toHaveCount(0);
});
test("server incomparable verdict hides every delta even if partial task results exist", async ({
  page,
}) => {
  await redesignFixture(page);
  await page.route("**/api/v1/compare", (route) =>
    route.fulfill({
      json: {
        ...designComparison,
        comparable: false,
        reasons: ["Both runs must succeed"],
        config_changes: { attempts: { left: 1, right: 2 } },
      },
    }),
  );
  await page.goto("/compare?left=run-a&right=run-failed");
  await page.getByRole("button", { name: "开始对比" }).click();
  await expect(
    page.getByText("Both runs must succeed", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".report-summary")).toHaveCount(0);
  await expect(page.locator(".compare-table")).toHaveCount(0);
  await expect(
    page.getByRole("cell", { name: "attempts", exact: true }),
  ).toBeVisible();
});
for (const code of ["report_pending", "audit_incomplete", "evidence_expired"]) {
  test(`comparison provides dedicated feedback for ${code}`, async ({
    page,
  }) => {
    await redesignFixture(page);
    await page.route("**/api/v1/compare", (route) =>
      route.fulfill({ status: 409, json: { code, message: code } }),
    );
    await page.goto("/compare?left=run-a&right=run-b");
    await page.getByRole("button", { name: "开始对比" }).click();
    await expect(page.getByText(code, { exact: true })).toBeVisible();
    await expect(
      page.getByText(
        code === "evidence_expired" ? "证据已过期" : "报告尚未发布",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(page.locator(".compare-table")).toHaveCount(0);
  });
}
test("mobile comparison shows all four columns, valid zero and nonzero tiny delta", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await redesignFixture(page);
  await page.goto("/compare?left=run-a&right=run-b");
  await page.getByRole("button", { name: "开始对比" }).click();
  const row = page.getByRole("row").filter({ hasText: "bracket-fit" });
  await expect(row.getByRole("cell").nth(1)).toHaveText("0");
  await expect(row.getByRole("cell").nth(3)).toHaveText("2e-10");
  for (const index of [0, 1, 2, 3]) {
    const box = await row.getByRole("cell").nth(index).boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
test("capacity uses reserved slots, maintenance reason and visibly stale refresh", async ({
  page,
}) => {
  await redesignFixture(page);
  let failed = false;
  await page.route("**/api/v1/usage", (route) =>
    route.fulfill(
      failed
        ? {
            status: 503,
            json: { code: "unavailable", message: "fixture refresh failure" },
          }
        : {
            json: {
              active_jobs: 2,
              active_trials: 5,
              queued_jobs: 1,
              total_runs: 7,
              total_submissions: 9,
            },
          },
    ),
  );
  await page.route("**/api/v1/readiness", (route) =>
    route.fulfill({
      json: {
        accepting: false,
        observed: 1791460000,
        scheduler: { state: "unknown", reason: "unknown" },
        maintenance: { paused: true, reason: "维护配置", retry_at: 1791462000 },
        pending: {
          global_pending: 2,
          global_limit: 20,
          member_pending: 1,
          member_limit: 10,
        },
      },
    }),
  );
  await page.goto("/");
  await expect(page.getByLabel("受理与容量")).toContainText("实验槽位2 / 1");
  await expect(page.getByLabel("受理与容量")).toContainText("trial 槽位5 / 2");
  await expect(page.getByText(/维护暂停：维护配置/)).toBeVisible();
  await expect(page.getByLabel("受理与容量")).toContainText("不会自动恢复");
  failed = true;
  await page.getByRole("button", { name: "刷新实验" }).click();
  await expect(page.getByText(/上次成功更新.*刷新失败/)).toBeVisible();
  await expect(page.getByLabel("受理与容量")).toHaveClass(/stale/);
});
test("mobile drawer traps focus, closes by Escape and restores focus after routing", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixture(page, "member");
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "打开导航", exact: true });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "工作空间导航" });
  await expect(dialog).toBeVisible();
  await expect(
    page.getByRole("button", { name: "关闭导航", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "退出登录" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "关闭导航", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
  await trigger.click();
  await expect(dialog.getByRole("link", { name: "团队管理" })).toHaveCount(0);
  await dialog.getByRole("link", { name: "实验对比", exact: true }).click();
  await expect(page).toHaveURL(/compare/);
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await trigger.click();
  await expect(dialog).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(dialog).toHaveCount(0);
  await expect(page.locator("main")).not.toHaveAttribute("inert", "");
  await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(dialog).toHaveCount(0);
});
test("log refresh preserves literal text and distinguishes truncation, audit and expiry", async ({
  page,
}) => {
  await fixture(page);
  let state = "ok";
  await page.route("**/api/v1/runs/hh-test-zero/logs", (route) =>
    route.fulfill(
      state === "ok"
        ? {
            json: {
              text: "<script>window.logBad=1</script>\n原文 tail",
              truncated: true,
            },
          }
        : { status: 409, json: { code: state, message: state } },
    ),
  );
  await page.goto("/runs/hh-test-zero");
  await page.getByRole("tab", { name: "运行日志" }).click();
  await expect(
    page.getByText("仅显示末尾最多 256 KiB（已截断）", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".log-view")).toContainText("<script>");
  expect(await page.evaluate(() => "logBad" in window)).toBe(false);
  state = "audit_incomplete";
  await page.getByRole("button", { name: "刷新日志" }).click();
  await expect(
    page.getByText("日志安全审计异常", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".log-view")).toHaveCount(0);
  state = "evidence_expired";
  await page.getByRole("button", { name: "刷新日志" }).click();
  await expect(page.getByText("日志证据已过期", { exact: true })).toBeVisible();
  await expect(page.locator(".log-view")).toHaveCount(0);
});

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

test("empty list, no matches and refresh failure retain distinct recovery paths", async ({
  page,
}) => {
  await fixture(page);
  let mode = "error";
  await page.route("**/api/v1/runs", (route) =>
    route.fulfill(
      mode === "error"
        ? {
            status: 503,
            json: { code: "unavailable", message: "记录暂不可用" },
          }
        : { json: { runs: mode === "empty" ? [] : [run], submissions: [] } },
    ),
  );
  await page.goto("/");
  await expect(page.getByText("记录暂不可用", { exact: true })).toBeVisible();
  mode = "empty";
  await page.getByRole("button", { name: "重试加载", exact: true }).click();
  await expect(page.getByText("暂无实验", { exact: true })).toBeVisible();
  mode = "normal";
  await page.getByRole("button", { name: "刷新实验" }).click();
  await expect(
    page.getByRole("link", { name: run.id, exact: true }),
  ).toBeVisible();
  await page.getByRole("textbox", { name: "搜索实验" }).fill("no matches");
  await expect(page.getByText("没有匹配的实验", { exact: true })).toBeVisible();
  await expect(page.getByText("暂无实验", { exact: true })).toHaveCount(0);
});
test("scheduler unknown never looks ready and submission locks all inputs until response", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/v1/readiness", (route) =>
    route.fulfill({
      json: {
        accepting: false,
        scheduler: { state: "unknown", reason: "observation_unavailable" },
        maintenance: { paused: false },
        pending: {
          global_pending: 0,
          global_limit: 20,
          member_pending: 0,
          member_limit: 10,
        },
      },
    }),
  );
  await page.goto("/new");
  await expect(page.getByLabel("受理与容量").first()).toContainText(
    "调度器活动未知",
  );
  await expect(
    page.getByText("允许新受理 · 受理正常", { exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("模型方案", { exact: true }).selectOption("plan1");
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/submissions", async (route) => {
    await gate;
    await route.fulfill({
      json: { id: "submission-test", status: "preparing" },
    });
  });
  await page.getByRole("button", { name: "提交实验", exact: true }).click();
  await expect(page.getByLabel("数据集", { exact: true })).toBeDisabled();
  await expect(page.getByLabel("模型方案", { exact: true })).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "提交实验", exact: true }),
  ).toBeDisabled();
  release();
  await expect(page).toHaveURL(/submissions\/submission-test/);
});
test("report keeps zero, missing score and failed attempt distinct; diagnostics stay inside overview", async ({
  page,
}) => {
  await fixture(page);
  const diagnosis = {
    hint: "phase evidence",
    phase: "agent_setup",
    startup_multiplier: 10,
    model_status: "not_reached",
    phases: [
      { phase: "environment_setup", reached: true, seconds: null },
      { phase: "agent_setup", reached: true, seconds: 0 },
      { phase: "agent_execution", reached: false, seconds: null },
    ],
    compose: null,
  };
  await page.route("**/api/v1/runs/hh-test-zero", (route) =>
    route.fulfill({
      json: {
        row: { ...run, status: "failed" },
        manifest: { effective: { wall_seconds: 1800 } },
        artifacts: [],
        report: {
          complete: false,
          expected_attempts: 3,
          valid_attempts: 1,
          invalid_attempts: 1,
          missing_attempts: 1,
          tasks: [
            {
              task: "zero",
              valid_attempts: 1,
              expected_attempts: 1,
              mean_rewards: { reward: 0 },
              attempts: [
                { task: "zero", trial: "trial-zero", valid: true, diagnosis },
              ],
            },
            {
              task: "failed",
              valid_attempts: 0,
              expected_attempts: 1,
              mean_rewards: null,
              attempts: [
                {
                  task: "failed",
                  trial: "trial-failed",
                  valid: false,
                  exception: { type: "setup_error" },
                  diagnosis,
                },
              ],
            },
            {
              task: "missing",
              valid_attempts: 0,
              expected_attempts: 1,
              mean_rewards: null,
              attempts: [],
            },
          ],
        },
      },
    }),
  );
  await page.goto("/runs/hh-test-zero");
  await expect(
    page.locator(".diagnosis").filter({ hasText: "失败定位" }),
  ).toHaveAttribute("open", "");
  await expect(
    page.locator(".diagnosis").filter({ hasText: "执行阶段与耗时" }),
  ).not.toHaveAttribute("open", "");
  await expect(
    page.locator(".diagnosis[open]").getByText(/环境启动：耗时未知/),
  ).toBeVisible();
  await expect(
    page.locator(".diagnosis[open]").getByText(/代理准备：0.000秒/),
  ).toBeVisible();
  await expect(
    page.locator(".diagnosis[open]").getByText(/执行：未到达/),
  ).toBeVisible();
  await page.getByRole("tab", { name: "评分报告", exact: true }).click();
  await expect(page.locator(".diagnosis")).toHaveCount(0);
  await expect(
    page
      .getByRole("row")
      .filter({ has: page.getByRole("cell", { name: "zero", exact: true }) }),
  ).toContainText("reward: 0");
  await expect(
    page
      .getByRole("row")
      .filter({ has: page.getByRole("cell", { name: "failed 执行失败" }) }),
  ).toContainText("缺失评分");
  await expect(
    page.getByRole("row").filter({
      has: page.getByRole("cell", { name: "missing", exact: true }),
    }),
  ).toContainText("缺失评分");
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

test("administrator rotates master with password and expected generation", async ({
  page,
}) => {
  await fixture(page);
  let rotations = 0;
  let generation = 1;
  await page.route("**/api/v1/admin/master-key", (route) =>
    route.fulfill({
      json: {
        generation,
        rotated_at: generation === 1 ? null : 1791460000,
        available: true,
      },
    }),
  );
  await page.route("**/api/v1/admin/master-key/rotate", async (route) => {
    rotations++;
    const body = route.request().postDataJSON();
    expect(body).toEqual({
      password: "fake-revalidation-password",
      expected_generation: 1,
    });
    generation++;
    await route.fulfill({
      json: {
        generation,
        rotated_at: 1791460000,
        available: true,
        counts: { credential_versions: 4, source_credentials: 2 },
      },
    });
  });
  await page.goto("/admin?section=security");
  await expect(page.locator("dl > div").filter({ has: page.getByText("当前代次", { exact: true }) }).locator("dd")).toHaveText("1");
  await page.getByLabel("当前管理员密码").fill("fake-revalidation-password");
  await page.getByRole("button", { name: "轮换主密钥", exact: true }).click();
  await expect(page.getByText(/已轮换至代次 2/)).toBeVisible();
  await expect(page.getByLabel("当前管理员密码")).toHaveValue("");
  await page.reload();
  await expect(page.locator("dl > div").filter({ has: page.getByText("当前代次", { exact: true }) }).locator("dd")).toHaveText("2");
  expect(rotations).toBe(1);
});

test("管理员授信、动态凭证能力、拒绝历史及完整资料", async ({page}) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await fixture(page);
  let granted = false;
  await page.route("**/api/v1/admin/users", route => route.fulfill({json:[{id:"u1",username:"test-member",role:"member",enabled:true,evidence_grant:granted}]}));
  await page.route("**/api/v1/admin/users/u1/evidence-grant", async route => {
    granted = route.request().postDataJSON().enabled;
    await route.fulfill({json:{user_id:"u1",evidence_grant:granted}});
  });
  await page.route("**/api/v1/access-capabilities", route => route.fulfill({json:{scopes:granted ? ["read","execute","evidence"] : ["read","execute"],evidence_grant:granted}}));
  await page.route("**/api/v1/access-credentials", route => route.fulfill({json:[]}));
  await page.goto("/access-credentials");
  await expect(page.getByLabel("完整实验资料（须同时选择读取）")).toHaveCount(0);
  await page.goto("/admin");
  await page.getByRole("tab",{name:"受邀账户"}).click();
  await page.getByRole("button",{name:"授予完整资料权限"}).click();
  await expect(page.getByRole("button",{name:"撤销完整资料授信"})).toBeVisible();
  await page.goto("/access-credentials");
  await expect(page.getByLabel("完整实验资料（须同时选择读取）")).toBeVisible();
  await page.route("**/api/v1/operations?**", route => route.fulfill({json:{operations:[{id:"op-denied",user_id:"u1",operation:"submit",idem:"stable-key",request:{agent:"oracle"},created:1,updated:2,attempts:2,status:"rejected",result:null,error:{code:"queue_full",action:"retry_same_request"},recent:[{time:2,error:{code:"queue_full"}}],summarized_attempts:0}],offset:0,total:1,next_offset:null,attempt_limit:32}}));
  await page.goto("/operations");
  await expect(page.locator("article").getByText("已拒绝", {exact:true})).toBeVisible();
  await page.getByText("请求详情 · op-denied").click();
  await expect(page.getByText("幂等键：stable-key",{exact:false})).toBeVisible();
  await expect(page.getByText('"action": "retry_same_request"',{exact:false})).toBeVisible();
  await page.route("**/api/v1/runs/hh-test-zero/evidence", route => route.fulfill({json:{run_id:"hh-test-zero",state:"available",files:[{id:"opaque",name:"part.step",category:"artifact",bytes:10,sha256:"a".repeat(64),status:"original",processing:null,source:"run_local"}],limitations:["原生鉴权目录不采集"],session_coverage:[],legacy:false}}));
  await page.goto("/runs/hh-test-zero");
  await page.getByRole("tab",{name:"完整资料"}).click();
  await expect(page.getByRole("button",{name:"下载完整资料包",exact:true})).toBeEnabled();
  await expect(page.getByRole("link",{name:"下载文件",exact:true})).toHaveCount(0);
  await expect(page.getByText("可打包 1 个文件",{exact:false})).toBeVisible();
  await page.screenshot({path:process.env.HH_UI_OUTPUT + "/materials.png"});
  expect(errors).toEqual([]);
});


test("两阶段停止拒绝无写入、确认关闭后可显式取消并在刷新后保留", async ({ page }) => {
  const calls = await fixture(page);
  await page.goto("/admin");
  await page.getByRole("tab", { name: "容量与保留" }).click();
  await page.getByRole("button", { name: "开始停止流程", exact: true }).click();
  await page.getByRole("button", { name: "拒绝并返回", exact: true }).click();
  expect(calls.filter(c => c.path === "/admin/maintenance" && c.body)).toHaveLength(0);
  await page.getByRole("button", { name: "开始停止流程", exact: true }).click();
  await page.getByRole("button", { name: "同意关闭新受理", exact: true }).click();
  await page.getByRole("button", { name: "等待全部结束后停止", exact: true }).click();
  await expect(page.getByText("停止意图：等待全部已受理任务结束", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "取消全部未完成任务后停止", exact: true }).click();
  await page.getByRole("button", { name: "返回，不取消", exact: true }).click();
  expect(calls.filter(c => c.path === "/admin/shutdown" && c.body?.mode === "cancel")).toHaveLength(0);
  await page.getByRole("button", { name: "取消全部未完成任务后停止", exact: true }).click();
  await page.getByRole("button", { name: "确认取消全部并停止", exact: true }).click();
  await page.reload();
  await page.getByRole("tab", { name: "容量与保留" }).click();
  await expect(page.getByText("停止意图：取消全部未完成任务并清理资源", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "退出等待，保持入口关闭", exact: true }).click();
  await expect(page.getByText("停止意图：未请求停止", { exact: true })).toBeVisible();
  await expect(page.getByText("持久维护开关：已关闭新受理（跳过关闭确认）", { exact: true })).toBeVisible();
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

test("历史分离受理准备重试，服务端筛选分页与降级", async ({page}) => {
  await fixture(page);
  const queries: string[] = [];
  await page.route("**/api/v1/operations?**", async route => {
    const url = new URL(route.request().url()); queries.push(url.search);
    await route.fulfill({json:{operations:[{id:"op-accepted",user_id:"u1",username:"真实用户名",operation:"submit",idem:"same",request:{},created:1700000000,updated:1700000010,attempts:3,status:"accepted",result:{id:"sub-1",status:"failed",error:{message:"准备输入不可用"}},error:null,recent:[{error:{code:"idempotency_conflict"}}],summarized_attempts:2},{id:"op-deleted-user",user_id:"deleted-account-123",username:null,operation:"attachment_create",idem:"other",request:{},created:1,updated:1,attempts:1,status:"rejected",result:null,error:{code:"queue_full"},recent:[],summarized_attempts:0}],total:52,offset:Number(url.searchParams.get("offset")),next_offset:url.searchParams.get("offset")==="0"?50:null,attempt_limit:32}});
  });
  await page.goto("/operations");
  await expect(page.locator("article").getByText("已受理",{exact:true})).toBeVisible();
  await expect(page.getByText("提交准备：准备失败",{exact:false})).toBeVisible();
  await expect(page.getByText("最近一次重试被拒",{exact:false})).toBeVisible();
  await expect(page.getByText("真实用户名",{exact:false})).toBeVisible();
  await expect(page.getByText("用户 deleted-",{exact:false})).toBeVisible();
  await expect(page.locator("pre").first()).not.toBeVisible();
  await page.getByRole("button",{name:"下一页"}).click();
  await expect.poll(() => queries.at(-1)).toContain("offset=50");
  await page.getByLabel("受理结果",{exact:true}).selectOption("accepted");
  await expect.poll(() => queries.at(-1)).toContain("status=accepted");
  expect(queries.at(-1)).toContain("offset=0");
  await page.getByLabel("操作",{exact:true}).selectOption("submit");
  await expect.poll(() => queries.at(-1)).toContain("operation=submit");
  await page.getByLabel("仅本人").check();
  await expect.poll(() => queries.at(-1)).toContain("mine=true");
  await page.screenshot({path:test.info().outputPath("history.png"),fullPage:true});
});

test("资料只查询清单，单击单次打包、禁用与保存", async ({page}) => {
  await fixture(page);
  let packages = 0;
  await page.route("**/api/v1/runs/hh-test-zero/evidence", route => route.fulfill({json:{state:"available",files:[{id:"a",name:"hidden-file",status:"original"},{id:"b",name:"missing-file",status:"missing"}]}}));
  await page.route("**/api/v1/runs/hh-test-zero/evidence/package", async route => { packages++; await new Promise(r=>setTimeout(r,300)); await route.fulfill({contentType:"application/zip",body:Buffer.from("UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA==","base64")}); });
  await page.goto("/runs/hh-test-zero"); await page.getByRole("tab",{name:"完整资料"}).click();
  await expect(page.getByText("可打包 1 个文件；1 个已删除",{exact:false})).toBeVisible();
  expect(packages).toBe(0); await expect(page.getByText("hidden-file")).toHaveCount(0);
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button",{name:"下载完整资料包",exact:true}).click();
  await expect(page.getByRole("button",{name:"正在准备并下载…"})).toBeDisabled();
  expect((await downloaded).suggestedFilename()).toBe("hh-test-zero-materials.zip");
  expect(packages).toBe(1); await expect(page.getByText("资料包已交给浏览器保存。")).toBeVisible();
  await page.screenshot({path:test.info().outputPath("materials-download.png")});
});

for (const [code, status, text] of [["evidence_snapshot_busy",503,"资料包准备超时"],["audit_incomplete",409,"证据审计未完成或异常"],["evidence_changed",409,"资料已变化"],["evidence_grant_required",403,"未获得完整资料权限"],["login_required",401,"登录已过期"],["unknown_failure",500,"fixture failure"]] as const) {
  test(`资料下载错误留在页面 ${code}`, async ({page}) => {
    await fixture(page);
    await page.route("**/api/v1/runs/hh-test-zero/evidence",route=>route.fulfill({json:{state:"available",files:[]}}));
    await page.route("**/api/v1/runs/hh-test-zero/evidence/package",route=>route.fulfill({status,json:{code,message:"fixture failure",request_id:"request-proof"}}));
    await page.goto("/runs/hh-test-zero"); await page.getByRole("tab",{name:"完整资料"}).click();
    await page.getByRole("button",{name:"下载完整资料包",exact:true}).click();
    await expect(page.getByText(text,{exact:false})).toBeVisible();
    await expect(page.getByText("请求编号：request-proof")).toBeVisible();
    await expect(page.getByRole("button",{name:"下载完整资料包",exact:true})).toBeEnabled();
    await expect(page).toHaveURL(/runs\/hh-test-zero$/);
  });
}
for (const state of ["in_progress","expired"]) test(`资料状态 ${state}`,async ({page}) => {
  await fixture(page); await page.route("**/api/v1/runs/hh-test-zero/evidence",route=>route.fulfill({json:{state,files:[]}}));
  await page.goto("/runs/hh-test-zero"); await page.getByRole("tab",{name:"完整资料"}).click();
  await expect(page.getByRole("button",{name:"下载完整资料包",exact:true})).toBeDisabled();
  await expect(page.getByText(state==="expired"?"已过期，无法恢复":"运行中，结束且审计完成后提供",{exact:false})).toBeVisible();
});

test("历史加载、空、失败与筛选旧响应隔离", async ({page}) => {
  await fixture(page);
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let first = true;
  await page.route("**/api/v1/operations?**", async route => {
    if (first) { first = false; await held; await route.fulfill({json:{operations:[{id:"stale",user_id:"old",operation:"submit",status:"accepted",result:null,error:null,recent:[],attempts:1,created:1,updated:1,summarized_attempts:0}],total:1,next_offset:null}}); }
    else await route.fulfill({json:{operations:[],offset:0,total:0,next_offset:null}});
  });
  await page.goto("/operations"); await expect(page.locator("article")).toHaveCount(0);
  await page.getByLabel("受理结果",{exact:true}).selectOption("rejected");
  await expect(page.getByText("暂无请求记录",{exact:true})).toBeVisible();
  const staleResponse = page.waitForResponse(response =>
    response.url().includes("/api/v1/operations?") && !response.url().includes("status=rejected"));
  release();
  await (await staleResponse).finished();
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
  await expect(page.locator("article")).toHaveCount(0);
  await page.route("**/api/v1/operations?**",route=>route.fulfill({status:503,json:{message:"历史暂不可用",request_id:"history-request"}}));
  await page.getByRole("button",{name:"刷新",exact:true}).click();
  await expect(page.getByRole("alert")).toContainText("历史暂不可用");
});

test("资料 pending 仅刷新清单；触屏帮助无表单副作用", async ({page,browser}) => {
  await fixture(page);
  let manifests = 0, packages = 0;
  await page.route("**/api/v1/runs/hh-test-zero/evidence",route=>{ manifests++; return route.fulfill({json:{state:manifests>1?"expired":"available",files:[]}}); });
  await page.route("**/api/v1/runs/hh-test-zero/evidence/package",route=>{ packages++; return route.fulfill({status:409,json:{code:"evidence_pending"}}); });
  await page.goto("/runs/hh-test-zero"); await page.getByRole("tab",{name:"完整资料"}).click();
  await page.getByRole("button",{name:"下载完整资料包",exact:true}).click();
  await expect(page.getByText("资料状态：已过期，无法恢复",{exact:true})).toBeVisible();
  expect(packages).toBe(1); expect(manifests).toBe(2);
  const context = await browser.newContext({viewport:{width:390,height:844},hasTouch:true,isMobile:true});
  const mobile = await context.newPage();
  const calls = await fixture(mobile);
  await mobile.goto(new URL("/attachments",page.url()).href);
  const input = mobile.getByLabel("显示名称",{exact:true}); await input.fill("保留输入");
  const help = mobile.getByRole("button",{name:"附件 ZIP帮助"});
  await help.tap(); await expect(mobile.getByRole("dialog")).toBeVisible();
  await help.tap(); await expect(mobile.getByRole("dialog")).toHaveCount(0);
  await expect(input).toHaveValue("保留输入");
  expect(calls.filter(c=>c.path==="/attachments" && c.body)).toHaveLength(0);
  await context.close();
});

for (const width of [1440,1024,390]) test(`历史与资料长文、加载、错误截图 ${width}`,async ({page}) => {
  await page.setViewportSize({width,height:900}); await fixture(page);
  const errors: string[] = []; page.on("pageerror", e=>errors.push(e.message));
  await page.route("**/api/v1/operations?**",route=>route.fulfill({json:{operations:[{id:"op-long-record-12345",user_id:"user1",username:"可识别的团队成员",operation:"submit",status:"accepted",attempts:4,created:1700000000,updated:1700000001,result:{id:"sub-real-reference",status:"ready",run_id:"hh-test-zero"},recent:[{error:{code:"idempotency_conflict"}}],request:{},error:null,idem:"long".repeat(50),summarized_attempts:2}],total:1,offset:0,next_offset:null}}));
  await page.goto("/operations"); await expect(page.locator("article")).toHaveCount(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({path:test.info().outputPath(`history-${width}.png`),fullPage:true});
  let release!: () => void; const held = new Promise<void>(resolve=>{release=resolve;});
  await page.route("**/api/v1/runs/hh-test-zero/evidence",async route=>{await held; await route.fulfill({json:{state:"available",files:[{id:"good",name:"never-shown",status:"original"},{id:"missing",status:"deleted"}]}});});
  await page.goto("/runs/hh-test-zero"); await page.getByRole("tab",{name:"完整资料"}).click();
  await expect(page.getByRole("button",{name:"刷新资料状态"})).toBeDisabled();
  await page.screenshot({path:test.info().outputPath(`materials-loading-${width}.png`)});
  release(); await expect(page.getByText("可打包 1 个文件",{exact:false})).toBeVisible();
  await page.route("**/api/v1/runs/hh-test-zero/evidence/package",route=>route.fulfill({status:503,json:{code:"evidence_snapshot_busy",request_id:"synthetic-snapshot-request"}}));
  await page.getByRole("button",{name:"下载完整资料包",exact:true}).click();
  await expect(page.getByRole("alert")).toContainText("资料包准备超时");
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({path:test.info().outputPath(`materials-error-${width}.png`),fullPage:true});
  expect(errors).toEqual([]);
});

for (const change of ["filter", "page"] as const) {
  test(`历史已有成功记录后${change}失败隐藏旧列表计数并可重试`, async ({
    page,
  }) => {
    await fixture(page);
    let fail = true;
    await page.route("**/api/v1/operations?**", async (route) => {
      const query = new URL(route.request().url()).searchParams;
      const changed =
        change === "filter"
          ? query.get("status") === "rejected"
          : query.get("offset") === "50";
      if (changed && fail)
        return route.fulfill({
          status: 503,
          json: {
            message: "当前历史加载失败",
            request_id: "history-filter-failure",
          },
        });
      await route.fulfill({
        json: {
          operations: [
            {
              id: changed ? "op-current" : "op-old",
              user_id: "u1",
              username: changed ? "当前结果用户" : "旧条件用户",
              operation: "submit",
              status: changed && change === "filter" ? "rejected" : "accepted",
              result: null,
              error: null,
              recent: [],
              attempts: 1,
              created: 1,
              updated: 1,
              summarized_attempts: 0,
            },
          ],
          total: change === "page" ? 51 : 1,
          offset: Number(query.get("offset")),
          next_offset: !changed && change === "page" ? 50 : null,
        },
      });
    });
    await page.goto("/operations");
    await expect(page.locator("article")).toContainText("旧条件用户");
    await expect(page.locator(".history-pagination")).toContainText(
      change === "page" ? "1–1 / 51 条" : "1–1 / 1 条",
    );
    if (change === "filter")
      await page
        .getByLabel("受理结果", { exact: true })
        .selectOption("rejected");
    else
      await page.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("当前历史加载失败");
    await expect(page.locator("article")).toHaveCount(0);
    await expect(page.locator(".history-pagination")).not.toContainText(
      /\d+–\d+ \/|0 条记录/,
    );
    await expect(page.getByText("暂无请求记录", { exact: true })).toHaveCount(
      0,
    );
    await expect(
      page.getByRole("button", { name: "下一页", exact: true }),
    ).toBeDisabled();
    fail = false;
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await expect(page.locator("article")).toContainText("当前结果用户");
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(page.locator(".history-pagination")).toContainText(
      change === "page" ? "51–51 / 51 条" : "1–1 / 1 条",
    );
    if (change === "filter")
      await expect(page.getByLabel("受理结果", { exact: true })).toHaveValue(
        "rejected",
      );
  });
}

test("历史成功后快切失败与恢复不被迟到的旧条件成功覆盖", async ({ page }) => {
  await fixture(page);
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let oldStarted!: () => void;
  const started = new Promise<void>((resolve) => {
    oldStarted = resolve;
  });
  let fail = true;
  await page.route("**/api/v1/operations?**", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    if (query.get("operation") === "cancel") {
      oldStarted();
      await held;
    }
    if (query.get("status") === "rejected" && fail)
      return route.fulfill({ status: 503, json: { message: "快切失败" } });
    await route.fulfill({
      json: {
        operations: [
          {
            id: "op-" + query,
            user_id: "u1",
            username:
              query.get("operation") === "cancel"
                ? "迟到旧结果"
                : query.get("status") === "rejected"
                  ? "恢复当前结果"
                  : "初始成功结果",
            operation: query.get("operation") || "submit",
            status: query.get("status") || "accepted",
            result: null,
            error: null,
            recent: [],
            attempts: 1,
            created: 1,
            updated: 1,
            summarized_attempts: 0,
          },
        ],
        total: query.get("operation") === "cancel" ? 99 : 1,
        offset: 0,
        next_offset: null,
      },
    });
  });
  await page.goto("/operations");
  await expect(page.locator("article")).toContainText("初始成功结果");
  await page.getByLabel("操作", { exact: true }).selectOption("cancel");
  await started;
  await page.getByLabel("受理结果", { exact: true }).selectOption("rejected");
  await page.getByLabel("操作", { exact: true }).selectOption("submit");
  await expect(page.getByRole("alert")).toContainText("快切失败");
  await expect(page.locator("article")).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.locator("article")).toContainText("恢复当前结果");
  const late = page.waitForResponse(
    (response) =>
      new URL(response.url()).searchParams.get("operation") === "cancel" &&
      response.status() === 200,
  );
  release();
  await late;
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  await expect(page.locator("article")).toContainText("恢复当前结果");
  await expect(page.locator("article")).not.toContainText("迟到旧结果");
  await expect(page.locator(".history-pagination")).toContainText("1–1 / 1 条");
});

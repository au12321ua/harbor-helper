import { test, fixture, catalog } from "./fixture";
import { expect } from "@playwright/test";
import { holdCatalogRefresh, expectEditorsLocked } from "./ui-support";
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

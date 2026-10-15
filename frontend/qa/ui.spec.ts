import { test, expect, type Page } from "@playwright/test";
const user = { id: "u1", username: "test-admin", role: "admin" };
const run = {
  id: "hh-test-zero",
  submitter: "test-admin",
  status: "succeeded",
  created: 1791460000,
  audit_status: "clean",
  dataset: "team/test@1",
  model_profile: "plan1",
  concurrency: 1,
};
const catalog = {
  providers: [
    {
      id: "p1",
      name: "测试提供商",
      endpoint: "https://example.invalid/v1",
      protocol: "openai-compatible",
      enabled: true,
    },
  ],
  credentials: [
    {
      id: "c1",
      label: "测试凭据",
      provider_id: "p1",
      current_version: 1,
      enabled: true,
    },
  ],
  model_profiles: [
    {
      id: "plan1",
      name: "测试方案",
      model: "test-model",
      provider_id: "p1",
      credential_id: "c1",
      params: {},
      enabled: true,
    },
  ],
  datasets: [
    {
      id: "dataset1",
      name: "测试数据集",
      reference: "team/test@1",
      ready: true,
      version: 2,
      tasks: [{ name: "answer" }],
      author_parameters: {
        id: "dataset1",
        version: 0,
        values: {},
        status: "unchecked",
      },
    },
  ],
  settings: { default_dataset_id: "dataset1" },
  default_dataset: "team/test@1",
  limits: {
    max_jobs: 1,
    max_trials: 2,
    max_queue: 20,
    max_pending_per_member: 10,
    max_wall_seconds: 1800,
    max_attempts: 3,
    max_cpus_per_trial: 2,
    max_memory_mb_per_trial: 2048,
    max_upload_bytes: 10485760,
    log_retention_days: 30,
    artifact_retention_days: 30,
  },
};
async function fixture(page: Page, role = "admin", logged = true) {
  let authenticated = logged;
  const currentCatalog = structuredClone(catalog);
  let paused = false;
  let maintenanceReason = "";
  const calls: { path: string; body: any; headers: Record<string, string> }[] =
    [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname.replace("/api/v1", "");
    let body: any;
    try {
      body = request.postDataJSON();
    } catch {}
    calls.push({ path, body, headers: request.headers() });
    let value: any = {};
    let status = 200;
    if (path === "/setup") value = { initialized: true };
    else if (path === "/me") {
      value = { ...user, role };
      if (!authenticated) {
        status = 401;
        value = { code: "unauthorized", message: "请登录" };
      }
    } else if (path === "/auth/login") {
      authenticated = true;
      value = { user: { ...user, role } };
    } else if (path === "/auth/logout") {
      authenticated = false;
      value = { ok: true };
    } else if (path === "/readiness")
      value = {
        initialized: true,
        accepting: !paused,
        observed: 1791460000,
        scheduler: {
          state: "ready",
          reason: "recent_activity",
          observed: 1791460000,
        },
        maintenance: { paused, reason: maintenanceReason, retry_at: null },
        pending: {
          member_pending: 0,
          global_pending: 0,
          member_limit: currentCatalog.limits.max_pending_per_member,
          global_limit: currentCatalog.limits.max_queue,
        },
      };
    else if (path === "/admin/maintenance") {
      paused = body.paused;
      maintenanceReason = body.reason;
      value = { paused };
    } else if (path === "/admin/limits") {
      Object.assign(currentCatalog.limits, body);
      value = currentCatalog.limits;
    } else if (path === "/catalog") value = currentCatalog;
    else if (path === "/admin/model-profiles" && request.method() === "POST") {
      const index = currentCatalog.model_profiles.findIndex(
        (p) => p.id === body.id,
      );
      const previous = currentCatalog.model_profiles[index] as any;
      value = {
        ...body,
        id: body.id || "plan-new",
        version: (previous?.version || 1) + 1,
      };
      if (index >= 0) currentCatalog.model_profiles[index] = value;
      else currentCatalog.model_profiles.push(value);
    } else if (path === "/usage")
      value = {
        total_runs: 1,
        total_submissions: 1,
        active_jobs: 0,
        active_trials: 0,
        queued_jobs: 0,
      };
    else if (path === "/runs")
      value = {
        runs: [
          run,
          {
            ...run,
            id: "hh-other-running",
            submitter: "another-member",
            status: "running",
            audit_status: "pending",
          },
        ],
        submissions: [],
      };
    else if (path === "/runs/hh-test-zero")
      value = {
        row: run,
        manifest: {
          source: { dataset: "team/test@1" },
          profile: { model: "test-model" },
        },
        artifacts: [{ id: "answer", name: "answer.txt", deleted: false }],
        report: {
          complete: true,
          expected_attempts: 1,
          valid_attempts: 1,
          missing_attempts: 0,
          tasks: [
            {
              task: "test-answer",
              expected_attempts: 1,
              valid_attempts: 1,
              mean_rewards: { reward: 0 },
            },
          ],
        },
      };
    else if (path === "/runs/hh-other-running")
      value = {
        row: {
          ...run,
          id: "hh-other-running",
          submitter: "another-member",
          status: "running",
          audit_status: "pending",
        },
        manifest: {},
        artifacts: [],
        report: null,
      };
    else if (path.endsWith("/logs"))
      value = {
        text: '[bold]literal markup[/bold]\n<script>window.bad=1</script>\n"quoted"',
      };
    else if (path === "/submissions") {
      value = { id: "submission-test", status: "preparing" };
    } else if (path === "/submissions/submission-test")
      value = {
        id: "submission-test",
        submitter: user.username,
        status: "preparing",
      };
    else if (path === "/compare")
      value = { comparable: false, reasons: ["来源数据集不同"] };
    else if (path === "/admin/users") value = [{ ...user, enabled: true }];
    else if (path.startsWith("/admin/")) value = { ok: true };
    else if (path.endsWith("/rerun")) value = { id: "submission-test" };
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(value),
    });
  });
  return calls;
}
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
    path: "/tmp/harbor-helper-web-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "/tmp/harbor-helper-web-mobile.png",
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
  expect(submitted?.headers["idempotency-key"]).toHaveLength(32);
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
  await page.getByLabel("提供商", { exact: true }).first().selectOption("p1");
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
  await page.getByRole("link", { name: "修改输入后新提交" }).click();
  await expect(page.getByLabel("实验名称（可选）")).toHaveValue("失败示例");
  await expect(page.getByLabel("任务", { exact: true })).toHaveValue("answer");
  await expect(page.getByLabel("执行方案", { exact: true })).toHaveValue(
    "oracle",
  );
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
        label: "Hub 来源（owner/name@版本）",
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
  await expect(
    page.getByText(
      "保存仅代表加密持久化，未验证Hub身份或数据集访问权限。访问验证结果请查看数据集条目的验证状态。",
      { exact: true },
    ),
  ).toBeVisible();
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
    .locator(".font-semibold")
    .filter({ hasText: /^A$/ })
    .locator("..")
    .locator("..")
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
      "以下条件只缩小左侧列表；右侧新建或编辑表单中的提供商与团队 key 决定保存绑定。筛选不会修改表单或已有配置。",
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
    path: "/tmp/harbor-helper-web-retry-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "/tmp/harbor-helper-web-retry-mobile.png",
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
  await page.getByLabel("检查任务（可多选）").selectOption(["answer"]);
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
  await page
    .getByLabel("检查任务（可多选）", { exact: true })
    .selectOption(names.slice(0, 51));
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
  await expect(page.getByText("sha256:v1", { exact: false })).toBeVisible();
  await page.screenshot({
    path: "/tmp/hh-attachment-validation/attachments-desktop.png",
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
  await page.getByLabel("附件 ZIP").setInputFiles({
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
    path: "/tmp/hh-attachment-validation/attachments-mobile.png",
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
  await page.goto("/compare");
  await page.getByLabel("实验 A").selectOption("hh-test-zero");
  await page.getByLabel("实验 B").selectOption("hh-other-running");
  await page.getByRole("button", { name: "开始对比" }).click();
  await expect(
    page.getByText("实验 A 附件：无附件", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("实验 B 附件：av-candidate-v1 · sha256:candidate", {
      exact: true,
    }),
  ).toBeVisible();
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

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
    },
  ],
  settings: { default_dataset_id: "dataset1" },
  default_dataset: "team/test@1",
  limits: {
    max_jobs: 1,
    max_trials: 2,
    max_queue: 20,
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
      value = { user: { ...user, role } };
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
      value = { submission_id: "submission-test", status: "preparing" };
    } else if (path === "/submissions/submission-test")
      value = {
        id: "submission-test",
        submitter: user.username,
        status: "preparing",
      };
    else if (path === "/compare")
      value = { comparable: false, reasons: ["来源数据集不同"] };
    else if (path === "/admin/users")
      value = { users: [{ ...user, enabled: true }] };
    else if (path.startsWith("/admin/")) value = { ok: true };
    else if (path.endsWith("/rerun"))
      value = { submission_id: "submission-test" };
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
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/v1/catalog", async (route) => {
    await gate;
    await route.fallback();
  }, { times: 1 });
  return release;
}
async function expectEditorsLocked(page: Page) {
  await expect(page.getByRole("status").filter({ hasText: "正在保存并刷新配置" })).toBeVisible();
  await expect(page.locator("input:enabled, textarea:enabled, select:enabled")).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "模型与 key", exact: true })).toBeDisabled();
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
  const mutation = page.waitForResponse((r) => r.url().endsWith("/admin/model-profiles") && r.request().method() === "POST");
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
  expect(calls.filter((c) => c.path === "/admin/model-profiles" && c.body)).toHaveLength(3);
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
  await expect(page.getByRole("button", { name: "重跑实验" })).toBeVisible();
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
    current.runtimes = [
      {
        id: "runtime1",
        name: "环境旧名",
        image: "python:old",
        image_env: [],
        enabled: true,
        status: "unverified",
        version: 1,
      },
    ];
    current.datasets[0] = {
      ...current.datasets[0],
      name: "数据集旧名",
      runtime_id: "runtime1",
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
      current[spec.list][0] = {
        ...v,
        version: saves.length + 1,
        status: "unverified",
      };
      await route.fulfill({ json: current[spec.list][0] });
    });
    await page.goto("/admin");
    await page.getByRole("tab", { name: spec.tab, exact: true }).click();
    await page.getByRole("button", { name: spec.button, exact: true }).click();
    const input = page.getByLabel(spec.label, { exact: true });
    await input.fill(spec.value);
    const form = page.locator("form").filter({ has: input });
    const releaseRefresh = await holdCatalogRefresh(page);
    const mutation = page.waitForResponse((r) => r.url().endsWith(spec.path) && r.request().method() === "POST");
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
      saves.map((v) =>
        kind === "provider"
          ? v.endpoint
          : v.reference,
      ),
    ).toEqual([spec.value, spec.value]);
  });
}
test("failed credential save retains nonsecret inputs and clears secret", async ({
  page,
}) => {
  await fixture(page);
  let releaseFailure!: () => void;
  const gate = new Promise<void>((resolve) => { releaseFailure = resolve; });
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
  const request = page.waitForRequest((r) => r.url().endsWith("/admin/credentials") && r.method() === "POST");
  await form.getByRole("button", { name: "保存", exact: true }).click();
  await request;
  await expectEditorsLocked(page);
  await expect(form.getByLabel("密钥", { exact: true })).toBeDisabled();
  releaseFailure();
  await expect(form.getByLabel("Key 名称")).toBeEnabled();
  await expect(form.getByText("操作未完成", {exact:true})).toBeVisible();
  await expect(form.getByLabel("Key 名称")).toHaveValue("待修正key名称");
  await expect(form.getByLabel("提供商", { exact: true })).toHaveValue("p1");
  await expect(form.getByLabel("密钥", { exact: true })).toHaveValue("");
});

test("Hub status survives reload and distinguishes storage from access validation", async ({page}) => {
  await fixture(page);
  const current: any = structuredClone(catalog);
  current.hub = {state: "unset", mode: "anonymous", version: null, updated_at: null};
  await page.route("**/api/v1/catalog", route => route.fulfill({json: current}));
  await page.route("**/api/v1/admin/hub", async route => {
    current.hub = {state: "active", mode: "team", version: (current.hub.version || 0) + 1, updated_at: 1791518000};
    await route.fulfill({json: current.hub});
  });
  await page.route("**/api/v1/admin/hub/disable", async route => {
    current.hub = {...current.hub, state: "disabled", mode: "anonymous"};
    await route.fulfill({json: current.hub});
  });
  await page.goto("/admin");
  await expect(page.getByText("凭据：未设置", {exact:true})).toBeVisible();
  const form = page.locator("form").filter({has: page.getByLabel("Hub PAT", {exact:true})});
  for (let version = 1; version <= 2; version++) {
    await form.getByLabel("Hub PAT", {exact:true}).fill("fake-hub-ui-pat");
    await form.getByRole("button", {name:"保存", exact:true}).click();
    await expect(page.getByText("凭据：已设置（启用）", {exact:true})).toBeVisible();
    await expect(form.getByLabel("Hub PAT", {exact:true})).toHaveValue("");
    await expect(page.getByText(new RegExp(`版本：v${version}`))).toBeVisible();
    await page.reload();
    await expect(page.getByText("凭据：已设置（启用）", {exact:true})).toBeVisible();
  }
  await expect(page.getByText("保存仅代表加密持久化，未验证Hub身份或数据集访问权限。访问验证结果请查看数据集条目的验证状态。", {exact:true})).toBeVisible();
  await page.getByRole("button", {name:"停用 Hub 凭据，改为匿名来源"}).click();
  await expect(page.getByText("凭据：已停用", {exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByText("凭据：已停用", {exact:true})).toBeVisible();
});

test("Docker inventory is read-only and source needs no runtime", async ({page}) => {
  const calls = await fixture(page);
  await page.route("**/api/v1/admin/docker", route => route.fulfill({json:{state:"ready", checked_at:1791518000, message:"Docker daemon 可达", images:[{reference:"python:local"}], truncated:false}}));
  await page.goto("/admin");
  await page.getByRole("tab", {name:"Docker 诊断", exact:true}).click();
  await page.getByRole("button", {name:"发现本机 Docker 与镜像", exact:true}).click();
  await expect(page.getByText("Docker daemon 可达", {exact:true})).toBeVisible();
  await expect(page.getByText("python:local", {exact:true})).toBeVisible();
  await expect(page.getByLabel("Docker 镜像引用", {exact:true})).toHaveCount(0);
  await expect(page.getByLabel("任务镜像约定", {exact:true})).toHaveCount(0);
  await page.getByRole("tab", {name:"数据集", exact:true}).click();
  await expect(page.getByLabel("运行环境", {exact:true})).toHaveCount(0);
  expect(calls.filter(c => c.path === "/admin/catalog/runtime" && c.body)).toHaveLength(0);
  await page.getByRole("tab", {name:"Docker 诊断", exact:true}).click();
  await page.route("**/api/v1/admin/docker", route => route.fulfill({json:{state:"permission_denied", checked_at:1791518001, message:"服务账户没有daemon访问权限", images:[], truncated:false}}));
  await page.getByRole("button", {name:"发现本机 Docker 与镜像", exact:true}).click();
  await expect(page.getByText("服务账户没有daemon访问权限", {exact:true})).toBeVisible();
});

test("explicit new provider creates another object and editing preserves its peers", async ({page}) => {
  await fixture(page);
  const current: any = structuredClone(catalog);
  current.providers = [];
  const writes: any[] = [];
  await page.route("**/api/v1/catalog", route => route.fulfill({json: current}));
  await page.route("**/api/v1/admin/providers", async route => {
    const v = route.request().postDataJSON();
    writes.push(v);
    const index = current.providers.findIndex((p: any) => p.id === v.id);
    const saved = {...v, id: v.id || `provider${current.providers.length + 1}`, version: index < 0 ? 1 : current.providers[index].version + 1};
    if (index < 0) current.providers.push(saved); else current.providers[index] = saved;
    await route.fulfill({json: saved});
  });
  await page.goto("/admin");
  await page.getByRole("tab", {name:"模型与 key", exact:true}).click();
  const form = page.locator("form").filter({has:page.getByLabel("提供商名称", {exact:true})});
  for (const name of ["A", "B"]) {
    await page.getByRole("button", {name:"新建提供商", exact:true}).click();
    await expect(page.getByLabel("提供商名称", {exact:true})).toHaveValue("");
    await page.getByLabel("提供商名称", {exact:true}).fill(name);
    await page.getByLabel("API 端点", {exact:true}).fill(`https://${name.toLowerCase()}.invalid/v1`);
    await form.getByRole("button", {name:"保存", exact:true}).click();
    await expect(page.getByText(`正在编辑：${name}`, {exact:false})).toBeVisible();
  }
  expect(current.providers).toHaveLength(2);
  expect(writes.map(v => v.id)).toEqual([undefined, undefined]);
  await page.locator(".font-semibold").filter({hasText:/^A$/}).locator("..").locator("..").getByRole("button", {name:"编辑提供商", exact:true}).click();
  await page.getByLabel("API 端点", {exact:true}).fill("https://a-edited.invalid/v1");
  await form.getByRole("button", {name:"保存", exact:true}).click();
  await expect.poll(() => writes.length).toBe(3);
  expect(writes[2].id).toBe("provider1");
  expect(current.providers[1].name).toBe("B");
  expect(current.providers[1].endpoint).toBe("https://b.invalid/v1");
});

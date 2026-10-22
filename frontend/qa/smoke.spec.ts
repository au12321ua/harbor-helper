// Walks the M2 pages against a fresh, disposable service started with the demo executor:
//   maestro --config <tmp>/config.toml init        (prints the setup token)
//   maestro --config <tmp>/config.toml serve --port 8431 --demo-executor
//   MAESTRO_SETUP_TOKEN=<token> npm run test:ui
// Never point this at a real team state: it creates an admin, runs, PATs and invitations.
import { expect, test } from "@playwright/test";

const token = process.env.MAESTRO_SETUP_TOKEN;
const password = "smoke-password-123";



test("setup, run, PAT, admin and invitation flow", async ({ page, browser }) => {
  test.skip(!token, "MAESTRO_SETUP_TOKEN not set");
  await page.goto("/");
  await expect(page).toHaveTitle("Maestro");
  await page.getByLabel("初始化令牌").fill(token!);
  await page.getByLabel("管理员用户名").fill("admin");
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "创建管理员并登录" }).click();
  await expect(page.getByRole("heading", { name: "运行" })).toBeVisible();
  await expect(page.getByText("可受理运行")).toBeVisible();

  // Datasets (read only).
  await page.getByRole("link", { name: "数据集" }).click();
  await expect(page.getByText("demo/arith")).toBeVisible();
  await expect(page.getByText("add-01")).toBeVisible();

  // New run, explicit task selection.
  await page.getByRole("link", { name: "运行", exact: true }).click();
  await page.getByRole("link", { name: "新建运行" }).click();
  await page.getByLabel("运行名称").fill("smoke run");
  await page.getByLabel("手动选择").check();
  await page.getByLabel("选择 add-01").check();
  await page.getByLabel("选择 mul-01").check();
  await page.getByRole("button", { name: "提交运行" }).click();
  await expect(page).toHaveURL(/\/runs\/(?!new$)[^/]+$/);
  const runUrl = page.url();
  await expect(page.getByText("每 2 秒自动刷新")).toBeVisible();
  await expect(page.getByText("已结束")).toBeVisible({ timeout: 60_000 });
  for (const title of ["生命周期", "评分覆盖", "产物保存", "环境清理"]) {
    await expect(page.getByText(title, { exact: true })).toBeVisible();
  }
  await expect(page.getByTestId("trial-row")).toHaveCount(2);
  await page.getByTestId("trial-row").first().click();
  await expect(page.getByText("第 1 次尝试").first()).toBeVisible();
  await page.screenshot({ path: "/tmp/maestro-web-ui-results/run-detail.png", fullPage: true });

  // Deep link reload.
  await page.goto(runUrl);
  await expect(page.getByText("配置快照")).toBeVisible();

  // PAT shown once.
  await page.getByRole("link", { name: "个人设置" }).click();
  await page.getByLabel("名称").fill("smoke pat");
  await page.getByRole("button", { name: "创建令牌" }).click();
  await expect(page.getByText("只显示一次")).toBeVisible();
  await expect(page.getByTestId("one-time-secret")).toBeVisible();
  await page.getByRole("button", { name: "我已保存，关闭" }).click();
  await expect(page.getByText("smoke pat")).toBeVisible();

  // Admin pages.
  await page.getByRole("link", { name: "管理" }).click();
  await expect(page.getByRole("cell", { name: "admin", exact: true }).first()).toBeVisible();
  await page.getByRole("tab", { name: "凭据" }).click();
  await page.getByLabel("名称").fill("smoke-key");
  await page.getByLabel("提供商").fill("fake");
  await page.getByLabel("值（只写）").fill("not-a-real-secret");
  await page.getByRole("button", { name: "添加凭据" }).click();
  await expect(page.getByRole("cell", { name: "smoke-key" })).toBeVisible();
  await page.getByRole("tab", { name: "主密钥" }).click();
  await expect(page.getByText("代（generation）")).toBeVisible();
  await page.getByRole("tab", { name: "审计" }).click();
  await expect(page.getByText("run.cancel").or(page.getByText("credential.create")).first()).toBeVisible();
  await page.getByRole("tab", { name: "邀请" }).click();
  await page.getByRole("button", { name: "生成邀请链接" }).click();
  const link = (await page.getByTestId("one-time-secret").textContent())!;
  expect(link).toContain("/invite#");

  // Accept the invitation in a fresh browser context: the member has no admin nav.
  const other = await browser.newContext();
  const member = await other.newPage();
  await member.goto(link);
  await expect(member.getByRole("heading", { name: "接受邀请" })).toBeVisible();
  await member.getByLabel("用户名").fill("alice");
  await member.getByLabel("密码").fill(password);
  await member.getByRole("button", { name: "创建账户并登录" }).click();
  await expect(member.getByRole("heading", { name: "运行" })).toBeVisible();
  await expect(member.getByRole("link", { name: "管理" })).toHaveCount(0);
  await expect(member.getByText("smoke run")).toBeVisible();
  await member.getByRole("button", { name: "退出" }).click();
  await expect(member.getByRole("heading", { name: "登录" })).toBeVisible();
  await other.close();
});

// Score rendering rules with intercepted API responses (no backend state touched):
// 0 shows "0", null shows "未评分" with its reason; four run dimensions stay separate.
test("score and dimension rendering", async ({ page }) => {
  const meta = { request_id: "req_test" };
  const me = {
    id: "usr_1", username: "u", display_name: "U", role: "member", status: "active",
    revision: 1, created_at: "2026-10-22T00:00:00Z", disabled_at: null,
    auth_channel: "web_session", pat_id: null, pat_scope: null,
  };
  const run = {
    id: "run_x", name: "fixture run", owner_id: "usr_2", pat_id: null, relation: "initial",
    source_run_id: null, dataset_version_id: "dsv_1", operation_id: "op_1",
    client_request_id: null, state: "finished", result_completeness: "partial",
    artifact_state: "failed", cleanup_state: "failed", stop_requested: false, stop_reason: null,
    counts: { planned: 3, terminal: 3, scored: 1, errors: 2, not_started: 0, cancelled: 0,
      interrupted: 0, active: 0, queued: 0 },
    accepted_at: "2026-10-22T00:00:00Z", started_at: null, finished_at: null,
    deadline_at: "2026-10-25T00:00:00Z", allowed_actions: ["view"], links: {},
    snapshot: { schema_version: 1, effective: {}, provenance: {}, policy: {},
      config_digest: "c", snapshot_digest: "s", comparison_digest: "d" },
  };
  const trial = (key: string, state: string, result: unknown, reason: string | null) => ({
    id: `trl_${key}`, task_id: `tsk_${key}`, task_key: key, repetition_index: 1, state,
    phase: null, reason_code: reason, artifact_state: "complete", cleanup_state: "complete",
    result, attempts: [{ id: `att_${key}`, attempt_index: 1, state: "failed", phase: "executing",
      started_at: "2026-10-22T00:00:00Z", ended_at: "2026-10-22T00:00:01Z",
      error: { code: "AGENT_TIMEOUT", message: "agent timed out" } }],
  });
  const result = (score: number | null, cause: string | null) => ({
    raw_score: score, reward_valid: score !== null, score, failure_cause: cause,
    exception_type: null, verifier_status: "ok", policy_version: "p", attempt_id: "att",
  });
  const routes: Record<string, unknown> = {
    "/api/v1/setup": { needs_setup: false },
    "/api/v1/session": { user: me, csrf_token: "csrf" },
    "/api/v1/capabilities": { api_version: "v1", service_version: "t", schema_revision: "t",
      features: {}, limits: {}, auth: {}, actions: {} },
    "/api/v1/system-status": { status: "ready", accepting_runs: false,
      detail: { master_key_available: false, executor: null } },
    "/api/v1/runs/run_x": run,
    "/api/v1/runs/run_x/trials": [
      trial("zero", "scored", result(0, null), null),
      trial("unscored", "execution_error", result(null, "agent_timeout"), "AGENT_TIMEOUT"),
      trial("noresult", "execution_error", null, "SETUP_FAILED"),
    ],
    "/api/v1/runs/run_x/artifacts": [],
  };
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const data = routes[path];
    return data === undefined
      ? route.fulfill({ status: 404, json: { error: { code: "NOT_FOUND", message: path,
          field_errors: [], retryable: false, suggested_actions: [] }, meta } })
      : route.fulfill({ json: { data, meta } });
  });
  await page.goto("/runs/run_x");
  await expect(page.getByText("当前无法受理新运行")).toBeVisible();
  await expect(page.getByRole("link", { name: "管理" })).toHaveCount(0);
  const rows = page.getByTestId("trial-row");
  await expect(rows.nth(0).getByRole("cell").nth(4)).toHaveText("0");
  await expect(rows.nth(1).getByRole("cell").nth(4)).toContainText("未评分");
  await expect(rows.nth(1).getByRole("cell").nth(4)).toContainText("AGENT_TIMEOUT");
  await expect(rows.nth(2).getByRole("cell").nth(4)).toContainText("未评分");
  await expect(rows.nth(2).getByRole("cell").nth(4)).toContainText("SETUP_FAILED");
  await expect(page.getByText("保存失败")).toBeVisible();
  await expect(page.getByText("清理失败")).toBeVisible();
  await expect(page.getByText("部分评分")).toBeVisible();
  await expect(page.getByRole("button", { name: "取消运行" })).toHaveCount(0);
  await rows.nth(1).click();
  await expect(page.getByText("AGENT_TIMEOUT：agent timed out")).toBeVisible();
});

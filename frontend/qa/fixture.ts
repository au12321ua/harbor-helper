import { type Page } from "@playwright/test";
export const user = { id: "u1", username: "test-admin", role: "admin" };
export const run = {
  id: "hh-test-zero",
  submitter: "test-admin",
  status: "succeeded",
  created: 1791460000,
  audit_status: "clean",
  dataset: "team/test@1",
  model_profile: "plan1",
  concurrency: 1,
};
export const catalog = {
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
export async function fixture(page: Page, role = "admin", logged = true) {
  let authenticated = logged;
  const currentCatalog = structuredClone(catalog);
  let paused = false;
  let maintenanceReason = "";
  let stopMode = "none";
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
    if (path === "/access-capabilities")
      value = {
        scopes: ["read", "attachments", "execute", "cancel_own"],
        evidence_grant: false,
      };
    else if (path === "/setup") value = { initialized: true };
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
    else if (path === "/admin/shutdown") {
      if (request.method() === "POST") stopMode = body.mode;
      value = {
        maintenance: {
          paused,
          reason: maintenanceReason,
          retry_at: null,
          updated: null,
        },
        intent: {
          mode: stopMode,
          phase:
            stopMode === "none" || stopMode === "abort" ? "idle" : "draining",
          updated: null,
        },
        counts: {
          preparing: 1,
          queued: 1,
          starting: 0,
          running: 1,
          cancelling: 0,
          cleanup_blocked: 0,
          audit_incomplete: 0,
        },
      };
    } else if (path === "/admin/maintenance") {
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

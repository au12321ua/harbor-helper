import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import fs from "node:fs";
const evidence = process.env.HH_BROWSER_EVIDENCE;
const inputs = JSON.parse(fs.readFileSync(evidence + "/drain-inputs.json", "utf8"));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.goto(inputs.url);
  await page.getByLabel("账户").fill("fixture-member");
  await page.getByLabel("密码", { exact: true }).fill("Fixture-only-checker-password-2026");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  async function submitFromWeb() {
    await page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "新建实验", exact: true }).click();
    await page.getByLabel("数据集", { exact: true }).selectOption(inputs.dataset_id);
    await page.getByLabel("执行方案", { exact: true }).selectOption("oracle");
    await page.getByLabel("团队附件版本（可选）").selectOption("");
    await page.getByRole("button", { name: "清除附件，使用无附件基线" }).click();
    await page.locator("details summary").click();
    await page.locator("[name=attempts]").fill("1");
    await page.locator("[name=concurrency]").fill("1");
    await page.locator("[name=wall_seconds]").fill("120");
    const accepted = page.waitForResponse((r) => r.url().endsWith("/api/v1/submissions") && r.request().method() === "POST");
    await page.getByRole("button", { name: "提交实验", exact: true }).click();
    const response = await accepted;
    assert.equal(response.status(), 202);
    return { value: await response.json(), key: response.request().headers()["idempotency-key"] };
  }
  const first = await submitFromWeb();
  const firstId = first.value.id || first.value.submission_id;
  const firstKey = first.key;
  assert(firstId && firstKey);
  const deadline = Date.now() + 15000;
  let firstState;
  do {
    const r = await page.request.get(inputs.url + `/api/v1/machine/submissions/${firstId}`);
    assert.equal(r.status(), 200);
    firstState = await r.json();
    if (firstState.status === "queued" || firstState.resource.state === "active") break;
    assert(Date.now() < deadline, "first acceptance did not enter queue/worker in time");
    await page.waitForTimeout(100);
  } while (true);
  const second = await submitFromWeb();
  const secondId = second.value.id || second.value.submission_id;
  const secondBefore = await (await page.request.get(inputs.url + `/api/v1/machine/submissions/${secondId}`)).json();
  assert(["preparing", "queued"].includes(secondBefore.status), secondBefore.status);

  const admin = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await admin.goto(inputs.url);
  await admin.getByLabel("账户").fill("fixture-admin");
  await admin.getByLabel("密码", { exact: true }).fill("Fixture-only-checker-password-2026");
  await admin.getByRole("button", { name: "登录", exact: true }).click();
  await admin.getByRole("link", { name: "团队管理", exact: true }).click();
  await admin.getByRole("tab", { name: "容量与保留", exact: true }).click();
  await admin.getByLabel("维护原因").fill("accepted-drain fixture window");
  const pause = admin.waitForResponse((r) => r.url().endsWith("/api/v1/admin/maintenance") && r.request().method() === "PATCH");
  await admin.getByRole("button", { name: "暂停新受理", exact: true }).click();
  assert.equal((await pause).status(), 200);
  const readiness = await (await page.request.get(inputs.url + "/api/v1/readiness")).json();
  assert.equal(readiness.maintenance.paused, true);

  const oldLookup = await page.request.get(inputs.url + `/api/v1/submission-operations/submit/${encodeURIComponent(firstKey)}`);
  assert.equal(oldLookup.status(), 200);
  const oldAccepted = await oldLookup.json();
  assert.equal(oldAccepted.id, firstId);
  const secondCancel = await page.request.post(inputs.url + `/api/v1/submissions/${secondId}/cancel`, {
    headers: { "X-Requested-With": "harbor-helper" }, data: {},
  });
  assert.equal(secondCancel.status(), 200);
  // The sole fixture worker is deliberately occupied by the first accepted
  // run; cancellation becomes observable after that bounded 20s work drains.
  const cancelDeadline = Date.now() + 60000;
  let secondAfter;
  let cancelledRun;
  do {
    const r = await page.request.get(inputs.url + `/api/v1/machine/submissions/${secondId}`);
    assert.equal(r.status(), 200);
    secondAfter = await r.json();
    if (secondAfter.run_id) {
      const runResponse = await page.request.get(inputs.url + `/api/v1/runs/${secondAfter.run_id}`);
      assert.equal(runResponse.status(), 200);
      cancelledRun = await runResponse.json();
      if (cancelledRun.row.status === "cancelled") break;
    } else if (secondAfter.status === "cancelled") {
      break;
    }
    assert(Date.now() < cancelDeadline, "queued own cancellation did not reach terminal state");
    await page.waitForTimeout(100);
  } while (true);
  assert.equal(secondAfter.resource.state, "released");
  assert(["available", "unavailable"].includes(secondAfter.report.state));
  if (secondAfter.report.state === "available") assert(secondAfter.report_url);
  const rejected = await page.request.post(inputs.url + "/api/v1/submissions", {
    headers: { "X-Requested-With": "harbor-helper", "Idempotency-Key": "checker-paused-denial-20261012" },
    data: { dataset_id: inputs.dataset_id, agent: "oracle", attempts: 1, concurrency: 1, wall_seconds: 120 },
  });
  assert.equal(rejected.status(), 503);
  assert.equal((await rejected.json()).code, "maintenance_paused");

  const drainDeadline = Date.now() + 60000;
  let drained;
  do {
    const r = await page.request.get(inputs.url + `/api/v1/machine/submissions/${firstId}`);
    assert.equal(r.status(), 200);
    drained = await r.json();
    if (drained.report.state === "available") break;
    assert(Date.now() < drainDeadline, "already accepted run did not drain while maintenance was paused");
    await page.waitForTimeout(150);
  } while (true);
  const stillPaused = await (await page.request.get(inputs.url + "/api/v1/readiness")).json();
  assert.equal(stillPaused.maintenance.paused, true);
  const resume = admin.waitForResponse((r) => r.url().endsWith("/api/v1/admin/maintenance") && r.request().method() === "PATCH");
  await admin.getByRole("button", { name: "恢复新受理", exact: true }).click();
  assert.equal((await resume).status(), 200);
  const resumed = await (await page.request.get(inputs.url + "/api/v1/readiness")).json();
  assert.equal(resumed.maintenance.paused, false);
  const result = { first_submission: firstId, first_key_lookup_id: oldAccepted.id, drained_run_id: drained.run_id, drained_report: drained.report, second_submission: secondId, second_before_cancel: secondBefore.status, second_after_cancel: cancelledRun?.row.status ?? secondAfter.status, second_cancel_resource: secondAfter.resource, second_cancel_report: secondAfter.report, maintenance_denial: { status: rejected.status(), code: "maintenance_paused" }, paused_during_drain: stillPaused.maintenance.paused, resumed: resumed.maintenance.paused };
  fs.writeFileSync(evidence + "/maintenance-drain-result.json", JSON.stringify(result, null, 2) + "\n");
  console.log(JSON.stringify(result));
  await admin.close();
} finally {
  await browser.close();
}

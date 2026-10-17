import { test, expect, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import type { Catalog, Comparison, Manifest } from "../src/api";
import {
  fromManifest,
  fromParent,
  fromRequest,
  initialDraft,
  problems,
  submissionBody,
} from "../src/features/experiments/reuse";
import {
  comparisonCSV,
  comparisonJSON,
} from "../src/features/experiments/comparisonExport";
const catalog = {
  datasets: [
    {
      id: "ds",
      enabled: true,
      ready: true,
      name: "目录",
      reference: "team/data@1",
      version: 2,
      tasks: [{ name: "题目" }],
      author_parameters: {},
    },
  ],
  settings: { default_dataset_id: "ds", default_model_profile: "model" },
  model_profiles: [
    {
      id: "model",
      enabled: true,
      provider_id: "p",
      credential_id: "k",
      model: "fixture",
    },
  ],
  providers: [{ id: "p", enabled: true }],
  credentials: [{ id: "k", enabled: true }],
  attachments: [
    {
      id: "a",
      name: "附件",
      enabled: true,
      versions: [
        { id: "v1", number: 1, enabled: true, availability: "available" },
      ],
    },
  ],
  limits: { max_attempts: 3, max_trials: 2, max_wall_seconds: 1800 },
} as unknown as Catalog;
const manifest = {
  effective: {
    agent: "opencode",
    dataset: "team/data@1",
    task_filter: "题目",
    attempts: 2,
    concurrency: 1,
    wall_seconds: 700,
    environment_build_timeout_multiplier: 7,
  },
  service: {
    name: "原名",
    dataset_id: "ds",
    dataset_version: 1,
    model_profile: "model",
    attachment_version_id: "v1",
  },
} as Manifest;
const row = {
  id: "run-a",
  status: "succeeded",
  audit_status: "clean",
  submitter: "alice",
  dataset: "team/data@1",
  name: "原名",
  created: 1,
  concurrency: 1,
};
const comparison = {
  left: "run-a",
  right: "run-b",
  comparable: false,
  reasons: ["配置不同"],
  config_changes: { name: { left: '中文,"\n', right: "B" } },
  environment_observations: { observed: "unknown" },
  attachment_inputs: {},
  bundle_change: {},
  mean_task_delta: { reward: 99 },
  tasks: [
    { task: "空任务", left: {}, right: {}, delta: {} },
    {
      task: ' \t=危险,"\n任务',
      left: {
        zero: 0,
        negative: -2.3456789012345,
        nullable: null,
        unknown: "unknown",
        precise: 0.123456789012345,
      },
      right: { zero: -1, missing: 5 },
      delta: { zero: -1 },
    },
  ],
} as unknown as Comparison;
function csvRows(csv: string) {
  const rows: string[][] = [];
  let row: string[] = [],
    field = "",
    quoted = false;
  csv = csv.replace(/^\uFEFF/, "");
  for (let i = 0; i < csv.length; i++) {
    const c = csv[i];
    if (c === '"') {
      if (quoted && csv[i + 1] === '"') {
        field += '"';
        i++;
      } else quoted = !quoted;
    } else if (c === "," && !quoted) {
      row.push(field);
      field = "";
    } else if (c === "\r" && csv[i + 1] === "\n" && !quoted) {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
      i++;
    } else field += c;
  }
  return rows
    .slice(1)
    .map((r) => Object.fromEntries(rows[0].map((k, i) => [k, r[i]])));
}
test("pure projection matrix: run operations, parent wall, request intent, oracle, CLI, partial preset", () => {
  for (const operation of ["submit", "rerun", "retry", "recover"]) {
    const v = fromManifest({ ...manifest, parent: operation }, operation);
    expect(v.values.name).toBe("原名 · 副本");
    expect(problems(v.values, catalog)).toEqual({});
    expect(submissionBody(v.values)).toMatchObject({
      dataset_id: "ds",
      task: "题目",
      model_profile: "model",
      attachment_version_id: "v1",
      attempts: 2,
      concurrency: 1,
      wall_seconds: 700,
      environment_build_timeout_multiplier: 7,
    });
  }
  expect(
    fromParent(
      manifest,
      { wall_seconds: 900, dataset_id: "wrong", name: "wrong" },
      "s",
    ).values,
  ).toMatchObject({ wall_seconds: 900, dataset_id: "ds", name: "原名" });
  for (const wall_seconds of [undefined, null, 0, -1, NaN])
    expect(
      fromParent(manifest, { wall_seconds }, "s").values.wall_seconds,
    ).toBe(700);
  expect(
    fromRequest({ name: "失败", agent: "oracle" }, "s").values,
  ).toMatchObject({
    name: "失败",
    task: "",
    attachment_version_id: "",
    dataset_id: undefined,
    attempts: undefined,
  });
  const oracle = {
    ...fromManifest(manifest, "s").values,
    agent: "oracle",
    model_profile: undefined,
    task: "",
    attachment_version_id: "",
  };
  expect(problems(oracle, catalog)).toEqual({});
  expect(submissionBody(oracle)).toMatchObject({
    model_profile: null,
    task: null,
    attachment_version_id: null,
  });
  expect(
    initialDraft(catalog, { kind: "attachment", version: "v1" }),
  ).toMatchObject({
    dataset_id: "ds",
    model_profile: "model",
    attachment_version_id: "v1",
    attempts: 1,
  });
  expect(
    fromManifest({ ...manifest, service: { name: "a".repeat(128) } }, "s")
      .values.name,
  ).toHaveLength(128);
  expect(
    fromManifest({ ...manifest, service: null }, "cli").values.dataset_id,
  ).toBe("引用：team/data@1");
});
test("pure invalid fields and unknowns remain unchanged, dependent availability checked", () => {
  const good = fromManifest(manifest, "s").values;
  for (const [field, bad] of Object.entries({
    dataset_id: "removed",
    task: "*pattern*",
    agent: "other",
    model_profile: "removed",
    attachment_version_id: "removed",
    attempts: 0,
    concurrency: 3,
    wall_seconds: 1801,
    environment_build_timeout_multiplier: "bad",
    name: "x".repeat(129),
  })) {
    const d = { ...good, [field]: bad };
    expect(problems(d, catalog)[field as keyof typeof good]).toBeTruthy();
    expect(d[field as keyof typeof good]).toBe(bad);
  }
  for (const field of [
    "dataset_id",
    "task",
    "agent",
    "model_profile",
    "attachment_version_id",
    "attempts",
    "concurrency",
    "wall_seconds",
    "environment_build_timeout_multiplier",
  ] as const)
    expect(
      problems({ ...good, [field]: undefined }, catalog)[field],
    ).toBeTruthy();
  for (const n of [null, "", {}, -1, 0, 1.1, Infinity])
    expect(problems({ ...good, attempts: n }, catalog).attempts).toBeTruthy();
  for (const c of [
    { ...catalog, providers: [] },
    { ...catalog, credentials: [] },
    {
      ...catalog,
      model_profiles: [{ ...catalog.model_profiles[0], enabled: false }],
    },
  ])
    expect(problems(good, c).model_profile).toBeTruthy();
});
test("pure serializers preserve raw comparison, typed metric states, precision, CSV quoting/formula defense", () => {
  expect(JSON.parse(comparisonJSON(comparison, "at"))).toEqual({
    format_version: 1,
    exported_at: "at",
    comparison,
  });
  const rows = csvRows(comparisonCSV(comparison, "at"));
  expect(rows.find((r) => r.task === "空任务")?.record).toBe(
    "no_valid_metrics",
  );
  expect(rows.find((r) => r.metric === "negative")).toMatchObject({
    left_type: "number",
    left_value: "-2.3456789012345",
    right_type: "missing",
    delta_type: "incomparable",
    delta_value: "",
  });
  expect(rows.find((r) => r.metric === "nullable")).toMatchObject({
    left_type: "null",
    left_value: "null",
  });
  expect(rows.find((r) => r.metric === "unknown")).toMatchObject({
    left_type: "string",
    left_value: "unknown",
  });
  expect(rows.find((r) => r.metric === "zero")?.left_value).toBe("0");
  expect(rows.find((r) => r.metric === "precise")?.left_value).toBe(
    "0.123456789012345",
  );
  expect(rows.find((r) => r.metric === "zero")?.task).toBe(
    "'" + comparison.tasks[1].task,
  );
  expect(rows.some((r) => r.record === "mean_task_delta")).toBe(false);
  const yes = csvRows(comparisonCSV({ ...comparison, comparable: true }, "at"));
  expect(yes.find((r) => r.metric === "zero")?.delta_value).toBe("-1");
  expect(yes.find((r) => r.record === "mean_task_delta")?.delta_value).toBe(
    "99",
  );
  expect(
    csvRows(comparisonCSV({ ...comparison, tasks: [] }, "at")),
  ).toHaveLength(1);
});
async function fixture(page: Page, source = manifest) {
  const writes: { body: unknown; key: string | undefined }[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname.replace("/api/v1", "");
    let json: unknown = {};
    if (path === "/setup") json = { initialized: true };
    else if (path === "/me") json = { username: "alice", role: "member" };
    else if (path === "/readiness")
      json = {
        accepting: true,
        scheduler: { state: "ready" },
        maintenance: { paused: false },
        pending: { global_pending: 0, member_pending: 0 },
      };
    else if (path === "/attachments")
      json = { attachments: catalog.attachments };
    else if (path === "/catalog") json = catalog;
    else if (path === "/runs")
      json = { runs: [row, { ...row, id: "run-b" }, { ...row, id: "run-c" }] };
    else if (path === "/runs/run-a")
      json = { row, manifest: source, report: null, artifacts: [] };
    else if (path === "/compare") json = comparison;
    else if (path === "/submissions" && req.method() === "POST") {
      writes.push({
        body: req.postDataJSON(),
        key: req.headers()["idempotency-key"],
      });
      await route.abort("failed");
      return;
    } else if (path.startsWith("/submissions/"))
      json = {
        id: "sub-failed",
        status: "failed",
        parent: "run-a",
        request: { wall_seconds: 900, model_profile: "wrong" },
      };
    await route.fulfill({ json });
  });
  return writes;
}
async function copy(page: Page) {
  await page.goto("/runs/run-a");
  await page.getByRole("link", { name: "复制配置新建" }).click();
}
test("browser copy uses manifest, same-key communication retry, edit changes key", async ({
  page,
}) => {
  const writes = await fixture(page);
  await copy(page);
  expect(writes).toHaveLength(0);
  await expect(page.getByLabel("实验名称（可选）")).toHaveValue("原名 · 副本");
  await expect(page.getByText(/来源数据集版本 1，当前版本 2/)).toBeVisible();
  await page.getByLabel("每任务尝试次数").fill("3");
  const submit = page.getByRole("button", { name: "提交实验", exact: true });
  await submit.click();
  await expect(page.getByText("操作未完成")).toBeVisible();
  await submit.click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[0].key).toBe(writes[1].key);
  expect(writes[0].body).toEqual(
    submissionBody({ ...fromManifest(manifest, "s").values, attempts: 3 }),
  );
  await page.getByLabel("每任务尝试次数").fill("2");
  await submit.click();
  await expect.poll(() => writes.length).toBe(3);
  expect(writes[2].key).not.toBe(writes[0].key);
  await page.screenshot({
    path: test.info().outputPath("reuse-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: test.info().outputPath("reuse-mobile.png"),
    fullPage: true,
  });
});
test("browser retains invalid task, attachment, zero and excess without silent fallback", async ({
  page,
}) => {
  const bad = structuredClone(manifest);
  bad.effective.task_filter = "*old*";
  bad.effective.attempts = 0;
  bad.effective.wall_seconds = 9999;
  bad.service!.attachment_version_id = "old-version";
  const writes = await fixture(page, bad);
  await copy(page);
  await expect(page.getByLabel("任务", { exact: true })).toHaveValue("*old*");
  await expect(page.getByLabel("团队附件版本（可选）")).toHaveValue(
    "old-version",
  );
  await expect(page.getByLabel("每任务尝试次数")).toHaveValue("0");
  await expect(page.getByLabel("实验总时长上限（秒，含准备）")).toHaveValue(
    "9999",
  );
  const submit = page.getByRole("button", { name: "提交实验", exact: true });
  await expect(submit).toBeDisabled();
  expect(writes).toHaveLength(0);
  await page.getByLabel("每任务尝试次数").fill("1");
  await page.getByLabel("实验总时长上限（秒，含准备）").fill("600");
  await page.getByRole("button", { name: "清除附件，使用无附件基线" }).click();
  await expect(submit).toBeDisabled();
  await page.getByLabel("任务", { exact: true }).selectOption("");
  await submit.click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body).toMatchObject({
    task: null,
    attachment_version_id: null,
    attempts: 1,
    wall_seconds: 600,
  });
});
test("browser parent failure takes manifest and wall; failed parent read never opens defaults", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/submissions/sub-failed");
  await page.getByRole("button", { name: "修改输入后新提交" }).click();
  await expect(page.getByLabel("实验名称（可选）")).toHaveValue("原名");
  await expect(page.getByLabel("模型方案", { exact: true })).toHaveValue(
    "model",
  );
  await expect(page.getByLabel("实验总时长上限（秒，含准备）")).toHaveValue(
    "900",
  );
  await page.route("**/api/v1/runs/run-a", (r) =>
    r.fulfill({ status: 404, json: { message: "parent missing" } }),
  );
  await page.goto("/submissions/sub-failed");
  await page.getByRole("button", { name: "修改输入后新提交" }).click();
  await expect(page.getByText(/恢复失败，未打开副本/)).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/submissions/sub-failed");
});
test("browser actual JSON/CSV bytes and old/late/failed comparison guards", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/compare?left=run-a&right=run-b");
  await page.getByRole("button", { name: "开始对比" }).click();
  for (const format of ["JSON", "CSV"] as const) {
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name: `下载 ${format}` }).click();
    const d = await pending;
    const content = await readFile((await d.path())!, "utf8");
    await d.saveAs(test.info().outputPath(d.suggestedFilename()));
    if (format === "JSON")
      expect(JSON.parse(content)).toEqual({
        format_version: 1,
        exported_at: expect.any(String),
        comparison,
      });
    else {
      const rows = csvRows(content);
      expect(content).toBe(comparisonCSV(comparison, rows[0].exported_at));
      expect(rows.find((r) => r.task === "空任务")).toBeTruthy();
      expect(
        rows
          .filter((r) => r.record === "task")
          .every((r) => r.delta_value === ""),
      ).toBe(true);
    }
  }
  await page.getByLabel("实验 B", { exact: true }).selectOption("run-c");
  await expect(page.getByRole("button", { name: "下载 JSON" })).toHaveCount(0);
  let release!: () => void;
  const held = new Promise<void>((r) => (release = r));
  await page.route("**/api/v1/compare", async (r) => {
    await held;
    await r.fulfill({ json: comparison });
  });
  await page.getByRole("button", { name: "开始对比" }).click();
  await expect(page.getByRole("button", { name: "下载 CSV" })).toHaveCount(0);
  await page.getByLabel("实验 B", { exact: true }).selectOption("run-b");
  release();
  await expect(page.getByRole("button", { name: "下载 JSON" })).toHaveCount(0);
  await page.route("**/api/v1/compare", (r) =>
    r.fulfill({ status: 500, json: { message: "failed" } }),
  );
  await page.getByRole("button", { name: "开始对比" }).click();
  await expect(page.getByText("操作未完成")).toBeVisible();
  await expect(page.getByRole("button", { name: "下载 CSV" })).toHaveCount(0);
});

test("same-route new intent, attachment partial preset and repeated history never retain previous draft", async ({
  page,
}) => {
  const writes = await fixture(page);
  await copy(page);
  await page.getByLabel("每任务尝试次数").fill("3");
  await page.getByRole("link", { name: "新建实验", exact: true }).click();
  await expect(page.getByLabel("每任务尝试次数")).toHaveValue("1");
  await expect(page.getByLabel("实验名称（可选）")).toHaveValue("");
  await expect(page.getByLabel("团队附件版本（可选）")).toHaveValue("");
  await page.getByRole("link", { name: "团队附件", exact: true }).click();
  await page.getByRole("link", { name: "使用 v1 新建实验" }).click();
  await expect(page.getByLabel("数据集", { exact: true })).toHaveValue("ds");
  await expect(page.getByLabel("模型方案", { exact: true })).toHaveValue(
    "model",
  );
  await expect(page.getByLabel("团队附件版本（可选）")).toHaveValue("v1");
  await expect(
    page.getByLabel("环境启动等待倍数", { exact: true }),
  ).toHaveValue("10");
  await copy(page);
  await expect(page.getByLabel("每任务尝试次数")).toHaveValue("2");
  await expect(
    page.getByLabel("环境启动等待倍数", { exact: true }),
  ).toHaveValue("7");
  expect(writes).toHaveLength(0);
});

test("unavailable dataset and model never fall back to defaults; changing dataset requires task confirmation", async ({
  page,
}) => {
  const bad = structuredClone(manifest);
  bad.service!.dataset_id = "removed-dataset";
  bad.service!.model_profile = "removed-model";
  const writes = await fixture(page, bad);
  await copy(page);
  await expect(page.getByLabel("数据集", { exact: true })).toHaveValue(
    "removed-dataset",
  );
  await expect(page.getByLabel("模型方案", { exact: true })).toHaveValue(
    "removed-model",
  );
  const submit = page.getByRole("button", { name: "提交实验", exact: true });
  await expect(submit).toBeDisabled();
  await page.getByLabel("数据集", { exact: true }).selectOption("ds");
  await page.getByLabel("模型方案", { exact: true }).selectOption("model");
  await expect(page.getByLabel("任务", { exact: true })).toHaveValue(
    "__unknown__",
  );
  await expect(submit).toBeDisabled();
  await page.getByLabel("任务", { exact: true }).selectOption("题目");
  await submit.click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body).toMatchObject({
    dataset_id: "ds",
    model_profile: "model",
    task: "题目",
  });
});

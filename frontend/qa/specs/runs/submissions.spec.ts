import { test, fixture, catalog, run } from "../../support/fixture";
import { expect } from "@playwright/test";
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

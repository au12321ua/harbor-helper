import { test } from "../../support/fixture";
import { expect, type Page } from "@playwright/test";
import { fixture, catalog } from "../../support/fixture";

function datasetCard(page: Page, n = 1) {
  return page
    .locator('[data-slot="card"]')
    .filter({ has: page.getByText(`数据集${n}`, { exact: true }) });
}
async function setup(page: Page) {
  await fixture(page);
  const c: any = structuredClone(catalog);
  c.settings.team_name = "saved-team";
  c.datasets = [1, 2].map((n) => ({
    ...c.datasets[0],
    id: `dataset${n}`,
    name: `数据集${n}`,
    enabled: true,
    status: "verified",
    author_parameters: {
      id: `dataset${n}`,
      version: 1,
      status: "checked",
      values: { VAR_0: "saved", REMOVE: "remove-saved" },
      discovery: {
        variables: { VAR_0: [], REMOVE: [] },
        budgets: [],
        images: [],
      },
    },
  }));
  const writes: { path: string; body: any }[] = [];
  let catalogs = 0;
  await page.route("**/api/v1/catalog", (route) => {
    catalogs++;
    return route.fulfill({ json: c });
  });
  await page.route(
    "**/api/v1/admin/datasets/*/author-inputs",
    async (route) => {
      const path = new URL(route.request().url()).pathname;
      const body = route.request().postDataJSON();
      writes.push({ path, body });
      const d = c.datasets.find((d: any) => path.includes(`/${d.id}/`));
      d.author_parameters.values = Object.fromEntries(
        Object.entries(body.values).map(([k, v]) => [k, String(v).trim()]),
      );
      d.author_parameters.version++;
      await route.fulfill({ json: d.author_parameters });
    },
  );
  await page.route("**/api/v1/admin/catalog/dataset", async (route) => {
    const body = route.request().postDataJSON();
    writes.push({ path: "/admin/catalog/dataset", body });
    Object.assign(
      c.datasets.find((d: any) => d.id === body.id),
      body,
    );
    await route.fulfill({
      json: c.datasets.find((d: any) => d.id === body.id),
    });
  });
  await page.goto("/admin?section=dataset");
  await expect(
    datasetCard(page).getByLabel("VAR_0", { exact: true }),
  ).toHaveValue("saved");
  const refresh = async () => {
    const count = catalogs;
    await datasetCard(page)
      .getByRole("button", { name: "刷新最近已保存结果" })
      .click();
    await expect.poll(() => catalogs).toBeGreaterThan(count);
    // The observable version in details proves this catalog render completed.
    await expect(
      datasetCard(page).getByText(
        `配置修订：${c.datasets[0].version} · 参数修订：${c.datasets[0].author_parameters.version}`,
        { exact: true },
      ),
    ).toHaveCount(1);
  };
  return { c, writes, refresh };
}

for (const kind of ["author", "source"] as const)
  test(`F1 ${kind} dirty state ends with the actual tab-mounted draft`, async ({
    page,
  }) => {
    const { c, refresh } = await setup(page);
    if (kind === "source")
      await datasetCard(page)
        .getByRole("button", { name: "编辑", exact: true })
        .click();
    const input =
      kind === "author"
        ? datasetCard(page).getByLabel("VAR_0", { exact: true })
        : page.getByLabel("Hub 来源（owner/name，可指定版本）", {
            exact: true,
          });
    const saved = kind === "author" ? "saved" : c.datasets[0].reference;
    await input.fill("unsaved-draft");
    await expect(
      datasetCard(page).getByRole("button", { name: "验证", exact: true }),
    ).toBeDisabled();
    await page.getByRole("tab", { name: "受邀账户", exact: true }).click();
    await page.getByRole("tab", { name: "数据集", exact: true }).click();
    await expect(input).toHaveValue(saved);
    await expect(
      datasetCard(page).getByRole("button", { name: "放弃此数据集草稿" }),
    ).toHaveCount(0);
    await expect(
      datasetCard(page).getByRole("button", {
        name: "检查作者参数",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      datasetCard(page).getByRole("button", { name: "验证", exact: true }),
    ).toBeEnabled();
    c.datasets[0].author_parameters.version++;
    await refresh();
    await expect(
      datasetCard(page).getByRole("button", { name: "验证", exact: true }),
    ).toBeEnabled();
  });

test("F2 clean author inputs follow saved catalog values and submit the refreshed values", async ({
  page,
}) => {
  const { c, writes, refresh } = await setup(page);
  const input = datasetCard(page).getByLabel("VAR_0", { exact: true });
  await input.evaluate((el) => el.setAttribute("data-same-input", "yes"));
  c.datasets[0].author_parameters.values.VAR_0 = "external-v2";
  c.datasets[0].author_parameters.version++;
  await refresh();
  await expect(input).toHaveValue("external-v2");
  await expect(input).toHaveAttribute("data-same-input", "yes");
  await expect(
    datasetCard(page).getByRole("button", { name: "放弃此数据集草稿" }),
  ).toHaveCount(0);
  await datasetCard(page)
    .getByRole("button", { name: "保存", exact: true })
    .click();
  await expect
    .poll(() => writes[0]?.body.values)
    .toEqual({ VAR_0: "external-v2", REMOVE: "remove-saved" });
  await expect(input).toHaveValue("external-v2");
});

test("dirty author refresh reconciles field additions/removals, preserves actual edits, and normalizes own save", async ({
  page,
}) => {
  const { c, writes, refresh } = await setup(page);
  const first = datasetCard(page),
    input = first.getByLabel("VAR_0", { exact: true });
  await input.fill("  real draft  ");
  const p = c.datasets[0].author_parameters;
  p.values = { VAR_0: "external-v2", NEW: "new-saved" };
  delete p.discovery.variables.REMOVE;
  p.discovery.variables.NEW = [];
  p.version++;
  await refresh();
  await expect(input).toHaveValue("  real draft  ");
  await expect(first.getByLabel("REMOVE", { exact: true })).toHaveCount(0);
  await expect(first.getByLabel("NEW", { exact: true })).toHaveValue(
    "new-saved",
  );
  await expect(
    first.getByRole("button", { name: "验证", exact: true }),
  ).toBeDisabled();
  await first.getByRole("button", { name: "保存", exact: true }).click();
  await expect
    .poll(() => writes[0]?.body.values)
    .toEqual({ VAR_0: "  real draft  ", NEW: "new-saved" });
  await expect(input).toHaveValue("real draft");
  await expect(
    first.getByRole("button", { name: "验证", exact: true }),
  ).toBeEnabled();
  await input.fill("another draft");
  await refresh();
  await expect(input).toHaveValue("another draft");
  await input.fill("real draft");
  await expect(
    first.getByRole("button", { name: "验证", exact: true }),
  ).toBeEnabled();
});

test("clean schema changes use saved new fields and cannot submit removed fields", async ({
  page,
}) => {
  const { c, writes, refresh } = await setup(page);
  const p = c.datasets[0].author_parameters;
  p.values = { NEW: "new-saved" };
  p.discovery.variables = { NEW: [] };
  p.version++;
  await refresh();
  await expect(
    datasetCard(page).getByLabel("VAR_0", { exact: true }),
  ).toHaveCount(0);
  await expect(
    datasetCard(page).getByLabel("NEW", { exact: true }),
  ).toHaveValue("new-saved");
  await expect(
    datasetCard(page).getByRole("button", { name: "验证", exact: true }),
  ).toBeEnabled();
  await datasetCard(page)
    .getByRole("button", { name: "保存", exact: true })
    .click();
  await expect.poll(() => writes[0]?.body.values).toEqual({ NEW: "new-saved" });
});

test("source editor takes clean catalog updates and preserves edits through another dataset save", async ({
  page,
}) => {
  const { c, writes } = await setup(page);
  await datasetCard(page)
    .getByRole("button", { name: "编辑", exact: true })
    .click();
  const source = page.getByLabel("Hub 来源（owner/name，可指定版本）", {
    exact: true,
  });
  c.datasets[0].reference = "team/external@2";
  await datasetCard(page, 2)
    .getByLabel("VAR_0", { exact: true })
    .fill("other change");
  await datasetCard(page, 2)
    .getByRole("button", { name: "保存", exact: true })
    .click();
  await expect(source).toHaveValue("team/external@2");
  await expect(
    datasetCard(page).getByRole("button", { name: "验证", exact: true }),
  ).toBeEnabled();
  await source.fill("team/my-draft@3");
  c.datasets[0].reference = "team/external@4";
  await datasetCard(page, 2)
    .getByLabel("VAR_0", { exact: true })
    .fill("other change 2");
  await datasetCard(page, 2)
    .getByRole("button", { name: "保存", exact: true })
    .click();
  await expect(source).toHaveValue("team/my-draft@3");
  await expect(
    datasetCard(page).getByRole("button", { name: "验证", exact: true }),
  ).toBeDisabled();
  await page
    .locator("form")
    .filter({ has: source })
    .getByRole("button", { name: "保存", exact: true })
    .click();
  await expect
    .poll(
      () =>
        writes.find((w) => w.path === "/admin/catalog/dataset")?.body.reference,
    )
    .toBe("team/my-draft@3");
});

test("removing the only edited field clears its blocker and re-adding it uses saved defaults", async ({
  page,
}) => {
  const { c, refresh } = await setup(page),
    first = datasetCard(page);
  await first.getByLabel("REMOVE", { exact: true }).fill("removed-draft");
  delete c.datasets[0].author_parameters.discovery.variables.REMOVE;
  c.datasets[0].author_parameters.version++;
  await refresh();
  await expect(
    first.getByRole("button", { name: "放弃此数据集草稿" }),
  ).toHaveCount(0);
  await expect(
    first.getByRole("button", { name: "检查作者参数", exact: true }),
  ).toBeEnabled();
  c.datasets[0].author_parameters.discovery.variables.REMOVE = [];
  c.datasets[0].author_parameters.values.REMOVE = "readded-saved";
  c.datasets[0].author_parameters.version++;
  await refresh();
  await expect(first.getByLabel("REMOVE", { exact: true })).toHaveValue(
    "readded-saved",
  );
  await expect(
    first.getByRole("button", { name: "验证", exact: true }),
  ).toBeEnabled();
});

for (const section of ["readiness", "models", "limits"] as const)
  for (const dirty of [false, true]) {
    test(`${section} ${dirty ? "dirty" : "clean"} mounted form reconciles catalog from long-check completion and submits actual displayed values`, async ({
      page,
    }) => {
      const { c } = await setup(page);
      let release!: () => void;
      await page.route(
        "**/api/v1/admin/datasets/dataset1/author-inputs/check",
        async (route) => {
          await new Promise<void>((resolve) => (release = resolve));
          await route.fulfill({ json: c.datasets[0].author_parameters });
        },
      );
      await datasetCard(page)
        .getByRole("button", { name: "检查作者参数", exact: true })
        .click();
      const spec = {
        readiness: {
          tab: "就绪与来源",
          label: "名称",
          path: "/admin/settings",
          field: "team_name",
          saved: "external-team",
          draft: "draft-team",
        },
        models: {
          tab: "模型与 key",
          label: "方案名称",
          path: "/admin/model-profiles",
          field: "name",
          saved: "external-model",
          draft: "draft-model",
        },
        limits: {
          tab: "容量与保留",
          label: "全局任务并发",
          path: "/admin/limits",
          field: "max_jobs",
          saved: "3",
          draft: "2",
        },
      }[section];
      await page.getByRole("tab", { name: spec.tab, exact: true }).click();
      if (section === "models")
        await page
          .getByRole("button", { name: "编辑方案", exact: true })
          .click();
      const input = page.getByLabel(spec.label, { exact: true });
      await input.evaluate((el) => el.setAttribute("data-same-input", "yes"));
      if (dirty) await input.fill(spec.draft);
      if (section === "readiness") {
        c.settings.team_name = spec.saved;
        c.datasets[1].ready = false;
      }
      if (section === "models") {
        c.model_profiles[0].name = spec.saved;
        c.model_profiles[0].params = { temperature: 0.25 };
      }
      if (section === "limits") {
        c.limits.max_jobs = Number(spec.saved);
        c.limits.max_trials = 4;
      }
      release();
      if (section === "readiness")
        await expect(page.getByText(/已验证可选数据集：/)).toContainText("1");
      if (section === "models")
        await expect(
          page.getByLabel("Temperature（可选）", { exact: true }),
        ).toHaveValue("0.25");
      if (section === "limits")
        await expect(
          page.getByLabel("全局 Trial 并发", { exact: true }),
        ).toHaveValue("4");
      await expect(input).toHaveValue(dirty ? spec.draft : spec.saved);
      await expect(input).toHaveAttribute("data-same-input", "yes");
      let submitted: any;
      await page.route(`**/api/v1${spec.path}`, async (route) => {
        submitted = route.request().postDataJSON();
        if (section === "models") Object.assign(c.model_profiles[0], submitted);
        else
          Object.assign(
            section === "limits" ? c.limits : c.settings,
            submitted,
          );
        await route.fulfill({
          json:
            section === "models"
              ? c.model_profiles[0]
              : section === "limits"
                ? c.limits
                : c.settings,
        });
      });
      await page
        .locator("form")
        .filter({ has: input })
        .getByRole("button", { name: "保存", exact: true })
        .click();
      await expect
        .poll(() => String(submitted?.[spec.field]))
        .toBe(dirty ? spec.draft : spec.saved);
    });
  }

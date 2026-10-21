import { test, fixture } from "../../support/fixture";
import { expect } from "@playwright/test";
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

import { test, fixture } from "../../support/fixture";
import { expect } from "@playwright/test";
test("历史分离受理准备重试，服务端筛选分页与降级", async ({page}) => {
  await fixture(page);
  const queries: string[] = [];
  await page.route("**/api/v1/operations?**", async route => {
    const url = new URL(route.request().url()); queries.push(url.search);
    await route.fulfill({json:{operations:[{id:"op-accepted",user_id:"u1",username:"真实用户名",operation:"submit",idem:"same",request:{},created:1700000000,updated:1700000010,attempts:3,status:"accepted",result:{id:"sub-1",status:"failed",error:{message:"准备输入不可用"}},error:null,recent:[{error:{code:"idempotency_conflict"}}],summarized_attempts:2},{id:"op-deleted-user",user_id:"deleted-account-123",username:null,operation:"attachment_create",idem:"other",request:{},created:1,updated:1,attempts:1,status:"rejected",result:null,error:{code:"queue_full"},recent:[],summarized_attempts:0}],total:52,offset:Number(url.searchParams.get("offset")),next_offset:url.searchParams.get("offset")==="0"?50:null,attempt_limit:32}});
  });
  await page.goto("/operations");
  await expect(page.locator("article").getByText("已受理",{exact:true})).toBeVisible();
  await expect(page.getByText("提交准备：准备失败",{exact:false})).toBeVisible();
  await expect(page.getByText("最近一次重试被拒",{exact:false})).toBeVisible();
  await expect(page.getByText("真实用户名",{exact:false})).toBeVisible();
  await expect(page.getByText("用户 deleted-",{exact:false})).toBeVisible();
  await expect(page.locator("pre").first()).not.toBeVisible();
  await page.getByRole("button",{name:"下一页"}).click();
  await expect.poll(() => queries.at(-1)).toContain("offset=50");
  await page.getByLabel("受理结果",{exact:true}).selectOption("accepted");
  await expect.poll(() => queries.at(-1)).toContain("status=accepted");
  expect(queries.at(-1)).toContain("offset=0");
  await page.getByLabel("操作",{exact:true}).selectOption("submit");
  await expect.poll(() => queries.at(-1)).toContain("operation=submit");
  await page.getByLabel("仅本人").check();
  await expect.poll(() => queries.at(-1)).toContain("mine=true");
  await page.screenshot({path:test.info().outputPath("history.png"),fullPage:true});
});

test("资料只查询清单，单击单次打包、禁用与保存", async ({page}) => {
  await fixture(page);
  let packages = 0;
  await page.route("**/api/v1/runs/hh-test-zero/evidence", route => route.fulfill({json:{state:"available",files:[{id:"a",name:"hidden-file",status:"original"},{id:"b",name:"missing-file",status:"missing"}]}}));
  await page.route("**/api/v1/runs/hh-test-zero/evidence/package", async route => { packages++; await new Promise(r=>setTimeout(r,300)); await route.fulfill({contentType:"application/zip",body:Buffer.from("UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA==","base64")}); });
  await page.goto("/runs/hh-test-zero"); await page.getByRole("tab",{name:"完整资料"}).click();
  await expect(page.getByText("可打包 1 个文件；1 个已删除",{exact:false})).toBeVisible();
  expect(packages).toBe(0); await expect(page.getByText("hidden-file")).toHaveCount(0);
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button",{name:"下载完整资料包",exact:true}).click();
  await expect(page.getByRole("button",{name:"正在准备并下载…"})).toBeDisabled();
  expect((await downloaded).suggestedFilename()).toBe("hh-test-zero-materials.zip");
  expect(packages).toBe(1); await expect(page.getByText("资料包已交给浏览器保存。")).toBeVisible();
  await page.screenshot({path:test.info().outputPath("materials-download.png")});
});

for (const [code, status, text] of [["evidence_snapshot_busy",503,"资料包准备超时"],["audit_incomplete",409,"证据审计未完成或异常"],["evidence_changed",409,"资料已变化"],["evidence_grant_required",403,"未获得完整资料权限"],["login_required",401,"登录已过期"],["unknown_failure",500,"fixture failure"]] as const) {
  test(`资料下载错误留在页面 ${code}`, async ({page}) => {
    await fixture(page);
    await page.route("**/api/v1/runs/hh-test-zero/evidence",route=>route.fulfill({json:{state:"available",files:[]}}));
    await page.route("**/api/v1/runs/hh-test-zero/evidence/package",route=>route.fulfill({status,json:{code,message:"fixture failure",request_id:"request-proof"}}));
    await page.goto("/runs/hh-test-zero"); await page.getByRole("tab",{name:"完整资料"}).click();
    await page.getByRole("button",{name:"下载完整资料包",exact:true}).click();
    await expect(page.getByText(text,{exact:false})).toBeVisible();
    await expect(page.getByText("请求编号：request-proof")).toBeVisible();
    await expect(page.getByRole("button",{name:"下载完整资料包",exact:true})).toBeEnabled();
    await expect(page).toHaveURL(/runs\/hh-test-zero$/);
  });
}

for (const state of ["in_progress","expired"]) test(`资料状态 ${state}`,async ({page}) => {
  await fixture(page); await page.route("**/api/v1/runs/hh-test-zero/evidence",route=>route.fulfill({json:{state,files:[]}}));
  await page.goto("/runs/hh-test-zero"); await page.getByRole("tab",{name:"完整资料"}).click();
  await expect(page.getByRole("button",{name:"下载完整资料包",exact:true})).toBeDisabled();
  await expect(page.getByText(state==="expired"?"已过期，无法恢复":"运行中，结束且审计完成后提供",{exact:false})).toBeVisible();
});

test("历史加载、空、失败与筛选旧响应隔离", async ({page}) => {
  await fixture(page);
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let first = true;
  await page.route("**/api/v1/operations?**", async route => {
    if (first) { first = false; await held; await route.fulfill({json:{operations:[{id:"stale",user_id:"old",operation:"submit",status:"accepted",result:null,error:null,recent:[],attempts:1,created:1,updated:1,summarized_attempts:0}],total:1,next_offset:null}}); }
    else await route.fulfill({json:{operations:[],offset:0,total:0,next_offset:null}});
  });
  await page.goto("/operations"); await expect(page.locator("article")).toHaveCount(0);
  await page.getByLabel("受理结果",{exact:true}).selectOption("rejected");
  await expect(page.getByText("暂无请求记录",{exact:true})).toBeVisible();
  const staleResponse = page.waitForResponse(response =>
    response.url().includes("/api/v1/operations?") && !response.url().includes("status=rejected"));
  release();
  await (await staleResponse).finished();
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
  await expect(page.locator("article")).toHaveCount(0);
  await page.route("**/api/v1/operations?**",route=>route.fulfill({status:503,json:{message:"历史暂不可用",request_id:"history-request"}}));
  await page.getByRole("button",{name:"刷新",exact:true}).click();
  await expect(page.getByRole("alert")).toContainText("历史暂不可用");
});

test("资料 pending 仅刷新清单；触屏帮助无表单副作用", async ({page,browser}) => {
  await fixture(page);
  let manifests = 0, packages = 0;
  await page.route("**/api/v1/runs/hh-test-zero/evidence",route=>{ manifests++; return route.fulfill({json:{state:manifests>1?"expired":"available",files:[]}}); });
  await page.route("**/api/v1/runs/hh-test-zero/evidence/package",route=>{ packages++; return route.fulfill({status:409,json:{code:"evidence_pending"}}); });
  await page.goto("/runs/hh-test-zero"); await page.getByRole("tab",{name:"完整资料"}).click();
  await page.getByRole("button",{name:"下载完整资料包",exact:true}).click();
  await expect(page.getByText("资料状态：已过期，无法恢复",{exact:true})).toBeVisible();
  expect(packages).toBe(1); expect(manifests).toBe(2);
  const context = await browser.newContext({viewport:{width:390,height:844},hasTouch:true,isMobile:true});
  const mobile = await context.newPage();
  const calls = await fixture(mobile);
  await mobile.goto(new URL("/attachments",page.url()).href);
  const input = mobile.getByLabel("显示名称",{exact:true}); await input.fill("保留输入");
  const help = mobile.getByRole("button",{name:"附件 ZIP帮助"});
  await help.tap(); await expect(mobile.getByRole("dialog")).toBeVisible();
  await help.tap(); await expect(mobile.getByRole("dialog")).toHaveCount(0);
  await expect(input).toHaveValue("保留输入");
  expect(calls.filter(c=>c.path==="/attachments" && c.body)).toHaveLength(0);
  await context.close();
});

for (const width of [1440,1024,390]) test(`历史与资料长文、加载、错误截图 ${width}`,async ({page}) => {
  await page.setViewportSize({width,height:900}); await fixture(page);
  const errors: string[] = []; page.on("pageerror", e=>errors.push(e.message));
  await page.route("**/api/v1/operations?**",route=>route.fulfill({json:{operations:[{id:"op-long-record-12345",user_id:"user1",username:"可识别的团队成员",operation:"submit",status:"accepted",attempts:4,created:1700000000,updated:1700000001,result:{id:"sub-real-reference",status:"ready",run_id:"hh-test-zero"},recent:[{error:{code:"idempotency_conflict"}}],request:{},error:null,idem:"long".repeat(50),summarized_attempts:2}],total:1,offset:0,next_offset:null}}));
  await page.goto("/operations"); await expect(page.locator("article")).toHaveCount(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({path:test.info().outputPath(`history-${width}.png`),fullPage:true});
  let release!: () => void; const held = new Promise<void>(resolve=>{release=resolve;});
  await page.route("**/api/v1/runs/hh-test-zero/evidence",async route=>{await held; await route.fulfill({json:{state:"available",files:[{id:"good",name:"never-shown",status:"original"},{id:"missing",status:"deleted"}]}});});
  await page.goto("/runs/hh-test-zero"); await page.getByRole("tab",{name:"完整资料"}).click();
  await expect(page.getByRole("button",{name:"刷新资料状态"})).toBeDisabled();
  await page.screenshot({path:test.info().outputPath(`materials-loading-${width}.png`)});
  release(); await expect(page.getByText("可打包 1 个文件",{exact:false})).toBeVisible();
  await page.route("**/api/v1/runs/hh-test-zero/evidence/package",route=>route.fulfill({status:503,json:{code:"evidence_snapshot_busy",request_id:"synthetic-snapshot-request"}}));
  await page.getByRole("button",{name:"下载完整资料包",exact:true}).click();
  await expect(page.getByRole("alert")).toContainText("资料包准备超时");
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({path:test.info().outputPath(`materials-error-${width}.png`),fullPage:true});
  expect(errors).toEqual([]);
});

for (const change of ["filter", "page"] as const) {
  test(`历史已有成功记录后${change}失败隐藏旧列表计数并可重试`, async ({
    page,
  }) => {
    await fixture(page);
    let fail = true;
    await page.route("**/api/v1/operations?**", async (route) => {
      const query = new URL(route.request().url()).searchParams;
      const changed =
        change === "filter"
          ? query.get("status") === "rejected"
          : query.get("offset") === "50";
      if (changed && fail)
        return route.fulfill({
          status: 503,
          json: {
            message: "当前历史加载失败",
            request_id: "history-filter-failure",
          },
        });
      await route.fulfill({
        json: {
          operations: [
            {
              id: changed ? "op-current" : "op-old",
              user_id: "u1",
              username: changed ? "当前结果用户" : "旧条件用户",
              operation: "submit",
              status: changed && change === "filter" ? "rejected" : "accepted",
              result: null,
              error: null,
              recent: [],
              attempts: 1,
              created: 1,
              updated: 1,
              summarized_attempts: 0,
            },
          ],
          total: change === "page" ? 51 : 1,
          offset: Number(query.get("offset")),
          next_offset: !changed && change === "page" ? 50 : null,
        },
      });
    });
    await page.goto("/operations");
    await expect(page.locator("article")).toContainText("旧条件用户");
    await expect(page.locator(".history-pagination")).toContainText(
      change === "page" ? "1–1 / 51 条" : "1–1 / 1 条",
    );
    if (change === "filter")
      await page
        .getByLabel("受理结果", { exact: true })
        .selectOption("rejected");
    else
      await page.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("当前历史加载失败");
    await expect(page.locator("article")).toHaveCount(0);
    await expect(page.locator(".history-pagination")).not.toContainText(
      /\d+–\d+ \/|0 条记录/,
    );
    await expect(page.getByText("暂无请求记录", { exact: true })).toHaveCount(
      0,
    );
    await expect(
      page.getByRole("button", { name: "下一页", exact: true }),
    ).toBeDisabled();
    fail = false;
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await expect(page.locator("article")).toContainText("当前结果用户");
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(page.locator(".history-pagination")).toContainText(
      change === "page" ? "51–51 / 51 条" : "1–1 / 1 条",
    );
    if (change === "filter")
      await expect(page.getByLabel("受理结果", { exact: true })).toHaveValue(
        "rejected",
      );
  });
}

test("历史成功后快切失败与恢复不被迟到的旧条件成功覆盖", async ({ page }) => {
  await fixture(page);
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let oldStarted!: () => void;
  const started = new Promise<void>((resolve) => {
    oldStarted = resolve;
  });
  let fail = true;
  await page.route("**/api/v1/operations?**", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    if (query.get("operation") === "cancel") {
      oldStarted();
      await held;
    }
    if (query.get("status") === "rejected" && fail)
      return route.fulfill({ status: 503, json: { message: "快切失败" } });
    await route.fulfill({
      json: {
        operations: [
          {
            id: "op-" + query,
            user_id: "u1",
            username:
              query.get("operation") === "cancel"
                ? "迟到旧结果"
                : query.get("status") === "rejected"
                  ? "恢复当前结果"
                  : "初始成功结果",
            operation: query.get("operation") || "submit",
            status: query.get("status") || "accepted",
            result: null,
            error: null,
            recent: [],
            attempts: 1,
            created: 1,
            updated: 1,
            summarized_attempts: 0,
          },
        ],
        total: query.get("operation") === "cancel" ? 99 : 1,
        offset: 0,
        next_offset: null,
      },
    });
  });
  await page.goto("/operations");
  await expect(page.locator("article")).toContainText("初始成功结果");
  await page.getByLabel("操作", { exact: true }).selectOption("cancel");
  await started;
  await page.getByLabel("受理结果", { exact: true }).selectOption("rejected");
  await page.getByLabel("操作", { exact: true }).selectOption("submit");
  await expect(page.getByRole("alert")).toContainText("快切失败");
  await expect(page.locator("article")).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.locator("article")).toContainText("恢复当前结果");
  const late = page.waitForResponse(
    (response) =>
      new URL(response.url()).searchParams.get("operation") === "cancel" &&
      response.status() === 200,
  );
  release();
  await late;
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  await expect(page.locator("article")).toContainText("恢复当前结果");
  await expect(page.locator("article")).not.toContainText("迟到旧结果");
  await expect(page.locator(".history-pagination")).toContainText("1–1 / 1 条");
});

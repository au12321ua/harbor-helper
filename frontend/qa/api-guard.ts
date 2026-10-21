import {
  test as base,
  expect,
  type BrowserContext,
  type TestInfo,
} from "@playwright/test";
import type { RunningVersion, MasterStatus, AccessCredential, AttachmentCatalog } from "../src/generated/contracts";

type Guard = { unknown: string[]; contexts: Set<BrowserContext> };
const guards = new WeakMap<TestInfo, Guard>();
const build = process.env.HH_QA_BUILD || "b".repeat(64);
const version = { version: "0.2.0", release: null, build, source: null } satisfies RunningVersion;
const master = { generation: 1, rotated_at: null, available: true } satisfies MasterStatus;

// Also called by fixture(page) for explicitly-created mobile contexts.
export async function protectAPI(context: BrowserContext) {
  const guard = guards.get(base.info());
  if (!guard) throw new Error("Use test exported by ./fixture for API mocks");
  if (guard.contexts.has(context)) return;
  guard.contexts.add(context);
  context.once("close", () => guard.contexts.delete(context));
  await context.route("**/api/**", async (route) => {
    const request = route.request();
    const key = `${request.method()} ${new URL(request.url()).pathname}`;
    const defaults: Record<string, unknown> = {
      "GET /api/v1/build": { build },
      "GET /api/v1/version": version,
      "GET /api/v1/upgrade-phase": { upgrading: false, phase: null },
      "GET /api/v1/attachments": { attachments: [] } satisfies AttachmentCatalog,
      "GET /api/v1/access-credentials": [] satisfies AccessCredential[],
      "GET /api/v1/admin/master-key": master,
    };
    if (Object.hasOwn(defaults, key)) {
      await route.fulfill({ json: defaults[key] });
      return;
    }
    guard.unknown.push(key);
    // Abort prevents Vite from forwarding unknown API traffic to a local service.
    await route.abort("failed");
  });
}

export const test = base.extend<{ apiGuard: void }>({
  apiGuard: [async ({ context }, runTest, info) => {
    const guard: Guard = { unknown: [], contexts: new Set() };
    guards.set(info, guard);
    try {
      await protectAPI(context);
      await runTest();
    } finally {
      for (const ctx of guard.contexts) await ctx.unrouteAll({ behavior: "wait" });
      guards.delete(info);
      expect(guard.unknown, "Unregistered API requests (method + path)").toEqual([]);
    }
  }, { auto: true }],
});

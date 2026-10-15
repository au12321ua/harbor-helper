import type {
  GET,
  POST,
  PATCH,
  PUT,
  DELETE,
  GETPath,
  PATCHPath,
  PUTPath,
  DELETEPath,
  JsonPostPath,
  UploadPath,
  ApiFailure,
  RunSummary,
  Accepted,
} from "./generated/contracts";
export type * from "./generated/contracts";
export class ApiError extends Error {
  code: string;
  requestId?: string;
  constructor(body: Partial<ApiFailure>, status: number) {
    super(body.message || `请求失败 (${status})`);
    this.code = body.code || "request_failed";
    this.requestId = body.request_id;
  }
}
// A broad template path union is only a coarse constraint: generated resolution
// also checks segment count, so an ID cannot swallow a misspelled suffix.
export type ValidPath<P, Spec> = [Spec] extends [never] ? never : P;
// Transport trust boundary: callers cannot choose a response type. Each
// method/path is generated from a server route and raw outputs are server checked.
async function request(
  path: string,
  method: string,
  body?: unknown,
  key?: boolean | string,
): Promise<unknown> {
  const headers = new Headers({ "X-Requested-With": "harbor-helper" });
  if (key)
    headers.set(
      "Idempotency-Key",
      typeof key === "string" ? key : newIdempotencyKey(),
    );
  if (body && !(body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body:
      body instanceof FormData
        ? body
        : body === undefined
          ? undefined
          : JSON.stringify(body),
  });
  const value = (await response.json().catch(() => ({
    message: `请求失败 (${response.status})`,
  }))) as Partial<ApiFailure>;
  if (!response.ok) {
    if (response.status === 401 && value.code !== "invalid_login")
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(value, response.status);
  }
  return value;
}
export function api<P extends GETPath>(
  path: ValidPath<P, GET<P>>,
): Promise<GET<P>["response"]>;
export function api<P extends PATCHPath>(
  path: ValidPath<P, PATCH<P>>,
  options: { method: "PATCH"; body: PATCH<P>["request"] },
): Promise<PATCH<P>["response"]>;
export function api<P extends PUTPath>(
  path: ValidPath<P, PUT<P>>,
  options: { method: "PUT"; body: PUT<P>["request"] },
): Promise<PUT<P>["response"]>;
export function api<P extends DELETEPath>(
  path: ValidPath<P, DELETE<P>>,
  options: { method: "DELETE" },
): Promise<DELETE<P>["response"]>;
export function api(
  path: string,
  options?: { method: string; body?: unknown },
): Promise<unknown> {
  return request(path, options?.method || "GET", options?.body);
}
export function post<P extends JsonPostPath>(
  path: ValidPath<P, POST<P>>,
  ...args: {} extends POST<P>["request"]
    ? [body?: POST<P>["request"], idempotent?: boolean | string]
    : [body: POST<P>["request"], idempotent?: boolean | string]
): Promise<POST<P>["response"]> {
  return request(path, "POST", args[0] ?? {}, args[1]) as Promise<
    POST<P>["response"]
  >;
}
export function upload<P extends UploadPath>(
  path: ValidPath<P, POST<P>>,
  metadata: POST<P>["request"],
  file: File | Blob,
  key: string,
): Promise<POST<P>["response"]> {
  const body = new FormData();
  body.set("file", file);
  body.set("metadata", JSON.stringify(metadata));
  return request(path, "POST", body, key || newIdempotencyKey()) as Promise<
    POST<P>["response"]
  >;
}
export function newIdempotencyKey() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
export const date = (value: unknown) =>
  value
    ? new Date(
        typeof value === "number" ? value * 1000 : String(value),
      ).toLocaleString("zh-CN", { hour12: false })
    : "—";
const statusLabels = {
  preparing: "准备中",
  ready: "准备完成",
  queued: "排队中",
  starting: "启动中",
  running: "运行中",
  cancelling: "取消中",
  cleanup_blocked: "资源清理阻塞",
  succeeded: "成功",
  failed: "执行失败",
  cancelled: "已取消",
  clean: "审计完成",
  incomplete: "审计异常",
  pending: "待审计",
} satisfies Record<
  RunSummary["status"] | Accepted["status"] | RunSummary["audit_status"],
  string
>;
export const labels: Readonly<Record<string, string | undefined>> =
  statusLabels;
export const terminal = (status: string) =>
  ["succeeded", "failed", "cancelled"].includes(status);

export type WriteMethod = "POST" | "PATCH" | "PUT";
export type WritePath<M extends WriteMethod> = M extends "POST"
  ? JsonPostPath
  : M extends "PATCH"
    ? PATCHPath
    : PUTPath;
export type WriteSpec<M extends WriteMethod, P> = M extends "POST"
  ? P extends JsonPostPath
    ? POST<P>
    : never
  : M extends "PATCH"
    ? P extends PATCHPath
      ? PATCH<P>
      : never
    : P extends PUTPath
      ? PUT<P>
      : never;
export function mutation<
  M extends WriteMethod = "POST",
  P extends WritePath<M> = WritePath<M>,
>(
  path: ValidPath<P, WriteSpec<M, P>>,
  body: WriteSpec<M, P>["request"],
  ...method: [M] extends ["POST"] ? [method?: M] : [method: M]
): Promise<WriteSpec<M, P>["response"]> {
  return request(path, method[0] || "POST", body) as Promise<
    WriteSpec<M, P>["response"]
  >;
}

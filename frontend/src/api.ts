export type Item = Record<string, any>;
export class ApiError extends Error {
  code: string;
  requestId?: string;
  constructor(body: Item, status: number) {
    super(body.message || `请求失败 (${status})`);
    this.code = body.code || "request_failed";
    this.requestId = body.request_id;
  }
}
export async function api<T = Item>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("X-Requested-With", "harbor-helper");
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  const body = await response
    .json()
    .catch(() => ({ message: `请求失败 (${response.status})` }));
  if (!response.ok) {
    if (response.status === 401 && body.code !== "invalid_login")
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(body, response.status);
  }
  return body as T;
}
export function newIdempotencyKey() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
export function post<T = Item>(
  path: string,
  body: unknown = {},
  idempotent: boolean | string = false,
): Promise<T> {
  return api<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: idempotent
      ? {
          "Idempotency-Key":
            typeof idempotent === "string" ? idempotent : newIdempotencyKey(),
        }
      : {},
  });
}
export const date = (value: unknown) =>
  value
    ? new Date(
        typeof value === "number" ? value * 1000 : String(value),
      ).toLocaleString("zh-CN", { hour12: false })
    : "—";
export const labels: Record<string, string> = {
  preparing: "准备中",
  queued: "排队中",
  running: "运行中",
  cleaning: "清理中",
  cleanup_blocked: "资源清理阻塞",
  succeeded: "成功",
  failed: "执行失败",
  cancelled: "已取消",
  canceling: "取消中",
  clean: "审计完成",
  complete: "审计完成",
  incomplete: "审计异常",
  pending: "待审计",
};
export const terminal = (status: string) =>
  ["succeeded", "failed", "cancelled"].includes(status);

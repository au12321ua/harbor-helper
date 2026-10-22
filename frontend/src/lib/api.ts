// Thin client for the Maestro /api/v1 contract: envelope unwrapping, CSRF header
// for cookie sessions, and typed errors. The CSRF token lives in memory only.
import type { ErrorBody, Meta } from "./types";

export const API = "/api/v1";

let csrfToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  status: number;
  body: ErrorBody;
  requestId?: string;
  /** True when the outcome is unknown (network failure, 5xx) and a retry may be needed. */
  indeterminate: boolean;

  constructor(status: number, body: ErrorBody, requestId?: string, indeterminate = false) {
    super(body.message);
    this.status = status;
    this.body = body;
    this.requestId = requestId;
    this.indeterminate = indeterminate;
  }

  get code() {
    return this.body.code;
  }

  /** Message for a form field: path "/name" or "/task_selection/task_ids" ending with the key. */
  field(name: string): string | undefined {
    const found = this.body.field_errors.find(
      (f) => f.path === `/${name}` || f.path.endsWith(`/${name}`) || f.path === name,
    );
    if (!found) return undefined;
    const limit = found.limit != null ? `（限制 ${found.limit}）` : "";
    return `${found.message ?? found.code}${limit}`;
  }
}

export interface Page<T> {
  data: T;
  meta: Meta;
}

type Method = "GET" | "POST" | "PUT" | "DELETE" | "PATCH";

interface RequestOptions {
  body?: unknown;
  headers?: Record<string, string>;
  query?: Record<string, string | number | null | undefined>;
}

export async function request<T>(
  method: Method,
  path: string,
  options: RequestOptions = {},
): Promise<Page<T>> {
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let url = path.startsWith("/") ? path : `${API}/${path}`;
  if (options.query) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(options.query)) {
      if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
    }
    const text = params.toString();
    if (text) url += `?${text}`;
  }
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      credentials: "same-origin",
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch (error) {
    throw new ApiError(
      0,
      {
        code: "NETWORK_ERROR",
        message: `网络请求失败：${error instanceof Error ? error.message : String(error)}`,
        field_errors: [],
        retryable: true,
        suggested_actions: [],
      },
      undefined,
      true,
    );
  }
  const requestId = response.headers.get("X-Request-Id") ?? undefined;
  if (response.status === 204) {
    return { data: undefined as T, meta: { request_id: requestId ?? "" } };
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const body =
      payload && typeof payload === "object" && "error" in payload
        ? (payload as { error: ErrorBody }).error
        : {
            code: `HTTP_${response.status}`,
            message: response.statusText || "请求失败",
            field_errors: [],
            retryable: response.status >= 500,
            suggested_actions: [],
          };
    body.field_errors ??= [];
    if (response.status === 401 && onUnauthorized && !path.endsWith("/session")) onUnauthorized();
    throw new ApiError(response.status, body, requestId, response.status >= 500);
  }
  return payload as Page<T>;
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"]) => request<T>("GET", path, { query }),
  post: <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
    request<T>("POST", path, { body: body ?? {}, headers }),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, { body: body ?? {} }),
  del: <T>(path: string) => request<T>("DELETE", path),
};

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return `${error.body.message}（${error.code}）`;
  return error instanceof Error ? error.message : String(error);
}

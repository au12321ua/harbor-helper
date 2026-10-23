export type Tone = "neutral" | "info" | "good" | "warn" | "bad" | "muted";

export function fmtTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

export function fmtBytes(size: number | null | undefined): string {
  if (size == null) return "—";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KiB`;
  return `${(size / 1024 / 1024).toFixed(1)} MiB`;
}

export function shortId(id: string | null | undefined, length = 12): string {
  if (!id) return "—";
  return id.length > length ? `${id.slice(0, length)}…` : id;
}

type Labels = Record<string, [string, Tone]>;

export const RUN_TERMINAL = new Set(["finished", "cancelled", "interrupted"]);

export const RUN_STATE: Labels = {
  queued: ["排队中", "info"],
  preparing: ["准备中", "info"],
  running: ["运行中", "info"],
  finalizing: ["收尾中", "info"],
  finished: ["已结束", "neutral"],
  cancelled: ["已取消", "warn"],
  interrupted: ["已中断", "bad"],
};

export const RESULT_COMPLETENESS: Labels = {
  none: ["无评分结果", "muted"],
  partial: ["部分评分", "warn"],
  complete: ["全部评分", "good"],
};

export const ARTIFACT_STATE: Labels = {
  pending: ["待保存", "muted"],
  saving: ["保存中", "info"],
  complete: ["已保存", "good"],
  partial: ["部分保存", "warn"],
  failed: ["保存失败", "bad"],
  expired: ["已过期", "warn"],
};

export const CLEANUP_STATE: Labels = {
  pending: ["待清理", "muted"],
  running: ["清理中", "info"],
  complete: ["已清理", "good"],
  failed: ["清理失败", "bad"],
  not_required: ["无需清理", "neutral"],
};

export const TRIAL_STATE: Labels = {
  queued: ["排队", "muted"],
  preparing: ["准备", "info"],
  executing: ["执行", "info"],
  verifying: ["验证", "info"],
  scored: ["已评分", "good"],
  execution_error: ["执行错误", "bad"],
  not_started: ["未开始", "muted"],
  cancelled: ["已取消", "warn"],
  interrupted: ["已中断", "bad"],
};

export const ATTEMPT_STATE: Labels = {
  starting: ["启动", "info"],
  preparing: ["准备", "info"],
  executing: ["执行", "info"],
  verifying: ["验证", "info"],
  completed: ["完成", "good"],
  failed: ["失败", "bad"],
  cancelled: ["已取消", "warn"],
  interrupted: ["已中断", "bad"],
};

/** Attempt steps as reported by the executor (Harbor: environment, agent, collecting, verifying). */
export const STEP_LABEL: Record<string, string> = {
  starting: "启动",
  environment: "准备环境",
  agent: "Agent 执行",
  collecting: "收集产物",
  verifying: "验证",
};

export const QUEUE_REASON: Record<string, string> = {
  CAPACITY_SLOTS: "等待空闲试次槽位",
  CAPACITY_CPU: "等待空闲 CPU",
  CAPACITY_MEMORY: "等待空闲内存",
  PROVIDER_LIMIT: "等待模型提供商并发额度",
  STORAGE_LOW: "存储空间不足，暂停启动",
};

export function fmtDuration(ms: number): string {
  if (Number.isNaN(ms) || ms < 0) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)} 分 ${Math.round((ms % 60_000) / 1000)} 秒`;
}

export const INVITATION_STATE: Labels = {
  pending: ["待使用", "info"],
  used: ["已使用", "neutral"],
  revoked: ["已撤销", "muted"],
  expired: ["已过期", "muted"],
};

export const PAT_STATE: Labels = {
  active: ["有效", "good"],
  revoked: ["已撤销", "muted"],
  expired: ["已过期", "muted"],
};

export function label(map: Labels, value: string | null | undefined): [string, Tone] {
  if (!value) return ["—", "muted"];
  return map[value] ?? [value, "neutral"];
}

export function blockerText(blocker: Record<string, unknown>): string {
  const { code, ...rest } = blocker;
  const extra = Object.entries(rest)
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(", ");
  return extra ? `${String(code)}（${extra}）` : String(code);
}

/** A statistic; null stays "—" (never 0). */
export function fmtNum(value: number | null | undefined, digits = 3): string {
  if (value == null || Number.isNaN(value)) return "—";
  return String(Number(value.toFixed(digits)));
}

export function fmtPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Number((value * 100).toFixed(1))}%`;
}

/** Local calendar day ("YYYY-MM-DD") to the API's RFC 3339 UTC form with microseconds. */
export function dayToApiTime(day: string, plusDays = 0): string | undefined {
  if (!day) return undefined;
  const date = new Date(`${day}T00:00:00`);
  if (Number.isNaN(date.getTime())) return undefined;
  date.setDate(date.getDate() + plusDays);
  return date.toISOString().replace(/\.(\d{3})Z$/, ".$1000Z");
}

export const ARTIFACT_STATUS: Labels = {
  pending: ["待保存", "muted"],
  available: ["可下载", "good"],
  failed: ["保存失败", "bad"],
  deleting: ["回收中", "warn"],
  expired: ["已过期", "warn"],
  unavailable: ["不可用", "bad"],
  deleted: ["已删除", "muted"],
};

export const ARTIFACT_REASON: Record<string, string> = {
  RETENTION_EXPIRED: "超过保留期，内容已回收",
  STORAGE_CONTENT_MISSING: "存储中找不到内容",
  DELETED: "管理员已删除",
};

export const EXPORT_STATE: Labels = {
  queued: ["排队中", "info"],
  building: ["打包中", "info"],
  ready: ["可下载", "good"],
  failed: ["失败", "bad"],
  expired: ["已过期", "muted"],
};

export const RECYCLE_TYPE: Record<string, string> = {
  run: "运行",
  artifact: "产物",
  dataset: "数据集",
  dataset_version: "数据集版本",
  credential: "凭据",
  user: "成员",
  pat: "访问令牌",
};

export const STORAGE_LEVEL: Labels = {
  ok: ["存储充足", "good"],
  accept_paused: ["存储偏低：暂停受理新运行", "warn"],
  dispatch_paused: ["存储不足：暂停启动排队运行", "bad"],
};

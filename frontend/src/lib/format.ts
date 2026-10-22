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

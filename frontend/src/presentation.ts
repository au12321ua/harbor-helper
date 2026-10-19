import type { Accepted, RunSummary } from "./generated/contracts";
export { formatTime as date } from "./app/timezone";
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
export const canCompare = (run: Pick<RunSummary, "status" | "audit_status">) =>
  terminal(run.status) && run.audit_status === "clean";
export const metricNumber = (value: number | null | undefined) =>
  value == null
    ? "—"
    : value === 0
      ? "0"
      : String(Number(value.toPrecision(6)));

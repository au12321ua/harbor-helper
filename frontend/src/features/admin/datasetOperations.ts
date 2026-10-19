import { ApiError, post } from "@/api";
import { useSyncExternalStore } from "react";

type Operation = {
  datasetId: string;
  label: string;
  running: boolean;
  unknown?: boolean;
  message: string;
};
let operations: Record<string, Operation> = {};
const listeners = new Set<() => void>();
function publish(operation: Operation) {
  operations = { ...operations, [operation.datasetId]: operation };
  listeners.forEach((fn) => fn());
}
export function useDatasetOperations() {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    () => operations,
  );
}
export function activeOperation() {
  return Object.values(operations).find((op) => op.running);
}
export async function runDatasetOperation(
  datasetId: string,
  name: string,
  kind: "verify" | "check",
  taskNames?: string[],
) {
  if (activeOperation()) return;
  if (
    operations[datasetId]?.unknown &&
    !window.confirm(
      "上次结果未知，后端可能仍在处理。再次执行可能重复检查，仍要继续？",
    )
  )
    return;
  const label = `${name} · ${kind === "verify" ? "来源验证" : taskNames ? `作者参数检查（${taskNames.length} 个选定任务）` : "作者参数检查（全部任务）"}`;
  publish({
    datasetId,
    label,
    running: true,
    message: `${label}中；最近已保存结果仍显示在下方。`,
  });
  try {
    const result =
      kind === "verify"
        ? await post(`/admin/catalog/dataset/${datasetId}/verify`, {})
        : await post(
            `/admin/datasets/${datasetId}/author-inputs/check`,
            taskNames ? { task_names: taskNames } : {},
          );
    if (!result || typeof result.status !== "string")
      throw new Error("无可靠应用回执");
    publish({
      datasetId,
      label,
      running: false,
      message:
        kind === "verify"
          ? result.status === "verified"
            ? "已收到回执：来源验证成功。"
            : "已收到回执：来源验证未通过，请查看已保存状态。"
          : ["checked", "partial_checked"].includes(result.status)
            ? "已收到回执：作者参数检查完成，请查看范围与结果。"
            : "已收到回执：作者参数存在阻碍，请查看范围与结果。",
    });
    window.dispatchEvent(new Event("dataset-operation-completed"));
  } catch (error) {
    const known =
      error instanceof ApiError &&
      error.status < 500 &&
      error.code !== "request_failed";
    const message = known
      ? ["configuration_changed", "dataset_unverified"].includes(error.code)
        ? "来源已变更或失效，本次结果未保存。"
        : `服务拒绝（${error.code}）：${error.message}`
      : "结果未知：未收到完成回执；后端可能仍在处理，也可能已中断。请手动刷新最近已保存结果；刷新不证明本次操作成功。";
    publish({ datasetId, label, running: false, unknown: !known, message });
  }
}

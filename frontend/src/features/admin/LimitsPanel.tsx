import { TabsContent } from "@/components/ui/tabs";
import { ShutdownPanel } from "./ShutdownPanel";
import { AdminForm } from "@/features/admin/AdminForm";
import { MaintenancePanel } from "@/features/admission/ReadinessPanel";
import type { AdminPanelProps } from "./types";

const limitLabels: Record<string, string> = {
  max_jobs: "全局任务并发",
  max_trials: "全局 Trial 并发",
  max_queue: "全局待处理上限（准备中与排队）",
  max_pending_per_member: "每成员待处理额度（有效值不超过全局上限）",
  max_wall_seconds: "实验总时长上限（秒，含准备）",
  max_attempts: "每任务最大尝试数",
  max_cpus_per_trial: "每 Trial CPU 上限",
  max_memory_mb_per_trial: "每 Trial 内存 MB",
  max_upload_bytes: "最大上传字节数",
  log_retention_days: "日志保留天数",
  artifact_retention_days: "产物保留天数",
};

export function LimitsPanel({
  c,
  save,
  reload,
}: Pick<AdminPanelProps, "c" | "save"> & { reload: () => Promise<void> }) {
  return (
    <TabsContent value="limits" className="flex flex-col gap-4">
      <ShutdownPanel />
      <MaintenancePanel readiness={c.readiness} saved={reload} />
      <AdminForm
        title="容量与保留"
        description="CLI/Web 共用；运行时长与并发不保证金额预算。降低额度不取消存量；每成员所有凭证与网页共用额度，管理员也计入本人额度。"
        fields={Object.entries(c.limits || {})
          .filter(([name]) => name in limitLabels)
          .map(([name, v]) => ({
            name,
            label: limitLabels[name],
            type: "number",
            defaultValue: String(v),
          }))}
        onSave={(v) =>
          save(
            "/admin/limits",
            Object.fromEntries(
              Object.entries(v).map(([k, x]) => [k, Number(x)]),
            ),
            "PATCH",
          )
        }
      />
    </TabsContent>
  );
}

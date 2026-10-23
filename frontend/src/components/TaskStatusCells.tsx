import { TableCell } from "@/components/ui/table";
import { Pill } from "@/components/common";
import { blockerText, CACHE_STATE, fmtTime, type Tone } from "@/lib/format";
import type { Task } from "@/lib/types";

const ADMISSION: Record<string, [string, Tone]> = {
  admitted: ["已准入", "good"],
  pending: ["待首次准备", "warn"],
  first_failed: ["首次准备失败", "bad"],
  revoked: ["已撤销", "bad"],
};
const AVAILABILITY: Record<string, [string, Tone]> = {
  available: ["可得", "good"],
  unavailable: ["不可得", "bad"],
  unknown: ["未检查", "muted"],
};

/** Admission, content availability, local cache, can_submit and reasons for one task row.
 * The three facts are separate: a cold cache never blocks submission (02 section 5). */
export function TaskStatusCells({ task }: { task: Task }) {
  const [availability, tone] = AVAILABILITY[task.content.availability] ?? [
    task.content.availability,
    "neutral" as Tone,
  ];
  const cache = CACHE_STATE[task.local_preparation.cache_state] ?? [
    task.local_preparation.cache_state,
    "neutral" as Tone,
  ];
  const restoreError = task.local_preparation.last_restore_error;
  const notes = [
    ...task.blockers.map(blockerText),
    ...task.warnings.map((w) =>
      w.code === "PREPARATION_CACHE_MISS" ? "本机缓存已回收，运行时自动按原摘要恢复" : w.code,
    ),
  ];
  if (restoreError?.message) notes.push(`上次恢复失败：${String(restoreError.message)}`);
  return (
    <>
      <TableCell>
        {task.admission ? (
          <Pill tone={ADMISSION[task.admission.state]?.[1] ?? "neutral"}>
            {ADMISSION[task.admission.state]?.[0] ?? task.admission.state}
          </Pill>
        ) : (
          <Pill tone="muted">未准入</Pill>
        )}
      </TableCell>
      <TableCell>
        <Pill
          tone={tone}
          title={task.content.resources
            .map((r) => `${r.resource_kind} ${r.digest}：${r.availability}`)
            .concat(`检查于 ${fmtTime(task.content.checked_at)}`)
            .join("\n")}
        >
          {availability}
        </Pill>
      </TableCell>
      <TableCell>
        <Pill tone={cache[1]} title={`位置 ${task.local_preparation.location_id}`}>
          {cache[0]}
        </Pill>
      </TableCell>
      <TableCell>
        {task.can_submit ? <Pill tone="good">可提交</Pill> : <Pill tone="bad">不可提交</Pill>}
      </TableCell>
      <TableCell className="max-w-md text-xs text-muted-foreground">
        {notes.length === 0 ? "—" : notes.join("；")}
      </TableCell>
    </>
  );
}

import { TableCell } from "@/components/ui/table";
import { Pill } from "@/components/common";
import { blockerText, fmtTime, type Tone } from "@/lib/format";
import type { Task } from "@/lib/types";

const ADMISSION: Record<string, [string, Tone]> = {
  admitted: ["已准入", "good"],
  pending: ["待准入", "warn"],
  revoked: ["已撤销", "bad"],
};
const AVAILABILITY: Record<string, [string, Tone]> = {
  available: ["可得", "good"],
  unavailable: ["不可得", "bad"],
  unknown: ["未检查", "muted"],
};

/** Admission, content availability, can_submit and blockers for one task row. */
export function TaskStatusCells({ task }: { task: Task }) {
  const [availability, tone] = AVAILABILITY[task.content.availability] ?? [
    task.content.availability,
    "neutral" as Tone,
  ];
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
          title={`digest ${task.content.digest}；检查于 ${fmtTime(task.content.checked_at)}`}
        >
          {availability}
        </Pill>
      </TableCell>
      <TableCell>
        {task.can_submit ? <Pill tone="good">可提交</Pill> : <Pill tone="bad">不可提交</Pill>}
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">
        {task.blockers.length === 0 ? "—" : task.blockers.map(blockerText).join("；")}
      </TableCell>
    </>
  );
}

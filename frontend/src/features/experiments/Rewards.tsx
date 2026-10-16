import { type Report } from "@/api";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
export function Rewards({ report }: { report: Report }) {
  return (
    <>
      <div className="report-summary">
        <div>
          <span>有效尝试</span>
          <strong>
            {report.valid_attempts ?? "—"} / {report.expected_attempts ?? "—"}
          </strong>
        </div>
        <div>
          <span>无效尝试</span>
          <strong>{report.invalid_attempts ?? "—"}</strong>
        </div>
        <div>
          <span>缺失尝试</span>
          <strong>{report.missing_attempts ?? "—"}</strong>
        </div>
        <div>
          <span>报告状态</span>
          <strong>{report.complete ? "完整" : "不完整"}</strong>
        </div>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>任务</TableHead>
            <TableHead>有效尝试</TableHead>
            <TableHead>评分</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(report.tasks || []).map((t, i: number) => (
            <TableRow key={t.task || i}>
              <TableCell className="mono">
                {t.task}
                {t.attempts?.some(
                  (attempt) =>
                    attempt.exception ||
                    attempt.framework_exception ||
                    (attempt.agent_exit_code != null &&
                      attempt.agent_exit_code !== "0"),
                ) && <small className="status-failed">执行失败</small>}
              </TableCell>
              <TableCell>
                {t.valid_attempts} / {t.expected_attempts}
              </TableCell>
              <TableCell>
                {t.mean_rewards == null ||
                !Object.keys(t.mean_rewards).length ? (
                  <span className="text-muted-foreground">缺失评分</span>
                ) : (
                  Object.entries(t.mean_rewards).map(([name, value]) => (
                    <div key={name}>
                      {name}: <strong>{String(value)}</strong>
                    </div>
                  ))
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {!report.complete ? (
        <p className="quiet-note">
          报告尚不完整。缺失评分不等于零分；执行失败由任务状态单独表示。
        </p>
      ) : null}
    </>
  );
}

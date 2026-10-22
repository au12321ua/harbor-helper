import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyNote, ErrorAlert, Loading, PageTitle, StatusPill } from "@/components/common";
import { api } from "@/lib/api";
import {
  ARTIFACT_STATE,
  CLEANUP_STATE,
  RESULT_COMPLETENESS,
  RUN_STATE,
  fmtTime,
  label,
  shortId,
} from "@/lib/format";
import { useSession } from "@/lib/hooks";
import type { Run } from "@/lib/types";
import { cn } from "@/lib/utils";

export function RunListPage() {
  const { me } = useSession();
  const [scope, setScope] = useState<"mine" | "all">("all");
  const [runs, setRuns] = useState<Run[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    async (after: string | null) => {
      setLoading(true);
      try {
        const res = await api.get<Run[]>("runs", {
          owner_id: scope === "mine" ? me.id : undefined,
          cursor: after,
        });
        setRuns((prev) => (after ? [...prev, ...res.data] : res.data));
        setCursor(res.meta.next_cursor ?? null);
        setError(undefined);
      } catch (err) {
        setError(err);
      } finally {
        setLoading(false);
      }
    },
    [scope, me.id],
  );

  useEffect(() => {
    void load(null);
  }, [load]);

  return (
    <div>
      <PageTitle title="运行">
        <div className="flex rounded-md border bg-background p-0.5 text-sm">
          {(["all", "mine"] as const).map((value) => (
            <button
              key={value}
              type="button"
              className={cn(
                "rounded px-3 py-1",
                scope === value ? "bg-primary text-primary-foreground" : "text-muted-foreground",
              )}
              onClick={() => setScope(value)}
            >
              {value === "all" ? "全部" : "我的"}
            </button>
          ))}
        </div>
        <Button variant="outline" size="sm" onClick={() => void load(null)}>
          <RefreshCw />
          刷新
        </Button>
        <Button asChild size="sm">
          <Link to="/runs/new">
            <Plus />
            新建运行
          </Link>
        </Button>
      </PageTitle>
      <ErrorAlert error={error} />
      {runs.length === 0 && !loading && !error && <EmptyNote>还没有运行记录。</EmptyNote>}
      {runs.length > 0 && (
        <div className="rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>提交者</TableHead>
                <TableHead>生命周期</TableHead>
                <TableHead>评分覆盖</TableHead>
                <TableHead>产物</TableHead>
                <TableHead>环境清理</TableHead>
                <TableHead className="text-right">已评分 / 计划</TableHead>
                <TableHead className="text-right">错误</TableHead>
                <TableHead>受理时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((run) => (
                <TableRow key={run.id}>
                  <TableCell>
                    <Link className="font-medium text-primary hover:underline" to={`/runs/${run.id}`}>
                      {run.name}
                    </Link>
                    <div className="text-xs text-muted-foreground">{shortId(run.id, 16)}</div>
                  </TableCell>
                  <TableCell className="text-xs">
                    {run.owner_id === me.id ? "我" : run.owner.display_name}
                    {run.pat_id && <div className="text-muted-foreground">PAT</div>}
                  </TableCell>
                  <TableCell>
                    <StatusPill value={label(RUN_STATE, run.state)} />
                    {run.stop_requested && run.state !== "cancelled" && (
                      <div className="mt-1 text-xs text-amber-700">已请求停止</div>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusPill value={label(RESULT_COMPLETENESS, run.result_completeness)} />
                  </TableCell>
                  <TableCell>
                    <StatusPill value={label(ARTIFACT_STATE, run.artifact_state)} />
                  </TableCell>
                  <TableCell>
                    <StatusPill value={label(CLEANUP_STATE, run.cleanup_state)} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {run.counts.scored} / {run.counts.planned}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{run.counts.errors}</TableCell>
                  <TableCell className="text-xs">{fmtTime(run.accepted_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {loading && <Loading />}
      {cursor && !loading && (
        <div className="mt-4 flex justify-center">
          <Button variant="outline" onClick={() => void load(cursor)}>
            加载更多
          </Button>
        </div>
      )}
    </div>
  );
}

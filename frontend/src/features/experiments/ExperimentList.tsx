import { api } from "@/api";
import {
  EmptyState,
  ErrorNotice,
  Loading,
  Status,
  Title,
} from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ReadinessNotice } from "@/features/admission/ReadinessPanel";
import { useLoad } from "@/hooks/useLoad";
import { date } from "@/presentation";
import { ArrowUpRight, Plus, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
export function ExperimentList() {
  const { data, error, loading, reload } = useLoad(
    () => Promise.all([api("/runs"), api("/usage")]),
    "",
    4000,
  );
  const [filter, setFilter] = useState("");
  if (loading) return <Loading />;
  const runs = data?.[0].runs || [],
    submissions = data?.[0].submissions || [],
    usage = data?.[1];
  if (!usage) return <ErrorNotice error={error} />;
  const shown = runs.filter((r) =>
    JSON.stringify([r.id, r.name, r.submitter, r.dataset, r.status])
      .toLowerCase()
      .includes(filter.toLowerCase()),
  );
  return (
    <>
      <Title
        title="共享实验"
        description="团队的每一次尝试，都在这里留下记录。"
        action={
          <Button asChild>
            <Link to="/new">
              <Plus data-icon="inline-start" />
              新建实验
            </Link>
          </Button>
        }
      />
      <ErrorNotice error={error} />
      <ReadinessNotice />
      <div className="usage-strip">
        <div>
          <span>累计实验</span>
          <strong>{usage.total_runs ?? runs.length}</strong>
        </div>
        <div>
          <span>运行中</span>
          <strong>
            {usage.active_jobs ?? "—"}
            <small> 个任务</small>
          </strong>
        </div>
        <div>
          <span>排队中</span>
          <strong>{usage.queued_jobs ?? "—"}</strong>
        </div>
        <div>
          <span>累计提交</span>
          <strong>{usage.total_submissions ?? submissions.length}</strong>
        </div>
      </div>
      <div className="section-bar">
        <h2>
          实验记录 <span>{runs.length}</span>
        </h2>
        <div className="flex gap-2">
          <Input
            aria-label="搜索实验"
            placeholder="搜索编号、成员、数据集…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <Button
            variant="outline"
            size="icon"
            aria-label="刷新实验"
            onClick={() => void reload()}
          >
            <RefreshCw />
          </Button>
        </div>
      </div>
      <div className="table-shell">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>实验 / 数据集</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>提交者</TableHead>
              <TableHead>创建时间</TableHead>
              <TableHead>审计</TableHead>
              <TableHead className="text-right">详情</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((r) => (
              <TableRow key={r.id}>
                <TableCell>
                  <Link className="run-link" to={`/runs/${r.id}`}>
                    {r.name || r.id}
                  </Link>
                  <div className="cell-secondary">
                    {typeof r.dataset === "string" ? r.dataset : "—"}
                  </div>
                </TableCell>
                <TableCell>
                  <Status value={r.status} />
                </TableCell>
                <TableCell>{r.submitter || "—"}</TableCell>
                <TableCell className="whitespace-nowrap">
                  {date(r.created)}
                </TableCell>
                <TableCell>
                  <Status value={r.audit_status} />
                </TableCell>
                <TableCell className="text-right">
                  <Button variant="ghost" size="icon" asChild>
                    <Link aria-label={`查看 ${r.id}`} to={`/runs/${r.id}`}>
                      <ArrowUpRight />
                    </Link>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {!shown.length ? (
          <EmptyState
            title={filter ? "没有匹配的实验" : undefined}
            description={filter ? "试试其他编号、成员或数据集。" : undefined}
          />
        ) : null}
      </div>
      {submissions.filter((s) => !s.run_id).length ? (
        <section className="flex flex-col gap-4">
          <h2>准备中的提交</h2>
          {submissions
            .filter((s) => !s.run_id)
            .map((s) => (
              <Card key={s.id}>
                <CardContent className="submission-row">
                  <Link to={`/submissions/${s.id}`}>
                    {s.request?.name || s.id}
                  </Link>
                  <Status value={s.status} />
                  <span>{s.submitter}</span>
                  <span className="text-muted-foreground">
                    {s.error || "等待数据源解析与入队"}
                  </span>
                </CardContent>
              </Card>
            ))}
        </section>
      ) : null}
      <p className="quiet-note">
        运行时长和并发限制控制资源使用，不代表准确的费用预算。
      </p>
    </>
  );
}

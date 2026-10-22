import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyNote, ErrorAlert, Loading, PageTitle, Pill } from "@/components/common";
import { TaskStatusCells } from "@/components/TaskStatusCells";
import { api } from "@/lib/api";
import { fmtTime, shortId } from "@/lib/format";
import { useLoad } from "@/lib/hooks";
import type { Dataset, DatasetVersionDetail, Task } from "@/lib/types";
import { cn } from "@/lib/utils";

export function DatasetsPage() {
  const datasets = useLoad(async () => (await api.get<Dataset[]>("datasets", { limit: 200 })).data);
  const [chosen, setVersionId] = useState<string>("");
  const versionId =
    chosen || datasets.data?.find((d) => d.versions.length > 0)?.versions[0].id || "";

  return (
    <div>
      <PageTitle title="数据集" />
      <p className="mb-4 text-sm text-muted-foreground">
        只读目录。数据集导入与首次准备将在后续版本提供。
      </p>
      <ErrorAlert error={datasets.error} />
      {datasets.loading && !datasets.data && <Loading />}
      {datasets.data && datasets.data.length === 0 && <EmptyNote>还没有数据集。</EmptyNote>}
      <div className="grid gap-4 lg:grid-cols-[minmax(260px,1fr)_3fr]">
        <div className="grid content-start gap-3">
          {datasets.data?.map((dataset) => (
            <Card key={dataset.id}>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">
                  {dataset.namespace}/{dataset.name}
                </CardTitle>
                <div className="text-xs text-muted-foreground">
                  来源：{dataset.source_kind}
                  {dataset.description && ` · ${dataset.description}`}
                </div>
              </CardHeader>
              <CardContent className="grid gap-1">
                {dataset.versions.length === 0 && (
                  <span className="text-xs text-muted-foreground">无版本</span>
                )}
                {dataset.versions.map((version) => (
                  <button
                    key={version.id}
                    type="button"
                    onClick={() => setVersionId(version.id)}
                    className={cn(
                      "flex items-center justify-between rounded-md border px-2 py-1 text-left text-sm",
                      versionId === version.id ? "border-primary bg-accent" : "hover:bg-muted",
                    )}
                  >
                    <span>
                      {version.upstream_ref}
                      <span className="ml-1 text-xs text-muted-foreground">({version.ref_kind})</span>
                    </span>
                    <Pill tone="neutral">{version.status}</Pill>
                  </button>
                ))}
              </CardContent>
            </Card>
          ))}
        </div>
        {versionId && <VersionTasks versionId={versionId} />}
      </div>
    </div>
  );
}

function VersionTasks({ versionId }: { versionId: string }) {
  const detail = useLoad(
    async () => (await api.get<DatasetVersionDetail>(`dataset-versions/${versionId}`)).data,
    [versionId],
  );
  const tasks = useLoad(
    async () => (await api.get<Task[]>(`dataset-versions/${versionId}/tasks`)).data,
    [versionId],
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">版本任务</CardTitle>
        {detail.data && (
          <div className="grid gap-1 text-xs text-muted-foreground">
            <div>
              版本 {detail.data.id} · 解析摘要{" "}
              <code title={detail.data.resolved_digest}>{shortId(detail.data.resolved_digest, 20)}</code>{" "}
              · 登记于 {fmtTime(detail.data.created_at)}
            </div>
            <div className="text-sm text-foreground">
              共 {detail.data.task_count} 个任务 · 已准入 {detail.data.admitted_task_count} ·
              可提交 {detail.data.submittable_task_count}
            </div>
          </div>
        )}
      </CardHeader>
      <CardContent>
        <ErrorAlert error={detail.error ?? tasks.error} />
        {tasks.loading && !tasks.data && <Loading />}
        {tasks.data && tasks.data.length === 0 && <EmptyNote>该版本没有任务。</EmptyNote>}
        {tasks.data && tasks.data.length > 0 && (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>任务</TableHead>
                  <TableHead>准入</TableHead>
                  <TableHead>内容</TableHead>
                  <TableHead>可提交</TableHead>
                  <TableHead>阻塞原因</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tasks.data.map((task) => (
                  <TableRow key={task.id}>
                    <TableCell className="font-mono text-xs">{task.task_key}</TableCell>
                    <TaskStatusCells task={task} />
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

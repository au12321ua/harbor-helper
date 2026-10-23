import { useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
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
import { api, errorText } from "@/lib/api";
import { fmtTime, shortId } from "@/lib/format";
import { useLoad, useSession } from "@/lib/hooks";
import type { Dataset, DatasetVersion, DatasetVersionDetail, Task } from "@/lib/types";
import { cn } from "@/lib/utils";

export function DatasetsPage() {
  const { me } = useSession();
  const canDelete = me.role === "admin" && me.auth_channel === "web_session";
  const datasets = useLoad(async () => (await api.get<Dataset[]>("datasets", { limit: 200 })).data);
  const [chosen, setVersionId] = useState<string>("");
  const visible = datasets.data?.some((d) => d.versions.some((v) => v.id === chosen));
  const versionId =
    (visible ? chosen : "") ||
    datasets.data?.find((d) => d.versions.length > 0)?.versions[0].id ||
    "";

  const removeDataset = async (dataset: Dataset) => {
    if (
      !window.confirm(
        `删除数据集「${dataset.namespace}/${dataset.name}」及其全部版本？它会移入回收站；已有运行记录保留，但不能再用它提交或重跑。`,
      )
    )
      return;
    try {
      await api.del(`admin/datasets/${dataset.id}`);
      toast.success("已移入回收站");
    } catch (err) {
      toast.error(`删除失败：${errorText(err)}`);
    }
    await datasets.reload();
  };

  const removeVersion = async (dataset: Dataset, version: DatasetVersion) => {
    if (
      !window.confirm(
        `删除版本「${dataset.name} ${version.upstream_ref}」？它会移入回收站；已有运行记录保留，但不能再用它提交或重跑。`,
      )
    )
      return;
    try {
      await api.del(`admin/dataset-versions/${version.id}`);
      toast.success("已移入回收站");
    } catch (err) {
      toast.error(`删除失败：${errorText(err)}`);
    }
    await datasets.reload();
  };

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
                <CardTitle className="flex items-center justify-between gap-2 text-base">
                  {dataset.namespace}/{dataset.name}
                  {canDelete && (
                    <Button
                      size="sm"
                      variant="ghost"
                      title="删除数据集"
                      aria-label={`删除数据集 ${dataset.name}`}
                      onClick={() => void removeDataset(dataset)}
                    >
                      <Trash2 />
                    </Button>
                  )}
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
                  <div key={version.id} className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => setVersionId(version.id)}
                      className={cn(
                        "flex flex-1 items-center justify-between rounded-md border px-2 py-1 text-left text-sm",
                        versionId === version.id ? "border-primary bg-accent" : "hover:bg-muted",
                      )}
                    >
                      <span>
                        {version.upstream_ref}
                        <span className="ml-1 text-xs text-muted-foreground">({version.ref_kind})</span>
                      </span>
                      <Pill tone="neutral">{version.status}</Pill>
                    </button>
                    {canDelete && (
                      <Button
                        size="sm"
                        variant="ghost"
                        title="删除该版本"
                        aria-label={`删除版本 ${version.upstream_ref}`}
                        onClick={() => void removeVersion(dataset, version)}
                      >
                        <Trash2 />
                      </Button>
                    )}
                  </div>
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
            {detail.data.deletion && (
              <div className="text-sm text-amber-800">
                该版本已删除（{detail.data.deletion.state === "purged" ? "已彻底删除" : "在回收站中"}，
                {fmtTime(detail.data.deletion.deleted_at)}）。
              </div>
            )}
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

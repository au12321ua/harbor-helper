import { useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
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
import {
  EmptyNote,
  ErrorAlert,
  Loading,
  PageTitle,
  Pill,
  SelectField,
  TextField,
} from "@/components/common";
import { ApiError, api } from "@/lib/api";
import { limit, useLoad, useSession } from "@/lib/hooks";
import type { Dataset, DatasetVersionDetail, RunAccepted, RunCreate, Task } from "@/lib/types";
import { TaskStatusCells } from "@/components/TaskStatusCells";

function newKey() {
  return crypto.randomUUID();
}

export function NewRunPage() {
  const { capabilities } = useSession();
  const navigate = useNavigate();
  const datasets = useLoad(async () => (await api.get<Dataset[]>("datasets", { limit: 200 })).data);
  const versions = useMemo(
    () =>
      (datasets.data ?? []).flatMap((d) =>
        d.versions.map((v) => ({ dataset: d, version: v })),
      ),
    [datasets.data],
  );

  const [chosenVersion, setChosenVersion] = useState("");
  const versionId = chosenVersion || versions[0]?.version.id || "";

  const tasks = useLoad(
    async () =>
      versionId
        ? (await api.get<Task[]>(`dataset-versions/${versionId}/tasks`)).data
        : ([] as Task[]),
    [versionId],
  );
  const detail = useLoad(
    async () =>
      versionId
        ? (await api.get<DatasetVersionDetail>(`dataset-versions/${versionId}`)).data
        : undefined,
    [versionId],
  );

  const repetitionsMax = limit(capabilities, "repetitions_max", 20);
  const concurrencyMax = limit(capabilities, "run_max_concurrency", 10);
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"all_eligible" | "explicit">("all_eligible");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [repetitions, setRepetitions] = useState(String(limit(capabilities, "repetitions_default", 1)));
  const [concurrency, setConcurrency] = useState(
    String(limit(capabilities, "run_default_concurrency", 4)),
  );
  const [clientRequestId, setClientRequestId] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  // One idempotency key per logical submission; kept while the outcome is unknown.
  const key = useRef<string>(newKey());
  // Set to the key in use while a submission's outcome is unknown.
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  const eligible = (tasks.data ?? []).filter((t) => t.can_submit);
  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    const body: RunCreate = {
      name,
      dataset_version_id: versionId,
      task_selection:
        mode === "all_eligible" ? { mode } : { mode, task_ids: [...selected].sort() },
      repetitions: Number(repetitions),
      concurrency: Number(concurrency),
      client_request_id: clientRequestId || null,
    };
    try {
      const res = await api.post<RunAccepted>("runs", body, { "Idempotency-Key": key.current });
      key.current = newKey();
      setPendingKey(null);
      toast.success(`已受理：计划 ${res.data.planned_trials} 个试次`);
      navigate(`/runs/${res.data.run_id}`);
    } catch (err) {
      setError(err);
      if (err instanceof ApiError && err.indeterminate) {
        setPendingKey(key.current);
      } else {
        key.current = newKey();
        setPendingKey(null);
      }
    } finally {
      setBusy(false);
    }
  };

  const fieldErr = (name: string) => (error instanceof ApiError ? error.field(name) : undefined);

  return (
    <div>
      <PageTitle title="新建运行">
        <Button asChild variant="outline" size="sm">
          <Link to="/runs">返回列表</Link>
        </Button>
      </PageTitle>
      {datasets.loading && !datasets.data && <Loading />}
      <ErrorAlert error={datasets.error} title="无法加载数据集" />
      {datasets.data && versions.length === 0 && (
        <EmptyNote>还没有可用的数据集版本。数据集导入将在后续版本提供。</EmptyNote>
      )}
      {versions.length > 0 && (
        <form className="grid gap-4" onSubmit={submit}>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">基本信息</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
              <TextField
                id="run-name"
                label="运行名称"
                value={name}
                onChange={(e) => setName(e.target.value)}
                error={fieldErr("name")}
                required
              />
              <SelectField
                id="run-version"
                label="数据集版本"
                value={versionId}
                onChange={(e) => {
                  setChosenVersion(e.target.value);
                  setSelected(new Set());
                }}
                error={fieldErr("dataset_version_id")}
              >
                {versions.map(({ dataset, version }) => (
                  <option key={version.id} value={version.id}>
                    {dataset.namespace}/{dataset.name} @ {version.upstream_ref} ({version.status})
                  </option>
                ))}
              </SelectField>
              <TextField
                id="run-repetitions"
                label={`每任务重复次数（1–${repetitionsMax}）`}
                type="number"
                min={1}
                max={repetitionsMax}
                value={repetitions}
                onChange={(e) => setRepetitions(e.target.value)}
                error={fieldErr("repetitions")}
                required
              />
              <TextField
                id="run-concurrency"
                label={`并发数（1–${concurrencyMax}）`}
                type="number"
                min={1}
                max={concurrencyMax}
                value={concurrency}
                onChange={(e) => setConcurrency(e.target.value)}
                error={fieldErr("concurrency")}
                required
              />
              <TextField
                id="run-client-request"
                label="客户端请求标识（可选）"
                value={clientRequestId}
                onChange={(e) => setClientRequestId(e.target.value)}
                error={fieldErr("client_request_id")}
                hint="便于之后按此标识查找该运行"
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">任务选择</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3">
              {detail.data && (
                <p className="text-sm text-muted-foreground">
                  共 {detail.data.task_count} 个任务；已准入 {detail.data.admitted_task_count}；
                  可提交 {detail.data.submittable_task_count}。
                </p>
              )}
              <div className="flex flex-wrap gap-4 text-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="mode"
                    checked={mode === "all_eligible"}
                    onChange={() => setMode("all_eligible")}
                  />
                  全部可提交任务（{eligible.length}）
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="mode"
                    checked={mode === "explicit"}
                    onChange={() => setMode("explicit")}
                  />
                  手动选择（已选 {selected.size}）
                </label>
              </div>
              {fieldErr("task_selection") && (
                <p className="text-xs text-destructive">{fieldErr("task_selection")}</p>
              )}
              {fieldErr("task_ids") && (
                <p className="text-xs text-destructive">{fieldErr("task_ids")}</p>
              )}
              <ErrorAlert error={tasks.error} title="无法加载任务" />
              {tasks.loading && !tasks.data && <Loading />}
              {tasks.data && (
                <div className="max-h-96 overflow-auto rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        {mode === "explicit" && <TableHead className="w-10" />}
                        <TableHead>任务</TableHead>
                        <TableHead>准入</TableHead>
                        <TableHead>内容</TableHead>
                        <TableHead>本机缓存</TableHead>
                        <TableHead>可提交</TableHead>
                        <TableHead>说明</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {tasks.data.map((task) => (
                        <TableRow key={task.id}>
                          {mode === "explicit" && (
                            <TableCell>
                              <input
                                type="checkbox"
                                aria-label={`选择 ${task.task_key}`}
                                disabled={!task.can_submit}
                                checked={selected.has(task.id)}
                                onChange={() => toggle(task.id)}
                              />
                            </TableCell>
                          )}
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

          {pendingKey && (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              上次提交结果未知（网络或服务端错误）。再次提交会复用同一幂等键，不会重复创建运行。
              <Pill tone="muted">Idempotency-Key {pendingKey.slice(0, 8)}…</Pill>
            </div>
          )}
          <ErrorAlert error={error} title="提交失败" />
          <div>
            <Button
              type="submit"
              disabled={busy || !versionId || (mode === "explicit" && selected.size === 0)}
            >
              {busy ? "提交中…" : pendingKey ? "重试提交" : "提交运行"}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

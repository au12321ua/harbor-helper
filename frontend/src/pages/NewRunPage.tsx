import { useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
  JsonBlock,
  Loading,
  PageTitle,
  Pill,
  SelectField,
  TextField,
} from "@/components/common";
import { ApiError, api } from "@/lib/api";
import {
  CONFIG_BLOCKER,
  SOURCE_LAYER,
  blockerText,
  fmtTime,
} from "@/lib/format";
import { limit, useLoad, useSession } from "@/lib/hooks";
import type {
  ConfigRequest,
  ConfigResolution,
  CredentialName,
  Dataset,
  DatasetVersionDetail,
  ExecutionMode,
  Harness,
  ModelConfig,
  ParameterValue,
  RunAccepted,
  RunCreate,
  Task,
} from "@/lib/types";
import { TaskStatusCells } from "@/components/TaskStatusCells";

function newKey() {
  return crypto.randomUUID();
}

/** Blank means "inherit": the field is sent as null so the resolver takes the layer below. */
function numberOrNull(text: string): number | null {
  return text.trim() === "" ? null : Number(text);
}

export function NewRunPage() {
  const { capabilities } = useSession();
  const navigate = useNavigate();
  const datasets = useLoad(
    async () => (await api.get<Dataset[]>("datasets", { limit: 200 })).data,
  );
  const models = useLoad(
    async () => (await api.get<ModelConfig[]>("model-configs")).data,
  );
  const harnesses = useLoad(
    async () => (await api.get<Harness[]>("harness-versions")).data,
  );
  const credentials = useLoad(
    async () => (await api.get<CredentialName[]>("credentials")).data,
  );
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
        ? (await api.get<DatasetVersionDetail>(`dataset-versions/${versionId}`))
            .data
        : undefined,
    [versionId],
  );

  const [name, setName] = useState("");
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("agent");
  const [modelId, setModelId] = useState("");
  const [harnessId, setHarnessId] = useState("");
  const [harnessParams, setHarnessParams] = useState<Record<string, string>>(
    {},
  );
  const [mode, setMode] = useState<"all_eligible" | "explicit">("all_eligible");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [overrides, setOverrides] = useState({
    repetitions: "",
    concurrency: "",
    run_deadline_hours: "",
    agent_sec: "",
    cpus: "",
    memory_mb: "",
  });
  const [parameters, setParameters] = useState<
    Record<string, { value: string; secret: boolean }>
  >({});
  const [clientRequestId, setClientRequestId] = useState("");
  const [resolution, setResolution] = useState<ConfigResolution | null>(null);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  // One idempotency key per logical submission; kept while the outcome is unknown.
  const key = useRef<string>(newKey());
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  const model =
    (models.data ?? []).find((m) => m.id === modelId) ?? models.data?.[0];
  const compatible = (harnesses.data ?? []).filter(
    (h) => h.enabled && (!model || h.protocols.includes(model.protocol)),
  );
  const harness = compatible.find((h) => h.id === harnessId) ?? compatible[0];
  const eligible = (tasks.data ?? []).filter((t) => t.can_submit);
  // Author parameters declared by this version's tasks; required ones need a value.
  const declared = useMemo(() => {
    const found = new Map<
      string,
      { sensitive: boolean; required: boolean; default: string | null }
    >();
    for (const task of tasks.data ?? []) {
      for (const p of task.parameters) {
        const known = found.get(p.name);
        found.set(p.name, {
          sensitive: (known?.sensitive ?? false) || p.sensitive,
          required:
            (known?.required ?? false) ||
            task.required_parameters.includes(p.name),
          default: known?.default ?? p.default,
        });
      }
    }
    return [...found.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [tasks.data]);

  // Any edit makes the shown resolution outdated: it has to be checked again.
  const changed =
    <T,>(set: (value: T) => void) =>
    (value: T) => {
      set(value);
      setResolution(null);
    };
  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    changed(setSelected)(next);
  };

  const request = (): ConfigRequest => {
    const params: Record<string, ParameterValue> = {};
    for (const [pname, entry] of Object.entries(parameters)) {
      if (entry.value.trim() === "") continue;
      params[pname] = entry.secret
        ? { credential_id: entry.value.trim() }
        : entry.value;
    }
    const typedHarnessParams: Record<string, unknown> = {};
    for (const [pname, text] of Object.entries(harnessParams)) {
      if (text.trim() === "") continue;
      const spec = harness?.parameter_schema.parameters[pname];
      typedHarnessParams[pname] =
        spec?.type === "integer" || spec?.type === "number"
          ? Number(text)
          : spec?.type === "boolean"
            ? text === "true"
            : text;
    }
    return {
      dataset_version_id: versionId,
      execution_mode: executionMode,
      task_selection:
        mode === "all_eligible"
          ? { mode }
          : { mode, task_ids: [...selected].sort() },
      ...(executionMode === "agent"
        ? {
            model_config_id: model?.id ?? null,
            harness_version_id: harness?.id ?? null,
            harness_params: typedHarnessParams,
          }
        : {}),
      repetitions: numberOrNull(overrides.repetitions),
      concurrency: numberOrNull(overrides.concurrency),
      run_deadline_hours: numberOrNull(overrides.run_deadline_hours),
      resources: {
        cpus: numberOrNull(overrides.cpus),
        memory_mb: numberOrNull(overrides.memory_mb),
      },
      timeouts: { agent_sec: numberOrNull(overrides.agent_sec) },
      parameters: params,
    };
  };

  const check = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const res = await api.post<ConfigResolution>(
        "config-resolutions",
        request(),
      );
      setResolution(res.data);
    } catch (err) {
      setError(err);
      setResolution(null);
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!resolution) return;
    setBusy(true);
    setError(undefined);
    const body: RunCreate = {
      name,
      resolution_id: resolution.resolution_id,
      client_request_id: clientRequestId || null,
    };
    try {
      const res = await api.post<RunAccepted>("runs", body, {
        "Idempotency-Key": key.current,
      });
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
        if (
          err instanceof ApiError &&
          err.code.startsWith("CONFIG_RESOLUTION_")
        )
          setResolution(null);
      }
    } finally {
      setBusy(false);
    }
  };

  const fieldErr = (field: string) =>
    error instanceof ApiError ? error.field(field) : undefined;
  const override = (
    field: keyof typeof overrides,
    label: string,
    hint: string,
  ) => (
    <TextField
      id={`run-${field}`}
      label={label}
      type="number"
      min={field === "cpus" ? 0.1 : 1}
      step={field === "cpus" ? 0.1 : 1}
      placeholder="继承"
      value={overrides[field]}
      onChange={(e) =>
        changed(setOverrides)({ ...overrides, [field]: e.target.value })
      }
      hint={hint}
      error={fieldErr(field)}
    />
  );

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
        <EmptyNote>
          还没有可用的数据集版本，请管理员先在“数据集”页添加。
        </EmptyNote>
      )}
      {versions.length > 0 && (
        <form className="grid gap-4" onSubmit={check}>
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
                  changed(setChosenVersion)(e.target.value);
                  setSelected(new Set());
                  setParameters({});
                }}
                error={fieldErr("dataset_version_id")}
              >
                {versions.map(({ dataset, version }) => (
                  <option key={version.id} value={version.id}>
                    {dataset.namespace}/{dataset.name} @ {version.upstream_ref}{" "}
                    ({version.status})
                  </option>
                ))}
              </SelectField>
              <fieldset className="grid gap-1 text-sm md:col-span-2">
                <legend className="mb-1">执行方式</legend>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="execution-mode"
                    checked={executionMode === "agent"}
                    onChange={() => changed(setExecutionMode)("agent")}
                  />
                  模型实验：由 Harness 驱动所选模型完成任务
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="execution-mode"
                    checked={executionMode === "oracle"}
                    onChange={() => changed(setExecutionMode)("oracle")}
                  />
                  Oracle
                  测试模式：执行任务自带的参考解法，不调用模型，不参与模型比较
                </label>
              </fieldset>
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

          {executionMode === "agent" && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">模型与 Harness</CardTitle>
                <CardDescription>
                  模型配置与 Harness 由管理员维护；这里只能选择。
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                {models.data && models.data.length === 0 && (
                  <EmptyNote>
                    还没有启用的模型配置，请管理员在“管理 → 模型”中添加。
                  </EmptyNote>
                )}
                {models.data && models.data.length > 0 && (
                  <SelectField
                    id="run-model"
                    label="模型"
                    value={model?.id ?? ""}
                    onChange={(e) => changed(setModelId)(e.target.value)}
                    error={fieldErr("model_config_id")}
                  >
                    {models.data.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name} — {m.model_id}（{m.provider}，修订 {m.revision}
                        ）{m.credential_problem ? " ⚠ 凭据不可用" : ""}
                      </option>
                    ))}
                  </SelectField>
                )}
                {model && compatible.length === 0 && (
                  <EmptyNote>没有能调用这个模型协议的 Harness 版本。</EmptyNote>
                )}
                {compatible.length > 0 && (
                  <SelectField
                    id="run-harness"
                    label="Harness"
                    value={harness?.id ?? ""}
                    onChange={(e) => {
                      changed(setHarnessId)(e.target.value);
                      setHarnessParams({});
                    }}
                    error={fieldErr("harness_version_id")}
                  >
                    {compatible.map((h) => (
                      <option key={h.id} value={h.id}>
                        {h.name} {h.version}（{h.agent}）
                      </option>
                    ))}
                  </SelectField>
                )}
                {harness &&
                  Object.entries(harness.parameter_schema.parameters ?? {}).map(
                    ([pname, spec]) => (
                      <TextField
                        key={pname}
                        id={`harness-param-${pname}`}
                        label={`Harness 参数 ${pname}（${spec.type}）`}
                        placeholder={
                          spec.default !== undefined
                            ? `默认 ${String(spec.default)}`
                            : "未设置"
                        }
                        value={harnessParams[pname] ?? ""}
                        onChange={(e) =>
                          changed(setHarnessParams)({
                            ...harnessParams,
                            [pname]: e.target.value,
                          })
                        }
                        hint={spec.description}
                      />
                    ),
                  )}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="text-base">规模与资源</CardTitle>
              <CardDescription>
                留空表示继承：次数、并发和总时限取团队默认，资源与时限取任务作者的设定。超过团队上限会被拒绝，不会被悄悄改小。
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-3">
              {override(
                "repetitions",
                "每任务重复次数",
                `团队默认 ${limit(capabilities, "repetitions_default", 1)}，上限 ${limit(capabilities, "repetitions_max", 20)}`,
              )}
              {override(
                "concurrency",
                "并发数",
                `团队默认 ${limit(capabilities, "run_default_concurrency", 4)}，上限 ${limit(capabilities, "run_max_concurrency", 10)}`,
              )}
              {override(
                "run_deadline_hours",
                "运行总时限（小时，含排队）",
                `团队默认 ${limit(capabilities, "run_deadline_hours", 72)}，上限 ${limit(capabilities, "run_deadline_hours_max", 72)}`,
              )}
              {override(
                "agent_sec",
                "Agent 时限（秒）",
                "留空用各任务作者的设定",
              )}
              {override(
                "cpus",
                "每试次 CPU",
                "留空用作者设定；只能调高，不能低于作者设定",
              )}
              {override(
                "memory_mb",
                "每试次内存（MiB）",
                "留空用作者设定；只能调高，不能低于作者设定",
              )}
            </CardContent>
          </Card>

          {declared.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">作者参数</CardTitle>
                <CardDescription>
                  任务作者声明的参数。秘密参数只能选一个团队凭据，不能直接填值；凭据由管理员维护，这里只显示名称。
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                {declared.map(([pname, info]) =>
                  info.sensitive ? (
                    <SelectField
                      key={pname}
                      id={`param-${pname}`}
                      label={`${pname}${info.required ? "（必填）" : ""}（秘密）`}
                      value={parameters[pname]?.value ?? ""}
                      onChange={(e) =>
                        changed(setParameters)({
                          ...parameters,
                          [pname]: { value: e.target.value, secret: true },
                        })
                      }
                      error={fieldErr(pname)}
                    >
                      <option value="">
                        {info.default != null ? "用作者默认值" : "选择凭据"}
                      </option>
                      {(credentials.data ?? []).map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}（{c.provider}）
                        </option>
                      ))}
                    </SelectField>
                  ) : (
                    <TextField
                      key={pname}
                      id={`param-${pname}`}
                      label={`${pname}${info.required ? "（必填）" : ""}`}
                      placeholder={
                        info.default != null ? `默认 ${info.default}` : ""
                      }
                      value={parameters[pname]?.value ?? ""}
                      onChange={(e) =>
                        changed(setParameters)({
                          ...parameters,
                          [pname]: { value: e.target.value, secret: false },
                        })
                      }
                      error={fieldErr(pname)}
                    />
                  ),
                )}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="text-base">任务选择</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3">
              {detail.data && (
                <p className="text-sm text-muted-foreground">
                  共 {detail.data.task_count} 个任务；已准入{" "}
                  {detail.data.admitted_task_count}； 可提交{" "}
                  {detail.data.submittable_task_count}。
                </p>
              )}
              <div className="flex flex-wrap gap-4 text-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="mode"
                    checked={mode === "all_eligible"}
                    onChange={() => changed(setMode)("all_eligible")}
                  />
                  全部可提交任务（{eligible.length}）
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="mode"
                    checked={mode === "explicit"}
                    onChange={() => changed(setMode)("explicit")}
                  />
                  手动选择（已选 {selected.size}）
                </label>
              </div>
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
                          <TableCell className="font-mono text-xs">
                            {task.task_key}
                            {task.required_parameters.length > 0 && (
                              <div className="text-[11px] text-muted-foreground">
                                需要参数：{task.required_parameters.join("、")}
                              </div>
                            )}
                          </TableCell>
                          <TaskStatusCells task={task} />
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>

          <ErrorAlert
            error={error}
            title={resolution ? "提交失败" : "检查失败"}
          />
          <div>
            <Button
              type="submit"
              variant={resolution ? "outline" : "default"}
              disabled={
                busy ||
                !versionId ||
                (mode === "explicit" && selected.size === 0)
              }
            >
              {busy && !resolution
                ? "检查中…"
                : resolution
                  ? "重新检查"
                  : "检查配置"}
            </Button>
          </div>

          {resolution && (
            <ResolutionReview
              resolution={resolution}
              busy={busy}
              pendingKey={pendingKey}
              canSubmit={name.trim() !== ""}
              onSubmit={() => void submit()}
            />
          )}
        </form>
      )}
    </div>
  );
}

const FIELD_LABEL: Record<string, string> = {
  "/repetitions": "每任务重复次数",
  "/concurrency": "并发数",
  "/run_deadline_hours": "运行总时限（小时）",
  "/resources/cpus": "每试次 CPU",
  "/resources/memory_mb": "每试次内存（MiB）",
  "/timeouts/agent_sec": "Agent 时限（秒）",
  "/timeouts/verifier_sec": "验证时限（秒）",
  "/model": "模型",
  "/harness": "Harness",
};

const TASK_FIELD: Record<string, string> = {
  "/resources/cpus": "cpus",
  "/resources/memory_mb": "memory_mb",
  "/timeouts/agent_sec": "agent_timeout_sec",
  "/timeouts/verifier_sec": "verifier_timeout_sec",
};

function ResolutionReview({
  resolution,
  busy,
  pendingKey,
  canSubmit,
  onSubmit,
}: {
  resolution: ConfigResolution;
  busy: boolean;
  pendingKey: string | null;
  canSubmit: boolean;
  onSubmit: () => void;
}) {
  const effective = resolution.effective_config;
  const value = (path: string): string => {
    if (!effective) return "—";
    if (path === "/model") return resolution.labels.model ?? "—";
    if (path === "/harness") return resolution.labels.harness ?? "—";
    const taskField = TASK_FIELD[path];
    if (taskField) {
      // Per-task values: one value when all tasks agree, otherwise the distinct ones.
      const values = new Set(
        (effective.tasks ?? []).map((task) => {
          const v = (task as Record<string, unknown>)[taskField];
          return v == null ? "执行器默认" : String(v);
        }),
      );
      return [...values].join(" / ") || "—";
    }
    let node: unknown = effective;
    for (const part of path.split("/").filter(Boolean)) {
      node = (node as Record<string, unknown> | undefined)?.[part];
    }
    if (node && typeof node === "object")
      return "value" in node ? String(node.value) : "（凭据）";
    return node == null ? "—" : String(node);
  };
  const blocked = resolution.blockers.length > 0;

  return (
    <Card className={blocked ? "border-destructive" : "border-emerald-400"}>
      <CardHeader>
        <CardTitle className="text-base">
          {blocked
            ? "配置有阻塞项，不能提交"
            : `检查通过：计划 ${resolution.planned_trials} 个试次`}
        </CardTitle>
        <CardDescription>
          结果在 {fmtTime(resolution.expires_at)}{" "}
          前有效，不预留容量或额度；提交时服务端会再核对一次，期间配置若有变化会要求重新检查。
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 text-sm">
        {blocked && (
          <ul className="grid gap-1">
            {resolution.blockers.map((b, i) => (
              <li key={`${b.path}-${b.code}-${i}`} className="text-destructive">
                <code className="text-xs">{b.path}</code>：
                {CONFIG_BLOCKER[b.code] ?? b.message}
                <span className="text-xs text-muted-foreground">
                  （{b.message}）
                </span>
              </li>
            ))}
          </ul>
        )}
        {resolution.warnings.map((w, i) => (
          <div
            key={i}
            className="rounded-md border border-amber-300 bg-amber-50 p-2 text-amber-900"
          >
            <code className="text-xs">{w.path}</code>：{w.message}
          </div>
        ))}
        {effective && (
          <div className="overflow-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>字段</TableHead>
                  <TableHead>生效值</TableHead>
                  <TableHead>来源</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(resolution.field_sources).map(
                  ([path, source]) => (
                    <TableRow key={path}>
                      <TableCell>
                        {FIELD_LABEL[path] ?? (
                          <code className="text-xs">{path}</code>
                        )}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {value(path)}
                      </TableCell>
                      <TableCell>
                        <Pill
                          tone={source.layer === "override" ? "warn" : "muted"}
                        >
                          {SOURCE_LAYER[source.layer] ?? source.layer}
                          {source.revision != null
                            ? ` · 修订 ${source.revision}`
                            : ""}
                        </Pill>
                      </TableCell>
                    </TableRow>
                  ),
                )}
              </TableBody>
            </Table>
          </div>
        )}
        {resolution.baseline_differences.length > 0 && (
          <p className="text-muted-foreground">
            与作者基准不同：
            {resolution.baseline_differences
              .map(
                (d) =>
                  `${FIELD_LABEL[d.path] ?? d.path} = ${d.value}（低于作者 ${d.tasks_lower} 个任务，高于 ${d.tasks_higher} 个）`,
              )
              .join("；")}
          </p>
        )}
        {resolution.excluded_tasks.length > 0 && (
          <div>
            <p className="font-medium">
              不会运行的任务（{resolution.excluded_tasks.length}）
            </p>
            <ul className="mt-1 grid gap-1 text-xs">
              {resolution.excluded_tasks.map((x) => (
                <li key={x.task_id}>
                  <code>{x.task_key}</code>：
                  {x.blockers.map(blockerText).join("；")}
                </li>
              ))}
            </ul>
          </div>
        )}
        {resolution.required_preparation.length > 0 && (
          <p className="text-muted-foreground">
            {resolution.required_preparation.length}{" "}
            个任务的本机缓存不在，运行开始前会自动恢复，无需管理员操作。
          </p>
        )}
        <JsonBlock
          value={resolution.effective_config}
          summary="完整生效配置（JSON）"
        />
        <p className="font-mono text-xs text-muted-foreground">
          配置摘要 {resolution.config_digest}
        </p>
        {pendingKey && (
          <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-900">
            上次提交结果未知（网络或服务端错误）。再次提交会复用同一幂等键，不会重复创建运行。
            <Pill tone="muted">Idempotency-Key {pendingKey.slice(0, 8)}…</Pill>
          </div>
        )}
        <div>
          <Button
            type="button"
            disabled={busy || blocked || !canSubmit}
            onClick={onSubmit}
          >
            {busy ? "提交中…" : pendingKey ? "重试提交" : "按此配置提交运行"}
          </Button>
          {!canSubmit && (
            <span className="ml-2 text-xs text-muted-foreground">
              先填写运行名称
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

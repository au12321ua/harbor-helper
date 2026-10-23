// Administrator tabs for model configurations, harness versions and the team policy (03).
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
  Pill,
  SelectField,
  TextField,
} from "@/components/common";
import { ApiError, api } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { useLoad } from "@/lib/hooks";
import type {
  Credential,
  Harness,
  HarnessAdapter,
  ModelConfig,
  ModelProtocol,
  PolicySetting,
  TeamPolicy,
} from "@/lib/types";

const PROTOCOLS: [ModelProtocol, string][] = [
  ["openai-compatible", "OpenAI 兼容（Chat Completions）"],
  ["openai", "OpenAI Responses"],
  ["anthropic", "Anthropic Messages"],
];

function protocolLabel(value: string) {
  return PROTOCOLS.find(([key]) => key === value)?.[1] ?? value;
}

function parseJson(text: string, what: string): Record<string, unknown> {
  if (!text.trim()) return {};
  try {
    const value = JSON.parse(text);
    if (value && typeof value === "object" && !Array.isArray(value)) return value;
  } catch {
    // fall through
  }
  throw new Error(`${what}必须是 JSON 对象`);
}

// --- model configurations -----------------------------------------------------------------

interface ModelForm {
  name: string;
  provider: string;
  protocol: ModelProtocol;
  endpoint: string;
  model_id: string;
  params: string;
  credential_id: string;
  description: string;
}

const EMPTY_MODEL: ModelForm = {
  name: "",
  provider: "",
  protocol: "openai-compatible",
  endpoint: "",
  model_id: "",
  params: "{}",
  credential_id: "",
  description: "",
};

export function ModelsTab() {
  const models = useLoad(
    async () => (await api.get<ModelConfig[]>("model-configs", { include_disabled: "true" })).data,
  );
  const credentials = useLoad(async () => (await api.get<Credential[]>("admin/credentials")).data);
  const [editing, setEditing] = useState<ModelConfig | null>(null);
  const [form, setForm] = useState<ModelForm>(EMPTY_MODEL);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const keys = (credentials.data ?? []).filter((c) => c.kind === "model_api_key");

  const edit = (model: ModelConfig | null) => {
    setEditing(model);
    setError(undefined);
    setForm(
      model
        ? {
            name: model.name,
            provider: model.provider,
            protocol: model.protocol,
            endpoint: model.endpoint,
            model_id: model.model_id,
            params: JSON.stringify(model.params, null, 2),
            credential_id: model.credential_id ?? "",
            description: model.description,
          }
        : EMPTY_MODEL,
    );
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const body = {
        provider: form.provider.trim(),
        protocol: form.protocol,
        endpoint: form.endpoint.trim(),
        model_id: form.model_id.trim(),
        params: parseJson(form.params, "请求参数"),
        credential_id: form.credential_id || null,
        description: form.description,
      };
      if (editing) {
        await api.put(`admin/model-configs/${editing.id}`, {
          ...body,
          expected_revision: editing.revision,
        });
        toast.success(`${editing.name} 已保存为新修订；已受理的运行不受影响`);
      } else {
        await api.post("admin/model-configs", { ...body, name: form.name.trim() });
        toast.success("模型配置已创建");
      }
      edit(null);
      await models.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setError(undefined);
    try {
      await fn();
      toast.success(done);
      await models.reload();
    } catch (err) {
      setError(err);
    }
  };
  const fieldErr = (name: string) => (error instanceof ApiError ? error.field(name) : undefined);

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">模型配置</CardTitle>
          <CardDescription>
            说明怎样调用一个模型：调用协议、服务地址、模型标识和请求参数。密钥只能绑定团队凭据，不能写进参数或地址。
            修改会生成新修订，已受理的运行继续使用受理时的修订。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm">
          {models.loading && !models.data && <Loading />}
          <ErrorAlert error={models.error} />
          {models.data && models.data.length === 0 && <EmptyNote>还没有模型配置。</EmptyNote>}
          {models.data && models.data.length > 0 && (
            <div className="overflow-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>名称</TableHead>
                    <TableHead>提供商 / 协议</TableHead>
                    <TableHead>模型</TableHead>
                    <TableHead>凭据</TableHead>
                    <TableHead>修订</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {models.data.map((m) => (
                    <TableRow key={m.id}>
                      <TableCell className="font-medium">{m.name}</TableCell>
                      <TableCell>
                        <div className="font-mono text-xs">{m.provider}</div>
                        <div className="text-xs text-muted-foreground">{protocolLabel(m.protocol)}</div>
                      </TableCell>
                      <TableCell>
                        <div className="font-mono text-xs">{m.model_id}</div>
                        <div className="max-w-64 truncate text-xs text-muted-foreground" title={m.endpoint}>
                          {m.endpoint}
                        </div>
                      </TableCell>
                      <TableCell>
                        {m.credential_name ?? (m.credential_bound ? "已绑定" : "无")}
                        {m.credential_problem && (
                          <Pill tone="bad" title="新运行会被阻止">
                            {m.credential_problem}
                          </Pill>
                        )}
                      </TableCell>
                      <TableCell className="tabular-nums">{m.revision}</TableCell>
                      <TableCell>
                        <Pill tone={m.enabled ? "good" : "muted"}>{m.enabled ? "启用" : "停用"}</Pill>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right">
                        <Button size="sm" variant="outline" onClick={() => edit(m)}>
                          修改
                        </Button>{" "}
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            void act(
                              () =>
                                api.post(`admin/model-configs/${m.id}/enabled`, {
                                  enabled: !m.enabled,
                                }),
                              m.enabled ? "已停用：新运行不能再选择它" : "已启用",
                            )
                          }
                        >
                          {m.enabled ? "停用" : "启用"}
                        </Button>{" "}
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            void act(
                              () => api.del(`admin/model-configs/${m.id}`),
                              "已移入回收站",
                            )
                          }
                        >
                          删除
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{editing ? `修改 ${editing.name}` : "新建模型配置"}</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="grid gap-3 md:grid-cols-2" onSubmit={save}>
            {!editing && (
              <TextField
                id="model-name"
                label="名称"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                error={fieldErr("name")}
                required
              />
            )}
            <TextField
              id="model-provider"
              label="提供商（并发上限按它计算）"
              value={form.provider}
              onChange={(e) => setForm({ ...form, provider: e.target.value })}
              error={fieldErr("provider")}
              required
            />
            <SelectField
              id="model-protocol"
              label="调用协议"
              value={form.protocol}
              onChange={(e) => setForm({ ...form, protocol: e.target.value as ModelProtocol })}
            >
              {PROTOCOLS.map(([value, text]) => (
                <option key={value} value={value}>
                  {text}
                </option>
              ))}
            </SelectField>
            <TextField
              id="model-endpoint"
              label="服务地址（http/https，不含密钥或查询参数）"
              value={form.endpoint}
              onChange={(e) => setForm({ ...form, endpoint: e.target.value })}
              error={fieldErr("endpoint")}
              required
            />
            <TextField
              id="model-id"
              label="模型标识"
              value={form.model_id}
              onChange={(e) => setForm({ ...form, model_id: e.target.value })}
              error={fieldErr("model_id")}
              required
            />
            <SelectField
              id="model-credential"
              label="凭据（模型 API 密钥）"
              value={form.credential_id}
              onChange={(e) => setForm({ ...form, credential_id: e.target.value })}
              error={fieldErr("credential_id")}
            >
              <option value="">不需要密钥</option>
              {keys.map((c) => (
                <option key={c.id} value={c.id} disabled={!c.enabled}>
                  {c.name}
                  {c.enabled ? "" : "（已停用）"}
                </option>
              ))}
            </SelectField>
            <label className="grid gap-1 text-sm md:col-span-2" htmlFor="model-params">
              <span>请求参数（JSON 对象，例如 {"{\"temperature\": 0}"}）</span>
              <textarea
                id="model-params"
                className="min-h-24 rounded-md border bg-background p-2 font-mono text-xs"
                value={form.params}
                onChange={(e) => setForm({ ...form, params: e.target.value })}
              />
              {fieldErr("params") && <span className="text-xs text-destructive">{fieldErr("params")}</span>}
            </label>
            <TextField
              id="model-description"
              label="说明（可选）"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
            <div className="flex items-end gap-2">
              <Button type="submit" disabled={busy}>
                {editing ? "保存为新修订" : "创建"}
              </Button>
              {editing && (
                <Button type="button" variant="outline" onClick={() => edit(null)}>
                  取消
                </Button>
              )}
            </div>
          </form>
          <div className="mt-3">
            <ErrorAlert error={error} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// --- harness versions -----------------------------------------------------------------------

export function HarnessesTab() {
  const harnesses = useLoad(async () => (await api.get<Harness[]>("harness-versions")).data);
  const adapters = useLoad(async () => (await api.get<HarnessAdapter[]>("admin/harness-adapters")).data);
  const [form, setForm] = useState({
    name: "",
    version: "",
    agent: "",
    protocols: [] as ModelProtocol[],
    schema: '{\n  "parameters": {}\n}',
    description: "",
  });
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const agent = form.agent || adapters.data?.[0]?.agent || "";
  const adapter = adapters.data?.find((a) => a.agent === agent);
  const supported = adapter?.protocols ?? [];

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await api.post("admin/harness-versions", {
        name: form.name.trim(),
        version: form.version.trim(),
        agent,
        protocols: form.protocols.filter((p) => supported.includes(p)),
        parameter_schema: parseJson(form.schema, "参数定义"),
        description: form.description,
      });
      toast.success("Harness 版本已发布；之后内容不能修改，修改需发布新版本");
      setForm({ ...form, version: "" });
      await harnesses.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setError(undefined);
    try {
      await fn();
      toast.success(done);
      await harnesses.reload();
    } catch (err) {
      setError(err);
    }
  };
  const fieldErr = (name: string) => (error instanceof ApiError ? error.field(name) : undefined);

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Harness 版本</CardTitle>
          <CardDescription>
            Harness 是驱动模型完成任务的程序。每个版本发布后内容固定；执行器以适配器实现它，并声明能调用哪些协议的模型。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm">
          {harnesses.loading && !harnesses.data && <Loading />}
          <ErrorAlert error={harnesses.error} />
          {harnesses.data && harnesses.data.length === 0 && <EmptyNote>还没有发布 Harness 版本。</EmptyNote>}
          {harnesses.data && harnesses.data.length > 0 && (
            <div className="overflow-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>名称与版本</TableHead>
                    <TableHead>适配器</TableHead>
                    <TableHead>协议</TableHead>
                    <TableHead>参数</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {harnesses.data.map((h) => (
                    <TableRow key={h.id}>
                      <TableCell>
                        <span className="font-medium">{h.name}</span>{" "}
                        <span className="font-mono text-xs">{h.version}</span>
                        <div className="font-mono text-[11px] text-muted-foreground" title={h.content_digest}>
                          {h.content_digest.slice(0, 19)}…
                        </div>
                      </TableCell>
                      <TableCell className="font-mono text-xs">{h.agent}</TableCell>
                      <TableCell className="text-xs">{h.protocols.map(protocolLabel).join("、")}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {Object.keys(h.parameter_schema.parameters ?? {}).join(", ") || "—"}
                      </TableCell>
                      <TableCell>
                        <Pill tone={h.enabled ? "good" : "muted"}>{h.enabled ? "启用" : "停用"}</Pill>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            void act(
                              () => api.post(`admin/harness-versions/${h.id}/enabled`, { enabled: !h.enabled }),
                              h.enabled ? "已停用" : "已启用",
                            )
                          }
                        >
                          {h.enabled ? "停用" : "启用"}
                        </Button>{" "}
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => void act(() => api.del(`admin/harness-versions/${h.id}`), "已移入回收站")}
                        >
                          删除
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">发布新版本</CardTitle>
          {adapters.data && adapters.data.length === 0 && (
            <CardDescription>当前执行器还没有可用的 Harness 适配器，暂时不能发布。</CardDescription>
          )}
        </CardHeader>
        <CardContent>
          <form className="grid gap-3 md:grid-cols-2" onSubmit={create}>
            <TextField
              id="harness-name"
              label="名称"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              error={fieldErr("name")}
              required
            />
            <TextField
              id="harness-version"
              label="版本"
              value={form.version}
              onChange={(e) => setForm({ ...form, version: e.target.value })}
              error={fieldErr("version")}
              required
            />
            <SelectField
              id="harness-agent"
              label="执行器适配器"
              value={agent}
              onChange={(e) => setForm({ ...form, agent: e.target.value, protocols: [] })}
              error={fieldErr("agent")}
            >
              {(adapters.data ?? []).map((a) => (
                <option key={a.agent} value={a.agent}>
                  {a.agent}
                </option>
              ))}
            </SelectField>
            <fieldset className="grid gap-1 text-sm">
              <legend className="mb-1">可调用的协议</legend>
              {supported.map((p) => (
                <label key={p} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={form.protocols.includes(p)}
                    onChange={() =>
                      setForm({
                        ...form,
                        protocols: form.protocols.includes(p)
                          ? form.protocols.filter((x) => x !== p)
                          : [...form.protocols, p],
                      })
                    }
                  />
                  {protocolLabel(p)}
                </label>
              ))}
              {fieldErr("protocols") && <span className="text-xs text-destructive">{fieldErr("protocols")}</span>}
            </fieldset>
            <label className="grid gap-1 text-sm md:col-span-2" htmlFor="harness-schema">
              <span>
                参数定义（JSON）：{"{\"parameters\": {\"max_turns\": {\"type\": \"integer\", \"default\": 30}}}"}
              </span>
              {adapter?.parameters && (
                <span className="text-xs text-muted-foreground">
                  这个适配器可声明的参数：{adapter.parameters.join("、")}
                </span>
              )}
              <textarea
                id="harness-schema"
                className="min-h-24 rounded-md border bg-background p-2 font-mono text-xs"
                value={form.schema}
                onChange={(e) => setForm({ ...form, schema: e.target.value })}
              />
            </label>
            <TextField
              id="harness-description"
              label="说明（可选）"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
            <div className="flex items-end">
              <Button type="submit" disabled={busy || !agent || form.protocols.length === 0}>
                发布
              </Button>
            </div>
          </form>
          <div className="mt-3">
            <ErrorAlert error={error} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// --- team policy ------------------------------------------------------------------------------

const GROUPS: [PolicySetting["group"], string][] = [
  ["runs", "运行规模与时限"],
  ["access", "访问令牌、邀请与登录"],
  ["retention", "保留与导出"],
];

const SETTING_LABEL: Record<string, string> = {
  repetitions_default: "每任务重复次数（默认）",
  repetitions_max: "每任务重复次数（上限）",
  run_default_concurrency: "运行并发（默认）",
  run_max_concurrency: "运行并发（上限）",
  run_deadline_hours: "运行总时限，小时（默认）",
  run_deadline_hours_max: "运行总时限，小时（上限）",
  run_max_tasks: "单个运行的任务数上限",
  run_max_trials: "单个运行的试次数上限",
  trial_cpus_max: "单个试次 CPU 上限",
  trial_memory_mb_max: "单个试次内存上限（MiB）",
  agent_timeout_sec_max: "单个试次 Agent 时限上限（秒）",
  batch_max_runs: "单个批次的运行数上限",
  batch_max_trials: "单个批次的试次数上限",
  pat_default_days: "访问令牌有效期，天（默认）",
  pat_max_days: "访问令牌有效期，天（上限）",
  pat_default_run_limit: "访问令牌可提交运行数（默认）",
  pat_max_run_limit: "访问令牌可提交运行数（上限）",
  invitation_hours: "邀请有效期（小时）",
  login_attempts_per_minute: "每账户每地址每分钟允许的登录失败次数",
  artifact_ttl_days: "原始产物保留天数",
  export_ttl_hours: "导出包保留小时数",
  export_max_runs: "单次导出的运行数上限",
  export_max_active_per_user: "每人同时进行中的导出数",
};

export function PolicyTab() {
  const policy = useLoad(async () => (await api.get<TeamPolicy>("team-policy")).data);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const data = policy.data;

  const changed = data
    ? Object.fromEntries(
        Object.entries(draft)
          .filter(([name, text]) => text.trim() !== "" && Number(text) !== data.values[name])
          .map(([name, text]) => [name, Number(text)]),
      )
    : {};

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!data) return;
    setBusy(true);
    setError(undefined);
    try {
      await api.put("admin/team-policy", { values: changed, expected_revision: data.revision });
      toast.success("已保存为新修订；对之后的新提交生效，已受理的运行不变");
      setDraft({});
      await policy.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">团队策略</CardTitle>
        <CardDescription>
          团队默认值与硬上限。每次保存生成一个新修订，只影响之后的新提交；超过上限的配置会被拒绝，不会被悄悄改小。
          与机器和磁盘有关的上限在部署配置 config.toml 中。
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 text-sm">
        {policy.loading && !data && <Loading />}
        <ErrorAlert error={policy.error} />
        {data && (
          <form className="grid gap-4" onSubmit={save}>
            <p className="text-muted-foreground">
              当前修订 {data.revision}
              {data.revision === 0 ? "（内置初值，尚未修改过）" : ""}
            </p>
            {GROUPS.map(([group, title]) => (
              <div key={group} className="grid gap-2">
                <h3 className="font-medium">{title}</h3>
                <div className="grid gap-x-4 gap-y-2 md:grid-cols-2">
                  {data.settings
                    .filter((s) => s.group === group)
                    .map((s) => (
                      <TextField
                        key={s.name}
                        id={`policy-${s.name}`}
                        label={SETTING_LABEL[s.name] ?? s.description}
                        type="number"
                        min={s.min}
                        max={s.max}
                        value={draft[s.name] ?? String(data.values[s.name])}
                        onChange={(e) => setDraft({ ...draft, [s.name]: e.target.value })}
                        hint={`内置 ${s.built_in}，范围 ${s.min}–${s.max}`}
                        error={error instanceof ApiError ? error.field(s.name) : undefined}
                      />
                    ))}
                </div>
              </div>
            ))}
            <div className="flex items-center gap-3">
              <Button type="submit" disabled={busy || Object.keys(changed).length === 0}>
                保存（{Object.keys(changed).length} 项改动）
              </Button>
              {Object.keys(draft).length > 0 && (
                <Button type="button" variant="outline" onClick={() => setDraft({})}>
                  放弃改动
                </Button>
              )}
            </div>
            <ErrorAlert error={error} />
          </form>
        )}
        <PolicyHistory revision={data?.revision} />
      </CardContent>
    </Card>
  );
}

function PolicyHistory({ revision }: { revision?: number }) {
  const history = useLoad(
    async () =>
      (
        await api.get<{ revision: number; values: Record<string, number>; created_by_username: string; created_at: string }[]>(
          "admin/team-policy/revisions",
        )
      ).data,
    [revision],
  );
  if (!history.data || history.data.length === 0) return null;
  return (
    <details>
      <summary className="cursor-pointer font-medium">修订历史（{history.data.length}）</summary>
      <ul className="mt-2 grid gap-1 text-xs text-muted-foreground">
        {history.data.map((h) => (
          <li key={h.revision}>
            修订 {h.revision} · {h.created_by_username} · {fmtTime(h.created_at)}
          </li>
        ))}
      </ul>
    </details>
  );
}

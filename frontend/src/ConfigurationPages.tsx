import { useLoad } from "./useLoad";
import { useState } from "react";
import { LoaderCircle } from "lucide-react";
import { api, post, date, type Item } from "./api";
import { ErrorNotice, Title, SelectField, Loading, EmptyState } from "./shared";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Field,
  FieldLabel,
  FieldGroup,
  FieldDescription,
} from "@/components/ui/field";
import { toast } from "sonner";
import { MaintenancePanel } from "./ReadinessPanel";
const limitLabels: Record<string, string> = {
  max_jobs: "全局任务并发",
  max_trials: "全局 Trial 并发",
  max_queue: "全局待处理上限（准备中与排队）",
  max_pending_per_member: "每成员待处理额度（有效值不超过全局上限）",
  max_wall_seconds: "实验总时长上限（秒，含准备）",
  max_attempts: "每任务最大尝试数",
  max_cpus_per_trial: "每 Trial CPU 上限",
  max_memory_mb_per_trial: "每 Trial 内存 MB",
  max_upload_bytes: "最大上传字节数",
  log_retention_days: "日志保留天数",
  artifact_retention_days: "产物保留天数",
};
function rowsOf(value: Item | Item[] | undefined, key: string): Item[] {
  return Array.isArray(value) ? value : value?.[key] || [];
}
function AdminForm({
  title,
  description,
  fields,
  onSave,
  resetOnSave = true,
}: {
  title: string;
  description: string;
  fields: {
    name: string;
    label: string;
    type?: string;
    options?: { value: string; label: string }[];
    defaultValue?: string;
    required?: boolean;
    copyTo?: string;
    description?: string;
  }[];
  onSave: (value: Item) => Promise<unknown>;
  resetOnSave?: boolean;
}) {
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false),
    [saved, setSaved] = useState(false);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const form = e.currentTarget;
            setBusy(true);
            setError(undefined);
            setSaved(false);
            const value = Object.fromEntries(new FormData(form));
            try {
              await onSave(value);
              if (resetOnSave) form.reset();
              toast.success("配置已保存");
              setSaved(true);
            } catch (err) {
              setError(err);
            } finally {
              const secrets = form.querySelectorAll<HTMLInputElement>(
                'input[type="password"]',
              );
              secrets.forEach((input) => {
                input.value = "";
              });
              setBusy(false);
            }
          }}
        >
          <fieldset disabled={busy} aria-busy={busy} className="min-w-0">
            <FieldGroup>
              {fields.map((f) => (
                <Field key={f.name}>
                  <FieldLabel htmlFor={`${title}-${f.name}`}>
                    {f.label}
                  </FieldLabel>
                  {f.options ? (
                    <select
                      id={`${title}-${f.name}`}
                      name={f.name}
                      required={f.required !== false}
                      defaultValue={f.defaultValue || ""}
                      onChange={
                        f.copyTo
                          ? (e) => {
                              const target =
                                e.currentTarget.form?.elements.namedItem(
                                  f.copyTo!,
                                );
                              if (
                                target instanceof HTMLInputElement &&
                                e.currentTarget.value
                              )
                                target.value = e.currentTarget.value;
                            }
                          : undefined
                      }
                    >
                      {!f.defaultValue ? (
                        <option value="">请选择</option>
                      ) : null}
                      {f.options.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  ) : f.type === "textarea" ? (
                    <Textarea
                      id={`${title}-${f.name}`}
                      name={f.name}
                      required={f.required !== false}
                      defaultValue={f.defaultValue}
                    />
                  ) : (
                    <Input
                      id={`${title}-${f.name}`}
                      name={f.name}
                      type={f.type || "text"}
                      step={f.type === "number" ? "any" : undefined}
                      required={f.required !== false}
                      defaultValue={f.defaultValue}
                      autoComplete={
                        f.type === "password" ? "new-password" : "off"
                      }
                    />
                  )}
                  {f.description ? (
                    <p className="text-sm text-muted-foreground">
                      {f.description}
                    </p>
                  ) : null}
                </Field>
              ))}
              <ErrorNotice error={error} />
              {saved ? (
                <p role="status">保存完成；下方状态以当前配置为准。</p>
              ) : null}
              <Button disabled={busy} type="submit">
                {busy ? (
                  <LoaderCircle
                    data-icon="inline-start"
                    className="animate-spin"
                  />
                ) : null}
                保存
              </Button>
            </FieldGroup>
          </fieldset>
        </form>
      </CardContent>
    </Card>
  );
}
function ModelForm({
  catalog,
  selected,
  save,
  onSaved,
}: {
  catalog: Item;
  selected?: Item;
  save: (path: string, value: Item) => Promise<Item>;
  onSaved: (value: Item) => void;
}) {
  const [provider, setProvider] = useState(selected?.provider_id || "");
  const credentials = (catalog.credentials || []).filter(
    (c: Item) => c.provider_id === provider && c.enabled,
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{selected ? "编辑模型方案" : "添加模型方案"}</CardTitle>
        <CardDescription>
          按名称绑定提供商与团队
          key。保存只检查配置与可解密性，不代表真实认证或推理成功。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <SelectField
          label="提供商"
          name="model-provider"
          value={provider}
          onChange={setProvider}
        >
          <option value="">选择提供商</option>
          {(catalog.providers || []).map((p: Item) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </SelectField>
        {provider && !credentials.length ? (
          <Alert>
            <AlertDescription>
              该提供商暂无启用的团队 key，请先添加或启用凭据再保存方案。
            </AlertDescription>
          </Alert>
        ) : null}
        <AdminForm
          key={`${selected?.id || "new"}-${provider}`}
          resetOnSave={!selected}
          title="模型配置"
          description="常用参数可留空；JSON 高级参数与常用参数合并。已有实验保留旧版本。"
          fields={[
            { name: "name", label: "方案名称", defaultValue: selected?.name },
            {
              name: "credential_id",
              label: "团队 key",
              defaultValue:
                selected?.provider_id === provider
                  ? selected?.credential_id
                  : undefined,
              options: credentials.map((c: Item) => ({
                value: c.id,
                label: `${(catalog.providers || []).find((p: Item) => p.id === c.provider_id)?.name || c.provider_id} → ${c.label}`,
              })),
            },
            {
              name: "model",
              label: "供应商模型名称",
              defaultValue: selected?.model,
            },
            {
              name: "temperature",
              label: "Temperature（可选）",
              type: "number",
              required: false,
              defaultValue: String(selected?.params?.temperature ?? ""),
            },
            {
              name: "max_tokens",
              label: "最大输出 tokens（可选）",
              type: "number",
              required: false,
              defaultValue: String(selected?.params?.max_tokens ?? ""),
            },
            {
              name: "params",
              label: "高级参数 JSON",
              type: "textarea",
              defaultValue: JSON.stringify(selected?.params || {}),
            },
            {
              name: "opencode_version",
              label: "OpenCode 版本",
              defaultValue: selected?.opencode_version || "1.18.35",
            },
          ]}
          onSave={async (v) => {
            const params = JSON.parse(v.params);
            if (!params || Array.isArray(params) || typeof params !== "object")
              throw new Error("参数须为 JSON 对象");
            if (v.temperature !== "")
              params.temperature = Number(v.temperature);
            if (v.max_tokens !== "") params.max_tokens = Number(v.max_tokens);
            const saved = await save("/admin/model-profiles", {
              id: selected?.id,
              name: v.name,
              provider_id: provider,
              credential_id: v.credential_id,
              model: v.model,
              params,
              opencode_version: v.opencode_version,
              enabled: selected?.enabled ?? true,
            });
            onSaved(saved);
          }}
        />
      </CardContent>
    </Card>
  );
}
function AuthorInputs({
  dataset,
  save,
  check,
  docker,
}: {
  dataset: Item;
  save: (path: string, value: Item, method?: string) => Promise<Item>;
  check: (path: string, value?: Item) => void;
  docker?: Item;
}) {
  const [taskNames, setTaskNames] = useState<string[]>([]);
  const parameters = dataset.author_parameters || {};
  const variables = parameters.discovery?.variables || {};
  return (
    <div className="flex flex-col gap-3">
      <p>
        作者运行参数 · v{parameters.version || 0} ·{" "}
        {parameters.status === "checked"
          ? "运行参数已检查"
          : parameters.status?.startsWith("partial_")
            ? "部分任务已检查（不代表全集就绪）"
            : parameters.status === "blocked"
              ? "检查失败"
              : parameters.status === "missing"
                ? "缺配置"
                : "尚未检查"}
        {parameters.checked ? ` · ${date(parameters.checked)}` : ""}
      </p>
      <p className="text-sm text-muted-foreground">
        仅非秘密：值进入任务快照、Job与报告，agent可见。此检查只检查输入，不证明构建、评分或模型可用。保存参数不改变来源验证。
      </p>
      {parameters.source ? (
        <p className="break-all text-sm">检查来源：{parameters.source}</p>
      ) : null}
      <Button
        variant="outline"
        disabled={!dataset.ready}
        onClick={() =>
          check(`/admin/datasets/${dataset.id}/author-inputs/check`)
        }
      >
        检查作者参数
      </Button>
      <Field>
        <FieldLabel htmlFor={`check-tasks-${dataset.id}`}>
          检查任务（可多选）
        </FieldLabel>
        <select
          id={`check-tasks-${dataset.id}`}
          multiple
          value={taskNames}
          onChange={(e) =>
            setTaskNames(
              Array.from(e.target.selectedOptions, (option) => option.value),
            )
          }
        >
          {(dataset.tasks || []).map((task: Item) => (
            <option key={task.name} value={task.name}>
              {task.name}
            </option>
          ))}
        </select>
        <FieldDescription>
          选定检查只下载所选任务；未选任务仍未知。上方按钮保留全部任务检查。
        </FieldDescription>
      </Field>
      <Button
        variant="outline"
        disabled={!dataset.ready || !taskNames.length}
        onClick={() =>
          check(`/admin/datasets/${dataset.id}/author-inputs/check`, {
            task_names: taskNames,
          })
        }
      >
        检查选定任务
      </Button>
      {parameters.scope ? (
        <p>
          检查范围：{parameters.scope.complete ? "全集" : "部分任务"} · 已扫描{" "}
          {parameters.scope.tasks.length}/{parameters.scope.total} · 另有{" "}
          {parameters.scope.unknown} 个任务未扫描
        </p>
      ) : null}
      {parameters.issues?.map((issue: Item, index: number) => (
        <Alert key={index} variant="destructive">
          <AlertDescription>
            {issue.task}：{issue.variables.join("、")} ·{" "}
            {issue.reason === "host_template_unsupported"
              ? "宿主模板暂不支持网页赋值"
              : issue.reason}
          </AlertDescription>
        </Alert>
      ))}
      {parameters.discovery?.images?.map((image: Item, index: number) => (
        <p key={index}>
          {image.task} / {image.role}：作者预构建镜像 {image.reference} ·{" "}
          {image.cached === true
            ? "本机已缓存（不证明兼容）"
            : image.cached === false
              ? "本机未缓存；Harbor会向registry获取，检查部署出网与启动阶段"
              : "本机缓存状态未知"}
          。该提示不阻止提交，不修改作者网络。
        </p>
      ))}
      {parameters.discovery ? (
        <>
          {Object.keys(variables).length ? (
            <AdminForm
              key={`${dataset.id}-${parameters.version}`}
              title="作者运行参数"
              description="字段来自已校验作者Compose。留空沿作者默认，必需项留空将阻止受理准备。两侧镜像分别消费各自字段；Oracle可检查作者环境与评分。"
              resetOnSave={false}
              fields={Object.entries(variables).flatMap(([name, raw]) => {
                const uses = raw as Item[];
                const imageOptions = (docker?.images || []).flatMap(
                  (image: Item) =>
                    (image.reference
                      ? [image.reference]
                      : image.tags || image.repo_tags || []
                    )
                      .filter((tag: string) => tag !== "<none>:<none>")
                      .map((tag: string) => ({ value: tag, label: tag })),
                );
                return [
                  ...(name.includes("IMAGE") && imageOptions.length
                    ? [
                        {
                          name: `${name}-inventory`,
                          label: `${name} · 本机镜像（可选）`,
                          required: false,
                          options: imageOptions,
                          copyTo: name,
                        },
                      ]
                    : []),
                  {
                    name,
                    label: name,
                    required: false,
                    defaultValue: parameters.values?.[name] || "",
                    description: uses
                      .map(
                        (use) =>
                          `${use.task} / ${use.file}：${use.required ? "必需" : `可选，作者默认 ${use.default || "空"}`}`,
                      )
                      .join("；"),
                  },
                ];
              })}
              onSave={async (value) => {
                const values = Object.fromEntries(
                  Object.keys(variables)
                    .filter((name) => value[name])
                    .map((name) => [name, value[name]]),
                );
                return save(
                  `/admin/datasets/${dataset.id}/author-inputs`,
                  { values },
                  "PUT",
                );
              }}
            />
          ) : (
            <p>
              已扫描任务没有可网页配置的外部Compose变量；其余任务仍需执行前完整校验。
            </p>
          )}
          <p>
            作者预算：
            {parameters.discovery.budgets
              ?.map(
                (budget: Item) =>
                  `${budget.task}：agent ${budget.agent_seconds}秒 + verifier ${budget.verifier_seconds}秒`,
              )
              .join("；")}
            。预算估算仅单task，重复尝试/多任务另需余量；总时长还需包含环境与工具准备。
          </p>
        </>
      ) : null}
    </div>
  );
}

export function Admin() {
  const { data, error, loading, reload } = useLoad(() =>
    Promise.all([api("/admin/users"), api("/catalog")]),
  );
  const [tab, setTab] = useState("readiness"),
    [edit, setEdit] = useState<Item>({}),
    [rotation, setRotation] = useState(""),
    [reset, setReset] = useState<Item>(),
    [saving, setSaving] = useState(false),
    [hubNotice, setHubNotice] = useState(""),
    [hubError, setHubError] = useState<unknown>(),
    [docker, setDocker] = useState<Item>(),
    [dockerBusy, setDockerBusy] = useState(false),
    [dockerError, setDockerError] = useState<unknown>(),
    [providerFilter, setProviderFilter] = useState(""),
    [keyFilter, setKeyFilter] = useState("");
  if (loading) return <Loading />;
  const users = rowsOf(data?.[0], "users"),
    c = data?.[1] || {};
  const visibleProviders = (c.providers || []).filter(
    (p: Item) => !providerFilter || p.id === providerFilter,
  );
  const visibleKeys = (c.credentials || []).filter(
    (k: Item) =>
      (!providerFilter || k.provider_id === providerFilter) &&
      (!keyFilter || k.id === keyFilter),
  );
  const visibleProfiles = (c.model_profiles || []).filter(
    (p: Item) =>
      (!providerFilter || p.provider_id === providerFilter) &&
      (!keyFilter || p.credential_id === keyFilter),
  );
  // Keep only the selection ID; refreshed catalog versions supply edit defaults.
  const selectedProfile = (c.model_profiles || []).find(
    (p: Item) => p.id === edit.profile,
  );
  async function save(path: string, value: Item, method = "POST") {
    // Catalog refresh can remount editors. Keep every editor and its selectors
    // unavailable until both the mutation and refresh finish.
    setSaving(true);
    try {
      const result = await api(path, { method, body: JSON.stringify(value) });
      await reload();
      return result;
    } finally {
      setSaving(false);
    }
  }
  async function discoverDocker() {
    setDockerBusy(true);
    setDockerError(undefined);
    try {
      setDocker(await api("/admin/docker"));
    } catch (e) {
      setDockerError(e);
    } finally {
      setDockerBusy(false);
    }
  }
  async function action(path: string, value: Item = {}, method = "POST") {
    try {
      await save(path, value, method);
      toast.success("已更新");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  function catalogList(kind: string, values: Item[]) {
    return (
      <div className="flex flex-col gap-4">
        {values.map((v) => (
          <Card key={v.id}>
            <CardHeader>
              <CardTitle>
                {v.name} · v{v.version}
              </CardTitle>
              <CardDescription>
                {kind === "dataset" ? v.reference : v.image}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {kind === "dataset" ? (
                <>
                  <p>
                    来源验证与运行输入分别检查；环境由Harbor按作者定义运行。
                  </p>
                  <AuthorInputs
                    dataset={v}
                    save={save}
                    check={(path, value) => void action(path, value)}
                    docker={docker}
                  />
                </>
              ) : null}
              <p>
                {v.status === "verified"
                  ? "来源已验证"
                  : v.status === "blocked"
                    ? "存在阻碍"
                    : "尚未验证"}
                {v.checked ? ` · ${date(v.checked)}` : ""} ·{" "}
                {v.enabled ? "启用" : "停用"}
              </p>
              {v.error || v.readiness_error ? (
                <Alert variant="destructive">
                  <AlertDescription>
                    {(v.error || v.readiness_error).message}
                  </AlertDescription>
                </Alert>
              ) : null}
              {v.tasks ? (
                <p>任务：{v.tasks.map((t: Item) => t.name).join("、")}</p>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  onClick={() => setEdit({ ...edit, [kind]: v })}
                >
                  编辑
                </Button>
                <Button
                  onClick={() =>
                    void action(`/admin/catalog/${kind}/${v.id}/verify`)
                  }
                >
                  验证
                </Button>
                {kind === "dataset" && v.ready ? (
                  <Button
                    variant="outline"
                    onClick={() =>
                      void action(
                        "/admin/settings",
                        { default_dataset_id: v.id },
                        "PATCH",
                      )
                    }
                  >
                    {c.settings?.default_dataset_id === v.id
                      ? "当前默认"
                      : "设为默认"}
                  </Button>
                ) : null}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }
  return (
    <>
      <Title
        title="团队管理"
        description="验证 benchmark 来源，再配置模型和受邀成员。环境按作者定义执行。"
      />
      <ErrorNotice error={error} />
      {saving ? (
        <p role="status">正在保存并刷新配置，完成后可继续编辑。</p>
      ) : null}
      <fieldset disabled={saving} aria-busy={saving} className="min-w-0">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="admin-tabs">
            <TabsTrigger value="readiness">就绪与来源</TabsTrigger>
            <TabsTrigger value="runtime">Docker 诊断</TabsTrigger>
            <TabsTrigger value="dataset">数据集</TabsTrigger>
            <TabsTrigger value="models">模型与 key</TabsTrigger>
            <TabsTrigger value="users">受邀账户</TabsTrigger>
            <TabsTrigger value="limits">容量与保留</TabsTrigger>
          </TabsList>
          <TabsContent value="readiness">
            <div className="admin-layout">
              <Card>
                <CardHeader>
                  <CardTitle>实验准备检查</CardTitle>
                  <CardDescription>
                    目录验证代表该次检查可用；实际提交仍重新校验并保留作者任务快照。
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex flex-col gap-4">
                  <p>
                    已验证可选数据集：
                    {(c.datasets || []).filter((v: Item) => v.ready).length}
                  </p>
                  <p>
                    默认数据集：
                    {(c.datasets || []).find(
                      (v: Item) => v.id === c.settings?.default_dataset_id,
                    )?.name || "尚未选择"}
                  </p>
                  <p>
                    Hub 来源：
                    {c.hub?.mode === "team"
                      ? `团队凭据 v${c.hub.version}`
                      : "匿名（仅公开包）"}
                  </p>
                  <p>
                    私有包需有访问权限的团队 Hub PAT；不会读取部署人员 HOME
                    登录。缺镜像或 Docker 权限须由部署负责人修复，再回网页验证。
                  </p>
                  <p>
                    模型配置保存 ≠ 真实认证成功；本页面不会发起付费模型请求。
                  </p>
                  <AdminForm
                    title="团队名称"
                    description="显示给全体成员"
                    fields={[
                      {
                        name: "team_name",
                        label: "名称",
                        defaultValue: c.settings?.team_name || "团队实验室",
                      },
                    ]}
                    onSave={(v) => save("/admin/settings", v, "PATCH")}
                  />
                </CardContent>
              </Card>
              <div className="flex flex-col gap-4">
                <Card>
                  <CardHeader>
                    <CardTitle>Hub 凭据状态</CardTitle>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-2">
                    <p>
                      凭据：
                      {c.hub?.state === "active" || c.hub?.mode === "team"
                        ? "已设置（启用）"
                        : c.hub?.version
                          ? "已停用"
                          : "未设置"}
                    </p>
                    <p>
                      版本：{c.hub?.version ? `v${c.hub.version}` : "无"} ·
                      更新时间：
                      {c.hub?.updated_at
                        ? date(c.hub.updated_at)
                        : c.hub?.version
                          ? "旧版本未记录"
                          : "无"}
                    </p>
                    <p>
                      保存仅代表加密持久化，未验证Hub身份或数据集访问权限。访问验证结果请查看数据集条目的验证状态。
                    </p>
                    {hubNotice ? <p role="status">{hubNotice}</p> : null}
                    <ErrorNotice error={hubError} />
                  </CardContent>
                </Card>
                <AdminForm
                  title="团队 Hub 来源凭据"
                  description="只写入并加密保存。输入 Hub PAT，保存后去数据集页面验证权限；轮换后重新验证数据集。PAT 只用于来源准备，不进入执行环境。"
                  fields={[{ name: "key", label: "Hub PAT", type: "password" }]}
                  onSave={async (v) => {
                    setHubNotice("");
                    setHubError(undefined);
                    await save("/admin/hub", v);
                    setHubNotice(
                      "Hub PAT已保存，输入已清空；若已有凭据则完成轮换。请另行验证数据集访问。",
                    );
                  }}
                />
                <Button
                  variant="outline"
                  disabled={!c.hub?.version || c.hub?.state === "disabled"}
                  onClick={async () => {
                    setHubNotice("");
                    setHubError(undefined);
                    try {
                      await save("/admin/hub/disable", {});
                      setHubNotice(
                        "Hub凭据已停用，当前使用匿名来源；需要权限的数据集须重新配置凭据。",
                      );
                    } catch (e) {
                      setHubError(e);
                    }
                  }}
                >
                  停用 Hub 凭据，改为匿名来源
                </Button>
              </div>
            </div>
          </TabsContent>
          <TabsContent value="runtime">
            <Card>
              <CardHeader>
                <CardTitle>服务端 Docker 与镜像库存</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <p>
                  只读诊断，不拉取、构建或删除镜像。库存不代表 benchmark
                  兼容性。
                </p>
                <Button
                  disabled={dockerBusy}
                  onClick={() => void discoverDocker()}
                >
                  {dockerBusy ? "发现中…" : "发现本机 Docker 与镜像"}
                </Button>
                <ErrorNotice error={dockerError} />
                {docker ? (
                  <>
                    <p role="status">{docker.message}</p>
                    <p>发现时间：{date(docker.checked_at)}</p>
                    {(docker.images || []).map((image: Item) => (
                      <p key={image.reference}>{image.reference}</p>
                    ))}
                  </>
                ) : null}
                <p>旧运行环境配置保留为历史记录，新实验不使用其镜像覆盖。</p>
                {(c.runtimes || []).map((runtime: Item) => (
                  <p key={runtime.id}>
                    {runtime.name} · v{runtime.version} · {runtime.image}
                  </p>
                ))}
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="dataset">
            <Button
              variant="outline"
              disabled={dockerBusy}
              onClick={() => void discoverDocker()}
            >
              发现本机镜像供作者参数选择
            </Button>
            <ErrorNotice error={dockerError} />
            <div className="admin-layout">
              {catalogList("dataset", c.datasets || [])}
              <div className="flex flex-col gap-4">
                <AdminForm
                  key={JSON.stringify(edit.dataset || {})}
                  title={`${edit.dataset ? "编辑" : "添加"}数据集`}
                  description="保存来源，再验证访问和任务清单。无需统一运行镜像；缺少作者依赖时执行会如实失败。"
                  fields={[
                    {
                      name: "name",
                      label: "数据集名称",
                      defaultValue: edit.dataset?.name,
                    },
                    {
                      name: "reference",
                      label: "Hub 来源（owner/name@版本）",
                      defaultValue: edit.dataset?.reference,
                    },
                    {
                      name: "enabled",
                      label: "状态",
                      defaultValue: String(edit.dataset?.enabled ?? true),
                      options: [
                        { value: "true", label: "启用" },
                        { value: "false", label: "停用" },
                      ],
                    },
                  ]}
                  onSave={async (v) => {
                    const saved = await save("/admin/catalog/dataset", {
                      ...v,
                      id: edit.dataset?.id,
                      enabled: v.enabled === "true",
                    });
                    setEdit((current) => ({ ...current, dataset: saved }));
                  }}
                />
                <Button
                  variant="ghost"
                  onClick={() => setEdit({ ...edit, dataset: undefined })}
                >
                  新建条目
                </Button>
              </div>
            </div>
          </TabsContent>
          <TabsContent value="models">
            <div className="flex flex-col gap-6">
              <Alert>
                <AlertTitle>明确绑定、版本化配置</AlertTitle>
                <AlertDescription>
                  提供商 → 团队 key →
                  模型方案。内部标识自动生成。密钥只写入；轮换保持同一 key
                  的绑定，停用阻止新执行。
                </AlertDescription>
              </Alert>
              <Card>
                <CardHeader>
                  <CardTitle>浏览配置列表</CardTitle>
                  <CardDescription>
                    以下条件只缩小左侧列表；右侧新建或编辑表单中的提供商与团队
                    key 决定保存绑定。筛选不会修改表单或已有配置。
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <div className="flex flex-wrap gap-4">
                    <SelectField
                      label="列表范围：提供商"
                      name="filter-provider"
                      value={providerFilter}
                      onChange={(v) => {
                        setProviderFilter(v);
                        setKeyFilter("");
                      }}
                    >
                      <option value="">全部提供商</option>
                      {(c.providers || []).map((p: Item) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </SelectField>
                    <SelectField
                      label="列表范围：团队 key"
                      name="filter-key"
                      value={keyFilter}
                      onChange={setKeyFilter}
                    >
                      <option value="">全部key</option>
                      {(c.credentials || [])
                        .filter(
                          (k: Item) =>
                            !providerFilter || k.provider_id === providerFilter,
                        )
                        .map((k: Item) => (
                          <option key={k.id} value={k.id}>
                            {
                              (c.providers || []).find(
                                (p: Item) => p.id === k.provider_id,
                              )?.name
                            }{" "}
                            → {k.label}
                          </option>
                        ))}
                    </SelectField>
                    <Button
                      variant="outline"
                      onClick={() => {
                        setProviderFilter("");
                        setKeyFilter("");
                      }}
                    >
                      显示全部配置
                    </Button>
                  </div>
                  <p>
                    当前列表：{visibleProviders.length} 个提供商、
                    {visibleKeys.length} 个团队 key、{visibleProfiles.length}{" "}
                    个模型方案。提供商条件作用于三种列表；key 条件只作用于 key
                    与模型方案。
                  </p>
                </CardContent>
              </Card>
              <div className="admin-layout">
                <div className="flex flex-col gap-4">
                  <h2>提供商列表</h2>
                  {!visibleProviders.length ? (
                    <EmptyState
                      title="此范围暂无提供商"
                      description="显示全部配置或在右侧新建提供商。"
                    />
                  ) : null}
                  {visibleProviders.map((p: Item) => (
                    <Card key={p.id}>
                      <CardHeader>
                        <CardTitle>{p.name}</CardTitle>
                        <CardDescription>
                          {p.endpoint} · {p.enabled ? "启用" : "停用"} ·{" "}
                          {
                            (c.credentials || []).filter(
                              (k: Item) => k.provider_id === p.id,
                            ).length
                          }
                          个key ·{" "}
                          {
                            (c.model_profiles || []).filter(
                              (m: Item) => m.provider_id === p.id,
                            ).length
                          }
                          个方案
                        </CardDescription>
                      </CardHeader>
                      <CardContent className="flex gap-2">
                        <Button
                          variant="outline"
                          onClick={() => setEdit({ ...edit, provider: p })}
                        >
                          编辑提供商
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() =>
                            void action("/admin/providers", {
                              ...p,
                              enabled: !p.enabled,
                            })
                          }
                        >
                          {p.enabled ? "停用" : "启用"}
                        </Button>
                      </CardContent>
                    </Card>
                  ))}
                </div>
                <div className="flex flex-col gap-3">
                  <p>
                    {edit.provider
                      ? `正在编辑：${edit.provider.name}`
                      : "正在新建提供商"}
                    ；每个提供商可有多个key，每个key可有多个方案。
                  </p>
                  <Button
                    variant="outline"
                    onClick={() =>
                      setEdit((current) => ({
                        ...current,
                        provider: undefined,
                      }))
                    }
                  >
                    新建提供商
                  </Button>
                  <AdminForm
                    key={JSON.stringify(edit.provider || {})}
                    title="提供商配置"
                    description="OpenAI-compatible HTTP API；已有实验保留提交时的端点。"
                    fields={[
                      {
                        name: "name",
                        label: "提供商名称",
                        defaultValue: edit.provider?.name,
                      },
                      {
                        name: "endpoint",
                        label: "API 端点",
                        type: "url",
                        defaultValue: edit.provider?.endpoint,
                      },
                    ]}
                    onSave={async (v) => {
                      const saved = await save("/admin/providers", {
                        ...v,
                        id: edit.provider?.id,
                        protocol: "openai-compatible",
                        enabled: edit.provider?.enabled ?? true,
                      });
                      setEdit((current) => ({ ...current, provider: saved }));
                    }}
                  />
                </div>
              </div>
              <div className="admin-layout">
                <div className="flex flex-col gap-3">
                  <h2>团队 key 列表</h2>
                  {!visibleKeys.length ? (
                    <EmptyState
                      title="此范围暂无团队 key"
                      description="调整列表范围；添加时在右侧明确选择所属提供商。"
                    />
                  ) : null}
                  {visibleKeys.map((key: Item) => (
                    <Card key={key.id}>
                      <CardHeader>
                        <CardTitle>
                          {key.label} · v{key.version}
                        </CardTitle>
                        <CardDescription>
                          {
                            (c.providers || []).find(
                              (p: Item) => p.id === key.provider_id,
                            )?.name
                          }{" "}
                          · {key.enabled ? "启用" : "停用"} ·{" "}
                          {
                            (c.model_profiles || []).filter(
                              (m: Item) => m.credential_id === key.id,
                            ).length
                          }
                          个方案
                        </CardDescription>
                      </CardHeader>
                      <CardContent className="flex gap-2">
                        <Button
                          variant="outline"
                          onClick={() => setRotation(key.id)}
                        >
                          轮换
                        </Button>
                        <Button
                          variant="outline"
                          disabled={!key.enabled}
                          onClick={() =>
                            void action(`/admin/credentials/${key.id}/disable`)
                          }
                        >
                          停用
                        </Button>
                      </CardContent>
                    </Card>
                  ))}
                  {rotation ? (
                    <AdminForm
                      key={rotation}
                      title="轮换团队 key"
                      description={`正在轮换：${(c.credentials || []).find((k: Item) => k.id === rotation)?.label || rotation}。旧版本继续供已绑定运行与审计使用。`}
                      fields={[
                        { name: "key", label: "新密钥", type: "password" },
                      ]}
                      onSave={async (v) => {
                        await save(`/admin/credentials/${rotation}/rotate`, v);
                        setRotation("");
                      }}
                    />
                  ) : null}
                </div>
                <AdminForm
                  title="添加团队 key"
                  description="每个提供商可新增多个key。绑定保持不变；轮换或停用已有key，方案可编辑或新增。密钥加密保存，不回显、不保存在浏览器。"
                  fields={[
                    { name: "label", label: "Key 名称" },
                    {
                      name: "provider_id",
                      label: "提供商",
                      options: (c.providers || []).map((p: Item) => ({
                        value: p.id,
                        label: p.name,
                      })),
                    },
                    { name: "key", label: "密钥", type: "password" },
                  ]}
                  onSave={(v) => save("/admin/credentials", v)}
                />
              </div>
              <div className="admin-layout">
                <div className="flex flex-col gap-4">
                  <h2>模型方案列表</h2>
                  {!visibleProfiles.length ? (
                    <EmptyState
                      title="此范围暂无模型方案"
                      description="调整列表范围或新建模型方案；保存绑定在右侧编辑。"
                    />
                  ) : null}
                  {visibleProfiles.map((p: Item) => (
                    <Card key={p.id}>
                      <CardHeader>
                        <CardTitle>
                          {p.name} · {p.model}
                        </CardTitle>
                        <CardDescription>
                          {
                            (c.providers || []).find(
                              (provider: Item) => provider.id === p.provider_id,
                            )?.name
                          }{" "}
                          →{" "}
                          {
                            (c.credentials || []).find(
                              (k: Item) => k.id === p.credential_id,
                            )?.label
                          }{" "}
                          · v{p.version} · {p.enabled ? "启用" : "停用"}
                        </CardDescription>
                      </CardHeader>
                      <CardContent className="flex flex-wrap gap-2">
                        <Button
                          variant="outline"
                          onClick={() => setEdit({ ...edit, profile: p.id })}
                        >
                          编辑方案
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() =>
                            void action("/admin/model-profiles", {
                              ...p,
                              enabled: !p.enabled,
                            })
                          }
                        >
                          {p.enabled ? "停用" : "启用"}
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() =>
                            void action(
                              "/admin/settings",
                              { default_model_profile: p.id },
                              "PATCH",
                            )
                          }
                        >
                          设为默认模型
                        </Button>
                      </CardContent>
                    </Card>
                  ))}
                  <Button
                    variant="ghost"
                    onClick={() => setEdit({ ...edit, profile: undefined })}
                  >
                    新建模型方案
                  </Button>
                </div>
                <ModelForm
                  key={JSON.stringify(selectedProfile || {})}
                  catalog={c}
                  selected={selectedProfile}
                  save={save}
                  onSaved={(saved) =>
                    setEdit((current) => ({ ...current, profile: saved.id }))
                  }
                />
              </div>
            </div>
          </TabsContent>
          <TabsContent value="users">
            <div className="admin-layout">
              <div className="flex flex-col gap-4">
                {users.map((u) => (
                  <Card key={u.id}>
                    <CardHeader>
                      <CardTitle>{u.username}</CardTitle>
                      <CardDescription>
                        {u.role === "admin" ? "管理员" : "成员"} ·{" "}
                        {u.enabled ? "启用" : "停用"}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="flex gap-2">
                      <Button
                        variant="outline"
                        onClick={() =>
                          void action(
                            `/admin/users/${u.id}`,
                            { enabled: !u.enabled },
                            "PATCH",
                          )
                        }
                      >
                        {u.enabled ? "停用" : "启用"}
                      </Button>
                      <Button variant="outline" onClick={() => setReset(u)}>
                        重置密码
                      </Button>
                    </CardContent>
                  </Card>
                ))}
                {reset ? (
                  <AdminForm
                    key={reset.id}
                    title={`重置 ${reset.username} 密码`}
                    description="将撤销该用户现有会话；请安全交付新密码。"
                    fields={[
                      {
                        name: "password",
                        label: "新密码（至少12位）",
                        type: "password",
                      },
                    ]}
                    onSave={async (v) => {
                      await save(`/admin/users/${reset.id}`, v, "PATCH");
                      setReset(undefined);
                    }}
                  />
                ) : null}
              </div>
              <AdminForm
                title="创建受邀账户"
                description="无公开注册。请安全交付网址和初始密码；成员可以在账户页修改密码。"
                fields={[
                  { name: "username", label: "用户名" },
                  {
                    name: "password",
                    label: "初始密码（至少12位）",
                    type: "password",
                  },
                  {
                    name: "role",
                    label: "角色",
                    defaultValue: "member",
                    options: [
                      { value: "member", label: "成员" },
                      { value: "admin", label: "管理员" },
                    ],
                  },
                ]}
                onSave={(v) => save("/admin/users", v)}
              />
            </div>
          </TabsContent>
          <TabsContent value="limits">
            <MaintenancePanel readiness={c.readiness} saved={reload} />
            <AdminForm
              key={JSON.stringify(c.limits)}
              title="容量与保留"
              description="CLI/Web 共用；运行时长与并发不保证金额预算。降低额度不取消存量；每成员所有凭证与网页共用额度，管理员也计入本人额度。"
              fields={Object.entries(c.limits || {})
                .filter(([name]) => name in limitLabels)
                .map(([name, v]) => ({
                  name,
                  label: limitLabels[name],
                  type: "number",
                  defaultValue: String(v),
                }))}
              onSave={(v) =>
                save(
                  "/admin/limits",
                  Object.fromEntries(
                    Object.entries(v).map(([k, x]) => [k, Number(x)]),
                  ),
                  "PATCH",
                )
              }
            />
          </TabsContent>
        </Tabs>
      </fieldset>
    </>
  );
}
export function SetupPage({ done }: { done: () => void }) {
  return (
    <div className="login-page">
      <AdminForm
        title="首次网站设置"
        description="需要部署负责人交付的一次性引导凭证；本网站不开放注册。主密钥在数据库外生成，不会回显。"
        fields={[
          { name: "setup_token", label: "部署引导凭证", type: "password" },
          { name: "team_name", label: "团队名称", defaultValue: "团队实验室" },
          { name: "username", label: "首管理员用户名" },
          {
            name: "password",
            label: "管理员密码（至少12位）",
            type: "password",
          },
        ]}
        onSave={async (v) => {
          await post("/setup", v);
          done();
        }}
      />
    </div>
  );
}
export function AccountPage({ logout }: { logout: () => void }) {
  return (
    <AdminForm
      title="修改密码"
      description="成功后所有现有会话失效，请使用新密码重新登录。"
      fields={[
        { name: "current_password", label: "当前密码", type: "password" },
        { name: "password", label: "新密码（至少12位）", type: "password" },
      ]}
      onSave={async (v) => {
        await post("/auth/password", v);
        logout();
      }}
    />
  );
}

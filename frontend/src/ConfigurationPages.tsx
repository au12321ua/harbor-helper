import { useLoad } from "./useLoad";
import { useState } from "react";
import { LoaderCircle } from "lucide-react";
import { api, post, date, type Item } from "./api";
import { ErrorNotice, Title, SelectField, Loading } from "./shared";
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
import { Field, FieldLabel, FieldGroup } from "@/components/ui/field";
import { toast } from "sonner";
const limitLabels: Record<string, string> = {
  max_jobs: "全局任务并发",
  max_trials: "全局 Trial 并发",
  max_queue: "最大队列长度",
  max_wall_seconds: "最长运行秒数",
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
  }[];
  onSave: (value: Item) => Promise<unknown>;
}) {
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
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
            const value = Object.fromEntries(new FormData(form));
            try {
              await onSave(value);
              form.reset();
              toast.success("配置已保存");
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
                  >
                    {!f.defaultValue ? <option value="">请选择</option> : null}
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
              </Field>
            ))}
            <ErrorNotice error={error} />
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
        </form>
      </CardContent>
    </Card>
  );
}
function ModelForm({
  catalog,
  selected,
  save,
}: {
  catalog: Item;
  selected?: Item;
  save: (path: string, value: Item) => Promise<unknown>;
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
        <AdminForm
          key={`${selected?.id || "new"}-${provider}`}
          title="模型配置"
          description="常用参数可留空；JSON 高级参数与常用参数合并。已有实验保留旧版本。"
          fields={[
            { name: "name", label: "方案名称", defaultValue: selected?.name },
            {
              name: "credential_id",
              label: "团队 key",
              defaultValue: selected?.credential_id,
              options: credentials.map((c: Item) => ({
                value: c.id,
                label: c.label,
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
            await save("/admin/model-profiles", {
              id: selected?.id,
              name: v.name,
              provider_id: provider,
              credential_id: v.credential_id,
              model: v.model,
              params,
              opencode_version: v.opencode_version,
              enabled: selected?.enabled ?? true,
            });
          }}
        />
      </CardContent>
    </Card>
  );
}
export function Admin() {
  const { data, error, loading, reload } = useLoad(() =>
    Promise.all([api("/admin/users"), api("/catalog")]),
  );
  const [tab, setTab] = useState("readiness"),
    [edit, setEdit] = useState<Item>({}),
    [rotation, setRotation] = useState(""),
    [reset, setReset] = useState<Item>();
  if (loading) return <Loading />;
  const users = rowsOf(data?.[0], "users"),
    c = data?.[1] || {};
  async function save(path: string, value: Item, method = "POST") {
    const result = await api(path, { method, body: JSON.stringify(value) });
    await reload();
    return result;
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
              <p>
                {v.status === "verified"
                  ? "已验证"
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
        description="先验证数据集与运行环境，再配置模型和受邀成员。日常配置在网页完成。"
      />
      <ErrorNotice error={error} />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="admin-tabs">
          <TabsTrigger value="readiness">就绪与来源</TabsTrigger>
          <TabsTrigger value="runtime">运行环境</TabsTrigger>
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
                  目录验证代表该次检查可用；实际提交仍重新校验并冻结来源与环境。
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <p>
                  已验证可选数据集：
                  {(c.datasets || []).filter((v: Item) => v.ready).length}
                </p>
                <p>
                  已验证环境：
                  {
                    (c.runtimes || []).filter(
                      (v: Item) => v.status === "verified" && v.enabled,
                    ).length
                  }
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
                <p>模型配置保存 ≠ 真实认证成功；本页面不会发起付费模型请求。</p>
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
              <AdminForm
                title="团队 Hub 来源凭据"
                description="只写入并加密保存。输入 Hub PAT，保存后去数据集页面验证权限；轮换后重新验证数据集。PAT 只用于来源准备，不进入执行环境。"
                fields={[{ name: "key", label: "Hub PAT", type: "password" }]}
                onSave={(v) => save("/admin/hub", v)}
              />
              <Button
                variant="outline"
                onClick={() => void action("/admin/hub/disable")}
              >
                停用 Hub 凭据，改为匿名来源
              </Button>
            </div>
          </div>
        </TabsContent>
        {(["runtime", "dataset"] as const).map((kind) => (
          <TabsContent key={kind} value={kind}>
            <div className="admin-layout">
              {catalogList(
                kind,
                c[kind === "dataset" ? "datasets" : "runtimes"] || [],
              )}
              <div className="flex flex-col gap-4">
                <AdminForm
                  key={JSON.stringify(edit[kind] || {})}
                  title={`${edit[kind] ? "编辑" : "添加"}${kind === "dataset" ? "数据集" : "运行环境"}`}
                  description="保存会创建新版本并取消验证状态；再次验证后才能供成员选择。"
                  fields={
                    kind === "dataset"
                      ? [
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
                            name: "runtime_id",
                            label: "运行环境",
                            defaultValue: edit.dataset?.runtime_id,
                            options: (c.runtimes || []).map((r: Item) => ({
                              value: r.id,
                              label: r.name,
                            })),
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
                        ]
                      : [
                          {
                            name: "name",
                            label: "环境名称",
                            defaultValue: edit.runtime?.name,
                          },
                          {
                            name: "image",
                            label: "Docker 镜像引用",
                            defaultValue: edit.runtime?.image,
                          },
                          {
                            name: "image_env",
                            label: "镜像变量名（逗号分隔）",
                            defaultValue: (
                              edit.runtime?.image_env || [
                                "CAD_BENCH_AGENT_IMAGE",
                                "CAD_BENCH_VERIFIER_IMAGE",
                              ]
                            ).join(","),
                            required: false,
                          },
                          {
                            name: "enabled",
                            label: "状态",
                            defaultValue: String(edit.runtime?.enabled ?? true),
                            options: [
                              { value: "true", label: "启用" },
                              { value: "false", label: "停用" },
                            ],
                          },
                        ]
                  }
                  onSave={async (v) => {
                    await save(`/admin/catalog/${kind}`, {
                      ...v,
                      id: edit[kind]?.id,
                      enabled: v.enabled === "true",
                      ...(kind === "runtime"
                        ? {
                            image_env: v.image_env
                              .split(",")
                              .map((x: string) => x.trim())
                              .filter(Boolean),
                          }
                        : {}),
                    });
                    setEdit({ ...edit, [kind]: undefined });
                  }}
                />
                <Button
                  variant="ghost"
                  onClick={() => setEdit({ ...edit, [kind]: undefined })}
                >
                  新建条目
                </Button>
              </div>
            </div>
          </TabsContent>
        ))}
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
            <div className="admin-layout">
              <div className="flex flex-col gap-4">
                {(c.providers || []).map((p: Item) => (
                  <Card key={p.id}>
                    <CardHeader>
                      <CardTitle>{p.name}</CardTitle>
                      <CardDescription>{p.endpoint}</CardDescription>
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
                  await save("/admin/providers", {
                    ...v,
                    id: edit.provider?.id,
                    protocol: "openai-compatible",
                    enabled: edit.provider?.enabled ?? true,
                  });
                  setEdit({ ...edit, provider: undefined });
                }}
              />
            </div>
            <div className="admin-layout">
              <div className="flex flex-col gap-3">
                {(c.credentials || []).map((key: Item) => (
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
                        · {key.enabled ? "启用" : "停用"}
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
                    description="旧版本继续供已绑定运行与审计使用。"
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
                description="密钥加密保存，不回显、不保存在浏览器。"
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
                {(c.model_profiles || []).map((p: Item) => (
                  <Card key={p.id}>
                    <CardHeader>
                      <CardTitle>
                        {p.name} · {p.model}
                      </CardTitle>
                      <CardDescription>
                        {
                          (c.credentials || []).find(
                            (k: Item) => k.id === p.credential_id,
                          )?.label
                        }{" "}
                        · v{p.version}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        onClick={() => setEdit({ ...edit, profile: p })}
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
                key={JSON.stringify(edit.profile || {})}
                catalog={c}
                selected={edit.profile}
                save={save}
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
          <AdminForm
            key={JSON.stringify(c.limits)}
            title="容量与保留"
            description="CLI/Web 共用；运行时长与并发不保证金额预算。降低容量不会强制中断正在运行的实验。"
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

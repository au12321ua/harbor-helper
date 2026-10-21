import {
  api,
  post,
  newIdempotencyKey,
  type User,
  type Target,
  type BatchEntry,
  type DatasetEntry,
  type RemoteVersions,
  type Preview,
  type MergePreview,
} from "@/api";
import { ErrorNotice, Loading, Title } from "@/components/shared";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useLoad } from "@/hooks/useLoad";
import { useState } from "react";
import { Link } from "react-router-dom";

export function ManagementPage({ user }: { user: User }) {
  const requests = useLoad(() => api("/management/requests"));
  const recycle = useLoad(() => api("/management/recycle"));
  const datasets = useLoad(() => api("/management/datasets"));
  const attachments = useLoad(() => api("/attachments"));
  const [selected, setSelected] = useState<Target[]>([]);
  const [results, setResults] = useState<BatchEntry[]>([]);
  const [failure, setFailure] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState<{
    id: string;
    label: string;
    count: number;
  }>();
  async function refresh() {
    await Promise.all([
      requests.reload(),
      recycle.reload(),
      datasets.reload(),
      attachments.reload(),
    ]);
  }
  async function perform(action: () => Promise<unknown>) {
    setBusy(true);
    setFailure(undefined);
    try {
      await action();
      await refresh();
    } catch (e) {
      setFailure(e);
    } finally {
      setBusy(false);
    }
  }
  function toggle(target: Target, checked: boolean) {
    setSelected((old) =>
      checked
        ? [
            ...old.filter(
              (t) => t.kind !== target.kind || t.object_id !== target.object_id,
            ),
            target,
          ]
        : old.filter(
            (t) => t.kind !== target.kind || t.object_id !== target.object_id,
          ),
    );
  }
  const selection = (target: Target, label: string) => (
    <label className="flex items-center gap-2">
      <input
        type="checkbox"
        aria-label={`选择${label}`}
        checked={selected.some(
          (t) => t.kind === target.kind && t.object_id === target.object_id,
        )}
        onChange={(e) => toggle(target, e.target.checked)}
      />
      {label}
    </label>
  );
  if (requests.loading) return <Loading />;
  return (
    <>
      <Title
        title="请求与目录管理"
        description="按组追溯来源；回收可恢复，永久删除须在回收站单独确认。目录删除不删除其他请求的独立快照。"
      />
      <ErrorNotice
        error={
          failure ||
          requests.error ||
          recycle.error ||
          datasets.error ||
          attachments.error
        }
      />
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => void perform(refresh)}
        >
          刷新
        </Button>
        <Button
          disabled={busy || !selected.length}
          onClick={() =>
            void perform(async () => {
              const items = await Promise.all(
                selected.map((t) => post("/management/recycle/preview", t)),
              );
              if (
                !window.confirm(
                  `移入回收站：${items.length} 项？整对象包含预览中的全部版本，已回收版本保持其恢复状态。`,
                )
              )
                return;
              const value = await post("/management/recycle", { items });
              setResults(value.results);
              setSelected([]);
            })
          }
        >
          将选中 {selected.length} 项移入回收站
        </Button>
      </div>
      {results.length > 0 ? (
        <ul aria-label="逐项处理结果">
          {results.map((r, i) => (
            <li key={i}>
              {r.kind} {r.object_id}：{r.error?.message || r.event?.state}
            </li>
          ))}
        </ul>
      ) : null}
      <Tabs defaultValue="requests">
        <TabsList>
          <TabsTrigger value="requests">请求组</TabsTrigger>
          <TabsTrigger value="attachments">附件</TabsTrigger>
          {user.role === "admin" ? (
            <TabsTrigger value="datasets">数据集版本</TabsTrigger>
          ) : null}
          <TabsTrigger value="recycle">回收站</TabsTrigger>
        </TabsList>
        <TabsContent value="requests" className="flex flex-col gap-4">
          {(requests.data?.requests || []).map((r) => (
            <Card key={r.id}>
              <CardHeader>
                <CardTitle>
                  {r.display_name} / #{r.number}
                </CardTitle>
                <CardDescription>
                  {r.submitter} · {r.status} · {r.id}
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <p>
                  直接来源：{r.source_id || "无已知来源"} · 关系：{r.relation}
                </p>
                <div className="flex gap-2">
                  {r.run_id ? (
                    <Button asChild variant="outline">
                      <Link to={`/runs/${r.run_id}`}>查看实验</Link>
                    </Button>
                  ) : r.id.startsWith("sub-") ? (
                    <Button asChild variant="outline">
                      <Link to={`/submissions/${r.id}`}>查看准备记录</Link>
                    </Button>
                  ) : (
                    <span>未受理请求</span>
                  )}
                </div>
                {user.role === "admin" || user.id === r.user_id
                  ? selection(
                      { kind: "request", object_id: r.id },
                      `请求 #${r.number}`,
                    )
                  : null}
                {user.role === "admin" || user.id === r.creator_id ? (
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      const form = new FormData(e.currentTarget);
                      void perform(() =>
                        api(`/management/groups/${r.group_id}`, {
                          method: "PATCH",
                          body: { name: String(form.get("name") || "") },
                        }),
                      );
                    }}
                  >
                    <FieldGroup>
                      <Field>
                        <FieldLabel htmlFor={`group-${r.id}`}>
                          组名（组创建者或管理员可改）
                        </FieldLabel>
                        <Input
                          id={`group-${r.id}`}
                          name="name"
                          defaultValue={r.name}
                          maxLength={128}
                        />
                      </Field>
                    </FieldGroup>
                    <Button variant="outline" disabled={busy}>
                      保存组名
                    </Button>
                  </form>
                ) : null}
              </CardContent>
            </Card>
          ))}
        </TabsContent>
        <TabsContent value="attachments" className="flex flex-col gap-4">
          <p>停用仍可下载；正常历史请求仍可按自己的冻结快照重跑。</p>
          {(attachments.data?.attachments || []).map((a) => (
            <Card key={a.id}>
              <CardHeader>
                <CardTitle>{a.name}</CardTitle>
                <CardDescription>{a.enabled ? "启用" : "停用"}</CardDescription>
              </CardHeader>
              <CardContent>
                {user.role === "admin" || user.id === a.creator_id
                  ? selection(
                      { kind: "attachment", object_id: a.id },
                      `整个附件 ${a.name}`,
                    )
                  : null}
                {a.versions.map((v) => (
                  <div key={v.id} className="flex flex-wrap gap-3">
                    {user.role === "admin" || user.id === a.creator_id ? (
                      selection(
                        { kind: "attachment_version", object_id: v.id },
                        `附件 v${v.number}`,
                      )
                    ) : (
                      <span>v{v.number}</span>
                    )}
                    <a href={`/api/v1/attachment-versions/${v.id}/download`}>
                      下载此版本
                    </a>
                    <span>SHA256 {v.digest}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          ))}
        </TabsContent>
        {user.role === "admin" ? (
          <TabsContent value="datasets" className="flex flex-col gap-4">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                void perform(() =>
                  post("/admin/catalog/dataset", {
                    name: String(f.get("name")),
                    reference: String(f.get("source")),
                  }),
                );
              }}
            >
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="dataset-name">数据集名称</FieldLabel>
                  <Input id="dataset-name" name="name" required />
                </Field>
                <Field>
                  <FieldLabel htmlFor="dataset-source">作者/包名</FieldLabel>
                  <Input
                    id="dataset-source"
                    name="source"
                    placeholder="owner/package"
                    required
                  />
                </Field>
              </FieldGroup>
              <Button disabled={busy}>登记来源并选择版本</Button>
            </form>
            {(datasets.data?.datasets || []).map((d) => (
              <Card key={d.id}>
                <CardHeader>
                  <CardTitle>{d.name}</CardTitle>
                  <CardDescription>
                    {d.source}
                    {d.auto_named ? " · 升级时已自动区分重名" : ""}
                    {d.needs_merge ? " · 有旧同源项，可合并" : ""}
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  {selection(
                    { kind: "dataset", object_id: d.id },
                    `整个数据集 ${d.name}`,
                  )}
                  <DatasetVersions dataset={d} perform={perform} busy={busy} />
                  {d.versions.map((v) => (
                    <div key={v.id} className="flex flex-col gap-2">
                      {selection(
                        { kind: "dataset_version", object_id: v.id },
                        `数据集版本 #${v.number}`,
                      )}
                      <p className="break-all">
                        {v.resolved} ·{" "}
                        {d.default_version === v.id ? "默认版本" : "非默认版本"}
                      </p>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            void perform(() =>
                              api(`/management/datasets/${d.id}/default`, {
                                method: "PUT",
                                body: { version_id: v.id },
                              }),
                            )
                          }
                        >
                          设为默认版本
                        </Button>
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            void perform(() =>
                              api(`/management/datasets/${d.id}/default`, {
                                method: "PUT",
                                body: { version_id: v.id, team_default: true },
                              }),
                            )
                          }
                        >
                          设为团队默认
                        </Button>
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            void perform(() =>
                              post(
                                `/admin/datasets/${d.id}/author-inputs/check`,
                                { version_id: v.id },
                              ),
                            )
                          }
                        >
                          检查此版本参数
                        </Button>
                      </div>
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          const f = new FormData(e.currentTarget);
                          void perform(() =>
                            api(`/admin/datasets/${d.id}/author-inputs`, {
                              method: "PUT",
                              body: {
                                version_id: v.id,
                                values: JSON.parse(String(f.get("values"))),
                              },
                            }),
                          );
                        }}
                      >
                        <FieldGroup>
                          <Field>
                            <FieldLabel htmlFor={`parameters-${v.id}`}>
                              此摘要的非秘密作者参数
                            </FieldLabel>
                            <Textarea
                              id={`parameters-${v.id}`}
                              name="values"
                              defaultValue={JSON.stringify(
                                v.parameters.values || {},
                                null,
                                2,
                              )}
                            />
                          </Field>
                        </FieldGroup>
                        <Button variant="outline" disabled={busy}>
                          保存此版本参数
                        </Button>
                      </form>
                      <p>检查状态：{String(v.parameters.status)}</p>
                    </div>
                  ))}
                </CardContent>
              </Card>
            ))}
            <DatasetMerge
              datasets={datasets.data?.datasets || []}
              busy={busy}
              perform={perform}
            />
          </TabsContent>
        ) : null}
        <TabsContent value="recycle" className="flex flex-col gap-4">
          <p>不自动清空。恢复不会重新启用目录，也不会自动设为团队默认。</p>
          {(recycle.data?.items || []).map((item) => (
            <Card key={item.id}>
              <CardHeader>
                <CardTitle>
                  {item.kind} · {item.object_id}
                </CardTitle>
                <CardDescription>
                  {item.state} · {item.count} 项 · {item.cleanup || "文件保留"}
                </CardDescription>
              </CardHeader>
              <CardContent className="flex gap-2">
                <Button
                  variant="outline"
                  disabled={busy || item.state !== "recycled"}
                  onClick={() =>
                    void perform(() =>
                      post(`/management/recycle/${item.id}/restore`),
                    )
                  }
                >
                  恢复
                </Button>
                {user.role === "admin" &&
                ["recycled", "purging"].includes(item.state) ? (
                  <Button
                    variant="destructive"
                    disabled={busy}
                    onClick={() =>
                      setConfirmation({
                        id: item.id,
                        label: `${item.kind} ${item.object_id}`,
                        count: item.count,
                      })
                    }
                  >
                    永久删除
                  </Button>
                ) : null}
              </CardContent>
            </Card>
          ))}
          {confirmation ? (
            <Card>
              <CardHeader>
                <CardTitle>确认永久删除</CardTitle>
                <CardDescription>
                  {confirmation.label} · 覆盖 {confirmation.count}{" "}
                  项；将清除正文和专属内容。其他请求的冻结副本与既有备份不受影响。
                </CardDescription>
              </CardHeader>
              <CardContent className="flex gap-2">
                <Button
                  variant="destructive"
                  disabled={busy}
                  onClick={() =>
                    void perform(async () => {
                      await post(
                        `/management/recycle/${confirmation.id}/purge`,
                        {},
                        newIdempotencyKey(),
                      );
                      setConfirmation(undefined);
                    })
                  }
                >
                  确认永久删除此回收事件
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setConfirmation(undefined)}
                >
                  取消
                </Button>
              </CardContent>
            </Card>
          ) : null}
        </TabsContent>
      </Tabs>
    </>
  );
}

function DatasetVersions({
  dataset,
  perform,
  busy,
}: {
  dataset: DatasetEntry;
  perform: (f: () => Promise<unknown>) => Promise<void>;
  busy: boolean;
}) {
  const [remote, setRemote] = useState<RemoteVersions>();
  const [digest, setDigest] = useState("");
  const [preview, setPreview] = useState<Preview>();
  return (
    <div className="flex flex-col gap-3">
      <Button
        variant="outline"
        disabled={busy}
        onClick={() =>
          void perform(async () => {
            setRemote(await api(`/management/datasets/${dataset.id}/versions`));
            setPreview(undefined);
          })
        }
      >
        查询远端可选版本
      </Button>
      {remote ? (
        <>
          <p>
            最近 {remote.limit} 个未撤回版本
            {remote.truncated ? " · 已截断" : ""}
            {remote.possibly_incomplete ? " · 列表可能不完整" : ""}
          </p>
          {!remote.versions.length ? <p>该来源没有可选择的未撤回版本。</p> : null}
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor={`remote-${dataset.id}`}>
                手选来源版本
              </FieldLabel>
              <select
                id={`remote-${dataset.id}`}
                value={digest}
                onChange={(e) => {
                  setDigest(e.target.value);
                  setPreview(undefined);
                }}
              >
                <option value="">请选择</option>
                {remote.versions.map((v) => (
                  <option key={v.digest} value={v.digest}>
                    rev.{v.revision} {v.tags.join(", ")} {v.digest}
                  </option>
                ))}
              </select>
            </Field>
          </FieldGroup>
          <Button
            disabled={busy || !digest}
            onClick={() =>
              void perform(async () =>
                setPreview(
                  await post(`/management/datasets/${dataset.id}/preview`, {
                    digest,
                  }),
                ),
              )
            }
          >
            预览固定摘要
          </Button>
        </>
      ) : null}
      {preview ? (
        <>
          <p className="break-all">
            固定来源：{preview.resolved} · {preview.tasks.length} 个任务
          </p>
          <Button
            disabled={busy}
            onClick={() =>
              void perform(async () => {
                await post("/management/datasets/confirm", {
                  preview_id: preview.id,
                });
                setPreview(undefined);
              })
            }
          >
            确认纳入此版本
          </Button>
        </>
      ) : null}
    </div>
  );
}

function DatasetMerge({
  datasets,
  perform,
  busy,
}: {
  datasets: DatasetEntry[];
  perform: (f: () => Promise<unknown>) => Promise<void>;
  busy: boolean;
}) {
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [preview, setPreview] = useState<MergePreview>();
  const [choices, setChoices] = useState<
    Record<string, { id: string; version: number }>
  >({});
  const parameters = (preview?.parameters || []).map((p) => ({
    id: String(p.id),
    version: Number(p.version),
    config: JSON.parse(String(p.config)) as {
      source?: string;
      values?: Record<string, string>;
    },
  }));
  const summaries = [
    ...new Set(
      parameters.map((p) => p.config.source).filter((s): s is string => !!s),
    ),
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>合并旧同源数据集</CardTitle>
        <CardDescription>
          先预览版本与参数修订；原参数保留，冲突须明确选择。
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FieldGroup>
          {(
            [
              ["source", source, setSource],
              ["target", target, setTarget],
            ] as const
          ).map(([label, value, set]) => (
            <Field key={label}>
              <FieldLabel htmlFor={`merge-${label}`}>
                {label === "source" ? "来源" : "目标"}
              </FieldLabel>
              <select
                id={`merge-${label}`}
                value={value}
                onChange={(e) => {
                  set(e.target.value);
                  setPreview(undefined);
                }}
              >
                {<option value="">请选择</option>}
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name} · {d.source}
                  </option>
                ))}
              </select>
            </Field>
          ))}
        </FieldGroup>
        <Button
          variant="outline"
          disabled={busy || !source || !target}
          onClick={() =>
            void perform(async () => {
              setPreview(
                await post("/management/dataset-merge/preview", {
                  source,
                  target,
                }),
              );
              setChoices({});
            })
          }
        >
          预览合并冲突
        </Button>
        {preview ? (
          <>
            <p>
              {preview.versions.length} 个来源版本；{preview.parameters.length}{" "}
              份参数修订；{preview.drafts.length} 份未验证资料（保留原归属）。
              当前团队默认：{preview.team_default || "未设置"}；原版本选择：{JSON.stringify(preview.defaults)}。
            </p>
            {summaries.map((s) => (
              <Field key={s}>
                <FieldLabel htmlFor={`choice-${s}`}>{s} 的将来参数</FieldLabel>
                <select
                  id={`choice-${s}`}
                  value={
                    choices[s] ? `${choices[s].id}:${choices[s].version}` : ""
                  }
                  onChange={(e) => {
                    const p = parameters.find(
                      (p) => `${p.id}:${p.version}` === e.target.value,
                    );
                    if (p)
                      setChoices((old) => ({
                        ...old,
                        [s]: { id: p.id, version: p.version },
                      }));
                  }}
                >
                  <option value="">请选择明确修订</option>
                  {parameters
                    .filter((p) => p.config.source === s)
                    .map((p) => (
                      <option
                        key={`${p.id}:${p.version}`}
                        value={`${p.id}:${p.version}`}
                      >
                        {p.id} / r{p.version} {JSON.stringify(p.config.values)}
                      </option>
                    ))}
                </select>
              </Field>
            ))}
            <Button
              disabled={busy}
              onClick={() =>
                void perform(async () => {
                  await post("/management/dataset-merge", {
                    source,
                    target,
                    revision: preview.revision,
                    parameter_choices: choices,
                  });
                  setPreview(undefined);
                })
              }
            >
              确认合并并保留参数历史
            </Button>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

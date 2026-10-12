import { useState } from "react";
import { Link } from "react-router-dom";
import { api, post, date, newIdempotencyKey, type Item } from "./api";
import { useLoad } from "./useLoad";
import { Title, ErrorNotice, Loading, SelectField } from "./shared";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Field, FieldLabel, FieldGroup } from "@/components/ui/field";

export function AttachmentsPage({ user }: { user: Item }) {
  const { data, error, loading, reload } = useLoad(() => api("/attachments"));
  const [action, setAction] = useState("create");
  const [target, setTarget] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File>();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>();
  const [result, setResult] = useState<Item>();
  const [receipt, setReceipt] = useState<{
    operation: string;
    key: string;
  } | null>(() => {
    try {
      return JSON.parse(
        sessionStorage.getItem(`attachment-receipt-${user.id}`) || "null",
      );
    } catch {
      return null;
    }
  });
  const [key, setKey] = useState(() => receipt?.key || newIdempotencyKey());
  const attachments: Item[] = data?.attachments || [];
  const maintainable = attachments.filter(
    (a) => user.role === "admin" || a.creator_id === user.id,
  );
  async function mutate(path: string, body: Item) {
    setBusy(true);
    setFailure(undefined);
    try {
      await api(path, { method: "PATCH", body: JSON.stringify(body) });
      reload();
    } catch (e) {
      setFailure(e);
    } finally {
      setBusy(false);
    }
  }
  async function lookup() {
    if (!receipt) return;
    setBusy(true);
    setFailure(undefined);
    try {
      setResult(
        await api(
          `/attachment-operations/${receipt.operation}/${encodeURIComponent(receipt.key)}`,
        ),
      );
      reload();
    } catch (e) {
      setFailure(e);
    } finally {
      setBusy(false);
    }
  }
  if (loading) return <Loading />;
  return (
    <>
      <Title
        title="团队附件"
        description="团队复用明确版本；更新发布新版本，已受理实验保留冻结输入。"
      />
      <ErrorNotice error={error || failure} />
      <Card>
        <CardHeader>
          <CardTitle>发布与登记</CardTitle>
          <CardDescription>
            派生也须上传自己的 ZIP。历史上传创建者未知，登记只记录登记者。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setFailure(undefined);
              const operation = `attachment_${action}`;
              const nextReceipt = { operation, key };
              setReceipt(nextReceipt);
              sessionStorage.setItem(
                `attachment-receipt-${user.id}`,
                JSON.stringify(nextReceipt),
              );
              try {
                let value: Item;
                if (action === "register") {
                  value = await post(
                    "/attachments/register",
                    { bundle_id: target, name, description },
                    key,
                  );
                } else {
                  const body = new FormData();
                  if (!file) throw new Error("请选择 ZIP 文件");
                  body.set("file", file);
                  body.set(
                    "metadata",
                    JSON.stringify(
                      action === "publish"
                        ? { notes: description }
                        : { name, description },
                    ),
                  );
                  const path =
                    action === "publish"
                      ? `/attachments/${target}/versions`
                      : action === "derive"
                        ? `/attachment-versions/${target}/derive`
                        : "/attachments";
                  value = await api(path, {
                    method: "POST",
                    body,
                    headers: { "Idempotency-Key": key },
                  });
                }
                setResult(value);
                reload();
              } catch (err) {
                setFailure(err);
              } finally {
                setBusy(false);
              }
            }}
          >
            <FieldGroup>
              <SelectField
                label="操作"
                name="attachment_action"
                value={action}
                onChange={(v) => {
                  setAction(v);
                  setTarget("");
                  setKey(newIdempotencyKey());
                  setResult(undefined);
                }}
              >
                <option value="create">新建附件与 v1</option>
                <option value="publish">发布后续版本</option>
                <option value="derive">从团队版本派生</option>
                <option value="register">登记旧 bundle ID</option>
              </SelectField>
              {action !== "create" ? (
                <SelectField
                  label={
                    action === "derive"
                      ? "来源版本"
                      : action === "register"
                        ? "历史上传"
                        : "维护附件"
                  }
                  name="attachment_target"
                  value={target}
                  onChange={setTarget}
                >
                  <option value="">请选择</option>
                  {action === "publish"
                    ? maintainable.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name} · {a.id}
                        </option>
                      ))
                    : action === "derive"
                      ? attachments.flatMap((a) =>
                          a.versions.map((v: Item) => (
                            <option
                              key={v.id}
                              value={v.id}
                              disabled={
                                !a.enabled ||
                                !v.enabled ||
                                v.availability !== "available"
                              }
                            >
                              {a.name} · v{v.number} · {v.id}
                            </option>
                          )),
                        )
                      : (data?.legacy_bundles || []).map((b: Item) => (
                          <option key={b.id} value={b.id}>
                            {b.id} · 历史上传，创建者未知
                          </option>
                        ))}
                </SelectField>
              ) : null}
              {action !== "publish" ? (
                <Field>
                  <FieldLabel htmlFor="attachment-name">显示名称</FieldLabel>
                  <Input
                    id="attachment-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    maxLength={128}
                    required
                  />
                </Field>
              ) : null}
              <Field>
                <FieldLabel htmlFor="attachment-description">
                  {action === "publish" ? "版本发布说明" : "说明"}
                </FieldLabel>
                <Input
                  id="attachment-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  maxLength={4096}
                />
              </Field>
              {action !== "register" ? (
                <Field>
                  <FieldLabel htmlFor="attachment-file">附件 ZIP</FieldLabel>
                  <Input
                    id="attachment-file"
                    type="file"
                    accept=".zip,application/zip"
                    required
                    onChange={(e) => setFile(e.target.files?.[0])}
                  />
                </Field>
              ) : null}
              <p className="text-muted-foreground break-all">
                幂等键：{key}。通信失败保留原输入与原键重试，或查回。
              </p>
              <div className="flex flex-wrap gap-2">
                <Button disabled={busy || (action !== "create" && !target)}>
                  提交附件操作
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy || !receipt}
                  onClick={lookup}
                >
                  查回上次写入
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => {
                    setKey(newIdempotencyKey());
                    setResult(undefined);
                  }}
                >
                  开始新操作
                </Button>
              </div>
              {result ? (
                <p role="status">
                  已提交 {result.attachment.name} · v{result.version.number} ·{" "}
                  {result.version.id} ·{" "}
                  {result.version.availability === "unavailable"
                    ? "输入不可用"
                    : "已可查回"}
                </p>
              ) : null}
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
      {attachments.map((a) => {
        const canMaintain = user.role === "admin" || user.id === a.creator_id;
        return (
          <Card key={a.id}>
            <CardHeader>
              <CardTitle>
                {a.name}{" "}
                <Badge variant="secondary">{a.enabled ? "启用" : "停用"}</Badge>
              </CardTitle>
              <CardDescription>
                {a.description} · 创建者 {a.creator} · {date(a.created)} ·{" "}
                {a.id}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {canMaintain ? (
                <form
                  className="flex flex-col gap-3"
                  onSubmit={async (e) => {
                    e.preventDefault();
                    const body = new FormData(e.currentTarget);
                    await mutate(`/attachments/${a.id}`, {
                      name: body.get("name"),
                      description: body.get("description"),
                    });
                  }}
                >
                  <FieldGroup>
                    <Field>
                      <FieldLabel htmlFor={`name-${a.id}`}>修改名称</FieldLabel>
                      <Input
                        id={`name-${a.id}`}
                        name="name"
                        defaultValue={a.name}
                        required
                        maxLength={128}
                      />
                    </Field>
                    <Field>
                      <FieldLabel htmlFor={`description-${a.id}`}>
                        修改说明
                      </FieldLabel>
                      <Input
                        id={`description-${a.id}`}
                        name="description"
                        defaultValue={a.description}
                        maxLength={4096}
                      />
                    </Field>
                  </FieldGroup>
                  <div className="flex gap-2">
                    <Button disabled={busy} variant="outline">
                      保存名称与说明
                    </Button>
                    <Button
                      type="button"
                      disabled={busy}
                      variant="outline"
                      onClick={() =>
                        mutate(`/attachments/${a.id}`, { enabled: !a.enabled })
                      }
                    >
                      {a.enabled ? "停用附件" : "恢复附件"}
                    </Button>
                  </div>
                </form>
              ) : null}
              <ul className="flex flex-col gap-4">
                {a.versions.map((v: Item) => (
                  <li key={v.id}>
                    <p>
                      <strong>v{v.number}</strong> ·{" "}
                      {v.enabled ? "启用" : "停用"} · 发布者 {v.publisher} ·{" "}
                      {date(v.created)}
                      {v.legacy ? " · 历史上传，原创建者未知" : ""}
                    </p>
                    <p>
                      {v.notes}{" "}
                      {v.source_version_id
                        ? ` · 派生自 ${v.source_version_id}`
                        : ""}
                    </p>
                    <p className="text-muted-foreground break-all">
                      {v.id} · {v.bundle_id} · SHA256 {v.digest}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {a.enabled &&
                      v.enabled &&
                      v.availability === "available" ? (
                        <Button asChild variant="outline">
                          <Link
                            to="/new"
                            state={{ request: { attachment_version_id: v.id } }}
                          >
                            使用 v{v.number} 新建实验
                          </Link>
                        </Button>
                      ) : (
                        <Badge variant="secondary">不可用于新实验</Badge>
                      )}
                      <Button
                        variant="outline"
                        disabled={busy || !a.enabled || !v.enabled}
                        onClick={() => {
                          setAction("derive");
                          setTarget(v.id);
                          setKey(newIdempotencyKey());
                          window.scrollTo(0, 0);
                        }}
                      >
                        派生此版本
                      </Button>
                      {canMaintain ? (
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            mutate(`/attachments/${a.id}/versions/${v.id}`, {
                              enabled: !v.enabled,
                            })
                          }
                        >
                          {v.enabled ? "停用版本" : "恢复版本"}
                        </Button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        );
      })}
    </>
  );
}

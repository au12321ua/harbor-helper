// Attachment packages (03 sections 6-7): members publish fixed versions; each trial of a
// model run installs the chosen ones in its own container before the agent starts.
import { Fragment, useRef, useState } from "react";
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
import { EmptyNote, ErrorAlert, Loading, PageTitle, Pill } from "@/components/common";
import { ApiError, api } from "@/lib/api";
import { ATTACHMENT_EFFECT, fmtBytes, fmtTime } from "@/lib/format";
import { useLoad, useSession } from "@/lib/hooks";
import type { Attachment } from "@/lib/types";

const EXAMPLE = `{
  "schema_version": 1,
  "name": "my-tools",
  "version": "1.0.0",
  "description": "说明（可选）",
  "effects": ["agent_tools"],
  "compatible_harnesses": ["terminus-2"],
  "provides": { "tools": ["mytool"], "env": [] }
}`;

function contentType(file: File): string {
  const name = file.name.toLowerCase();
  if (name.endsWith(".zip")) return "application/zip";
  if (name.endsWith(".tar")) return "application/x-tar";
  return "application/gzip";
}

export function AttachmentsPage() {
  const { me } = useSession();
  const list = useLoad(async () => (await api.get<Attachment[]>("attachments")).data);
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<Attachment | null>(null);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const upload = async () => {
    const file = input.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(undefined);
    try {
      const res = await api.upload<Attachment>("attachments", file, contentType(file));
      toast.success(`已发布 ${res.data.name} ${res.data.version}`);
      if (input.current) input.current.value = "";
      await list.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };
  const toggle = async (a: Attachment) => {
    if (open === a.id) {
      setOpen(null);
      return;
    }
    setOpen(a.id);
    setDetail(null);
    try {
      setDetail((await api.get<Attachment>(`attachments/${a.id}`)).data);
    } catch (err) {
      setError(err);
    }
  };
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setError(undefined);
    try {
      await fn();
      toast.success(done);
      await list.reload();
    } catch (err) {
      setError(err);
    }
  };
  const mayManage = (a: Attachment) => a.owner_id === me.id || me.role === "admin";
  const uploadErrors = error instanceof ApiError ? error.body.field_errors : [];

  return (
    <div className="grid gap-4">
      <PageTitle title="附件" />
      <Card>
        <CardHeader>
          <CardTitle className="text-base">已发布的附件</CardTitle>
          <CardDescription>
            附件是随模型运行加载的文件包，例如工具、SDK 或安装脚本。每个版本发布后内容固定。运行时，每个试次在自己的容器里复制附件到
            <code className="mx-1">/opt/maestro/attachments/</code>
            并运行其中的 <code>bootstrap.sh</code>，然后才开始 Agent；安装可以联网，Agent 和验证阶段仍按平台网络限制执行。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm">
          {list.loading && !list.data && <Loading />}
          <ErrorAlert error={list.error} />
          {list.data && list.data.length === 0 && <EmptyNote>还没有发布附件。</EmptyNote>}
          {list.data && list.data.length > 0 && (
            <div className="overflow-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>名称与版本</TableHead>
                    <TableHead>发布者</TableHead>
                    <TableHead>影响范围</TableHead>
                    <TableHead>Harness</TableHead>
                    <TableHead>内容</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {list.data.map((a) => (
                    <Fragment key={a.id}>
                      <TableRow>
                        <TableCell>
                          <button type="button" className="text-left" onClick={() => void toggle(a)}>
                            <span className="font-medium underline-offset-2 hover:underline">{a.name}</span>{" "}
                            <span className="font-mono text-xs">{a.version}</span>
                          </button>
                          <div className="font-mono text-[11px] text-muted-foreground" title={a.content_digest}>
                            {a.content_digest.slice(0, 19)}…
                          </div>
                        </TableCell>
                        <TableCell className="text-xs">
                          {a.owner_username ?? a.owner_id}
                          <div className="text-muted-foreground">{fmtTime(a.created_at)}</div>
                        </TableCell>
                        <TableCell className="text-xs">
                          {a.effects.map((e) => ATTACHMENT_EFFECT[e] ?? e).join("、")}
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {a.compatible_harnesses.includes("*") ? "任意" : a.compatible_harnesses.join(", ")}
                        </TableCell>
                        <TableCell className="text-xs">
                          {a.file_count} 个文件 · {fmtBytes(a.size_bytes)}
                          {a.has_bootstrap && (
                            <div>
                              <Pill tone="info">含安装脚本</Pill>
                            </div>
                          )}
                        </TableCell>
                        <TableCell>
                          <Pill tone={a.enabled ? "good" : "muted"}>{a.enabled ? "可用" : "停用"}</Pill>
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-right">
                          {mayManage(a) && (
                            <>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() =>
                                  void act(
                                    () => api.post(`attachments/${a.id}/enabled`, { enabled: !a.enabled }),
                                    a.enabled ? "已停用" : "已启用",
                                  )
                                }
                              >
                                {a.enabled ? "停用" : "启用"}
                              </Button>{" "}
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => void act(() => api.del(`attachments/${a.id}`), "已移入回收站")}
                              >
                                删除
                              </Button>
                            </>
                          )}
                        </TableCell>
                      </TableRow>
                      {open === a.id && (
                        <TableRow>
                          <TableCell colSpan={7} className="bg-muted/40">
                            {!detail && <Loading />}
                            {detail && (
                              <div className="grid gap-2 text-xs">
                                {detail.description && <p>{detail.description}</p>}
                                {(detail.provides.tools.length > 0 || detail.provides.env.length > 0) && (
                                  <p>
                                    提供：
                                    {[
                                      ...detail.provides.tools.map((x) => `工具 ${x}`),
                                      ...detail.provides.env.map((x) => `环境变量 ${x}`),
                                    ].join("、")}
                                  </p>
                                )}
                                <ul className="grid gap-0.5 font-mono">
                                  {(detail.files ?? []).map((f) => (
                                    <li key={f.path} title={f.sha256}>
                                      {f.executable ? "x " : "  "}
                                      {f.path} <span className="text-muted-foreground">({fmtBytes(f.size)})</span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                          </TableCell>
                        </TableRow>
                      )}
                    </Fragment>
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
          <CardDescription>
            上传 .tar.gz、.tar 或 .zip 包，根目录（或唯一的顶层目录）里放 manifest.json；可选 bootstrap.sh 由 bash
            运行，工作目录是附件目录，环境变量 MAESTRO_ATTACHMENT_DIR 指向它。上传只检查不运行；文件名只能用字母、数字和
            ._+@-，不能有链接。同名同版本再次上传相同内容会得到原版本，内容不同需改版本号。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <input ref={input} type="file" accept=".tar,.tar.gz,.tgz,.zip" className="text-sm" />
            <Button disabled={busy} onClick={() => void upload()}>
              {busy ? "上传中…" : "上传并发布"}
            </Button>
          </div>
          <ErrorAlert error={error} />
          {uploadErrors.length > 0 && (
            <ul className="grid gap-0.5 font-mono text-xs text-destructive">
              {uploadErrors.map((e, i) => (
                <li key={i}>
                  {e.path} · {e.code}
                  {e.message ? ` · ${e.message}` : ""}
                </li>
              ))}
            </ul>
          )}
          <details>
            <summary className="cursor-pointer text-xs text-muted-foreground">manifest.json 示例</summary>
            <pre className="mt-2 overflow-auto rounded-md bg-muted p-3 text-xs">{EXAMPLE}</pre>
            <p className="mt-1 text-xs text-muted-foreground">
              effects 目前支持 model_call、agent_tools、task_environment；改变验证或评分的附件暂不支持。compatible_harnesses
              填 Harness 适配器名，或 ["*"] 表示任意。provides 用于发现两个附件之间的冲突。
            </p>
          </details>
        </CardContent>
      </Card>
    </div>
  );
}

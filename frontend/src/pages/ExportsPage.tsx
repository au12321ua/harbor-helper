import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Download, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyNote, ErrorAlert, Loading, PageTitle, StatusPill } from "@/components/common";
import { API, api } from "@/lib/api";
import { EXPORT_STATE, fmtBytes, fmtTime, label, shortId } from "@/lib/format";
import { useInterval } from "@/lib/hooks";
import type { Export } from "@/lib/types";

const PENDING = new Set(["queued", "building"]);

function count(summary: Export["summary"], key: keyof NonNullable<Export["summary"]>): string {
  const value = summary?.[key];
  return typeof value === "number" ? String(value) : "—";
}

export function ExportsPage() {
  const [exports, setExports] = useState<Export[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (after: string | null) => {
    setLoading(true);
    try {
      const res = await api.get("/exports", { query: { cursor: after } });
      setExports((prev) => (after ? [...prev, ...res.data] : res.data));
      setCursor(res.meta.next_cursor ?? null);
      setError(undefined);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(null);
  }, [load]);

  const pending = exports.some((e) => PENDING.has(e.state));
  useInterval(() => void load(null), 2000, pending);

  return (
    <div>
      <PageTitle title="导出">
        {pending && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            打包中，每 2 秒自动刷新
          </span>
        )}
        <Button variant="outline" size="sm" onClick={() => void load(null)}>
          <RefreshCw />
          刷新
        </Button>
      </PageTitle>
      <p className="mb-4 text-sm text-muted-foreground">
        这里只列出你自己创建的导出。在运行列表勾选运行，或在运行详情点“导出”即可创建；压缩包含结果汇总、
        试次记录和仍在保留期内的产物，生成后限时可下载。
      </p>
      <ErrorAlert error={error} />
      {exports.length === 0 && !loading && !error && <EmptyNote>还没有导出。</EmptyNote>}
      {exports.length > 0 && (
        <div className="rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>导出</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>运行</TableHead>
                <TableHead className="text-right">大小</TableHead>
                <TableHead className="text-right">文件 / 缺失 / 警告</TableHead>
                <TableHead>创建</TableHead>
                <TableHead>到期</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {exports.map((item) => (
                <TableRow key={item.id} data-testid="export-row">
                  <TableCell className="font-mono text-xs" title={item.id}>
                    {shortId(item.id, 16)}
                    {item.digest && (
                      <div className="text-muted-foreground" title={item.digest}>
                        {shortId(item.digest, 20)}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusPill value={label(EXPORT_STATE, item.state)} />
                    {item.state === "failed" && item.error && (
                      <div className="mt-1 max-w-xs text-xs text-red-700">
                        {item.error.message ?? item.error.code}（{item.error.code}）
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">
                    {item.request.run_ids.slice(0, 3).map((id) => (
                      <div key={id}>
                        <Link className="font-mono text-primary hover:underline" to={`/runs/${id}`}>
                          {shortId(id)}
                        </Link>
                      </div>
                    ))}
                    {item.request.run_ids.length > 3 && (
                      <div className="text-muted-foreground">
                        等 {item.request.run_ids.length} 个
                      </div>
                    )}
                    {!item.request.include_artifacts && (
                      <div className="text-muted-foreground">不含产物</div>
                    )}
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums">
                    {fmtBytes(item.size_bytes)}
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums">
                    {count(item.summary, "files")} / {count(item.summary, "missing")} /{" "}
                    {count(item.summary, "warnings")}
                  </TableCell>
                  <TableCell className="text-xs">{fmtTime(item.created_at)}</TableCell>
                  <TableCell className="text-xs">{fmtTime(item.expires_at)}</TableCell>
                  <TableCell className="text-right">
                    {item.state === "ready" && (
                      <Button asChild size="sm" variant="outline">
                        <a href={item.links.download ?? `${API}/exports/${item.id}/download`}>
                          <Download />
                          下载
                        </a>
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {loading && exports.length === 0 && <Loading />}
      {cursor && !loading && (
        <div className="mt-4 flex justify-center">
          <Button variant="outline" onClick={() => void load(cursor)}>
            加载更多
          </Button>
        </div>
      )}
    </div>
  );
}

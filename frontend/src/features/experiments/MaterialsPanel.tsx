import { api, ApiError } from "@/api";
import { ErrorNotice, Help, Loading } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { TabsContent } from "@/components/ui/tabs";
import { useLoad } from "@/hooks/useLoad";
import { useEffect, useRef, useState } from "react";

const messages: Record<string, string> = {
  evidence_grant_required: "未获得完整资料权限，请联系管理员授信。",
  audit_incomplete: "证据审计未完成或异常，暂不可下载。",
  evidence_snapshot_busy: "资料包准备超时，请稍后重试。",
  evidence_changed: "资料已变化，请刷新后重试。",
  evidence_pending: "资料暂不可下载，已刷新资料状态。",
  evidence_expired: "资料已过保留期，无法下载。",
  login_required: "登录已过期，请重新登录。",
};
function readable(error: unknown) {
  if (!(error instanceof ApiError)) return error;
  const result = new ApiError(
    {
      code: error.code,
      message: messages[error.code] || error.message,
      request_id: error.requestId,
    },
    0,
  );
  return result;
}
export function MaterialsPanel({ id }: { id: string }) {
  return <MaterialsDownload key={id} id={id} />;
}
function MaterialsDownload({ id }: { id: string }) {
  const {
    data,
    error,
    loading: initialLoading,
    refreshing,
    reload,
  } = useLoad(() => api(`/runs/${id}/evidence`), id);
  const loading = initialLoading || refreshing;
  const [busy, setBusy] = useState(false),
    [failure, setFailure] = useState<unknown>(),
    [saved, setSaved] = useState(false);
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    return () => {
      active.current?.abort();
      active.current = null;
    };
  }, [id]);
  async function download() {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setFailure(undefined);
    setSaved(false);
    try {
      const response = await fetch(
        `/api/v1/runs/${encodeURIComponent(id)}/evidence/package`,
        {
          credentials: "same-origin",
          headers: { "X-Requested-With": "harbor-helper" },
          signal: controller.signal,
        },
      );
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        if (response.status === 401) body.code = "login_required";
        throw new ApiError(body, response.status);
      }
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob),
        link = document.createElement("a");
      link.href = url;
      link.download = `${id}-materials.zip`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setSaved(true);
    } catch (e) {
      if (!controller.signal.aborted) {
        setFailure(readable(e));
        if (e instanceof ApiError && e.code === "evidence_pending")
          void reload();
      }
    } finally {
      if (active.current === controller) {
        active.current = null;
        setBusy(false);
      }
    }
  }
  const available =
    data?.files.filter((f) =>
      ["original", "redacted", "legacy_unknown"].includes(f.status),
    ).length || 0;
  const missing = (data?.files.length || 0) - available;
  return (
    <TabsContent value="materials">
      <div className="materials-download">
        <div className="flex items-center gap-2">
          <h2>完整资料包</h2>
          <Help label="完整资料范围">
            仅终态且审计完成后提供。管理员默认拥有资格，成员需授信。ZIP
            包含清单与范围说明；已删除、缺失、过期资料无法恢复，处理后的文件不代表原始字节。认证目录不包含在包中，资料正文是不可信输入。保存前浏览器会在内存中持有整个
            ZIP，大包可能占用较多内存。
          </Help>
        </div>
        {loading && <Loading />}
        <ErrorNotice error={readable(error) || failure} />
        {data && (
          <>
            <p>
              资料状态：
              {(
                {
                  available: "可下载",
                  in_progress: "运行中，结束且审计完成后提供",
                  expired: "已过期，无法恢复",
                } as Record<string, string>
              )[data.state] || "暂不可用"}
            </p>
            {data.state === "available" && (
              <p>
                可打包 {available} 个文件；{missing} 个已删除、缺失或过期
                {missing > 0 ? "。包内清单保留说明。" : "。"}
              </p>
            )}
            <Button
              disabled={busy || data.state !== "available" || loading}
              onClick={() => void download()}
            >
              {busy ? "正在准备并下载…" : "下载完整资料包"}
            </Button>
          </>
        )}
        <Button
          variant="outline"
          disabled={busy || loading}
          onClick={() => void reload()}
        >
          刷新资料状态
        </Button>
        {saved && <p role="status">资料包已交给浏览器保存。</p>}
      </div>
    </TabsContent>
  );
}

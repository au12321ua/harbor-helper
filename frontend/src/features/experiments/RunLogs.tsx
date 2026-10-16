import { api, ApiError, type Logs } from "@/api";
import { ErrorNotice, Loading } from "@/components/shared";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Copy, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
export function RunLogs({ id }: { id: string }) {
  const [value, setValue] = useState<Logs>();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const lifecycle = useRef({ token: 0, active: true });
  const refresh = useCallback(async () => {
    const requests = lifecycle.current;
    const current = ++requests.token;
    setBusy(true);
    try {
      const logs = await api(`/runs/${id}/logs`);
      if (requests.active && current === requests.token) {
        setValue(logs);
        setError(undefined);
      }
    } catch (e) {
      if (requests.active && current === requests.token) {
        setError(e);
        setValue(undefined);
      }
    } finally {
      if (requests.active && current === requests.token) setBusy(false);
    }
  }, [id]);
  useEffect(() => {
    const requests = lifecycle.current;
    requests.active = true;
    let active = true;
    queueMicrotask(() => {
      if (active) void refresh();
    });
    return () => {
      active = false;
      requests.active = false;
    };
  }, [refresh]);
  const restricted =
    error instanceof ApiError &&
    ["audit_incomplete", "evidence_expired"].includes(error.code);
  return (
    <section aria-label="运行日志内容">
      <div className="log-toolbar">
        <span className="mono">run.log</span>
        <span>原文日志 · 刷新获取</span>
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={() => void refresh()}
        >
          <RefreshCw />
          刷新日志
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={!value || busy}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(value?.text || "");
              toast.success("日志已复制");
            } catch {
              toast.error("无法复制日志，请手动选择文本");
            }
          }}
        >
          <Copy />
          复制
        </Button>
      </div>
      {restricted ? (
        <Alert>
          <AlertTitle>
            {error.code === "audit_incomplete"
              ? "日志安全审计异常"
              : "日志证据已过期"}
          </AlertTitle>
          <AlertDescription>
            {error.code === "audit_incomplete"
              ? "审计未完成或异常，日志暂不可展示。"
              : "日志保留期已结束，原文不可获取。"}
            <p>{error.message}</p>
          </AlertDescription>
        </Alert>
      ) : (
        <ErrorNotice error={error} />
      )}
      {value?.truncated && (
        <p className="quiet-note" role="status">
          仅显示末尾最多 256 KiB（已截断）
        </p>
      )}
      {value ? (
        <pre className="log-view">{value.text || "暂无日志内容"}</pre>
      ) : busy ? (
        <Loading />
      ) : null}
    </section>
  );
}

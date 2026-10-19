import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const blockingPhases = new Set([
  "backup",
  "adapting",
  "migrating",
  "switching",
  "verifying",
  "restoring",
  "commit_decided",
  "releasing",
  "needs_manual",
]);

export function UpgradeStatus() {
  const [phase, setPhase] = useState<string>();
  const [stale, setStale] = useState(false);
  const wasBlocked = useRef(false);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    let live = true;
    async function poll() {
      try {
        const [status, build] = await Promise.all([
          fetch("/api/v1/upgrade-phase", { cache: "no-store" }).then(
            (response) => (response.ok ? response.json() : undefined),
          ),
          fetch("/api/v1/build", { cache: "no-store" }).then((response) =>
            response.ok ? response.json() : undefined,
          ),
        ]);
        if (!live) return;
        const current =
          status?.upgrading && typeof status.phase === "string"
            ? status.phase
            : undefined;
        setPhase(current);
        if (wasBlocked.current && !current) {
          window.location.reload();
          return;
        }
        wasBlocked.current = !!current && blockingPhases.has(current);
        const loaded = document.querySelector<HTMLMetaElement>(
          'meta[name="hh-build"]',
        )?.content;
        if (
          loaded &&
          typeof build?.build === "string" &&
          loaded !== build.build
        )
          setStale(true);
      } catch {
        /* A stopped HTTP process is expected during a switch; keep the last known phase. */
      }
    }
    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, 3000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);
  const blocking = !!phase && blockingPhases.has(phase);
  useEffect(() => {
    if (blocking) dialog.current?.showModal();
    else dialog.current?.close();
  }, [blocking]);
  return (
    <>
      {(phase && !blocking) || stale ? (
        <div
          role="status"
          className="flex flex-wrap items-center justify-center gap-2 border-b bg-muted p-2 text-sm"
        >
          {phase
            ? "服务正在准备更新或等待实验结束；已有任务继续执行。"
            : "页面构建已过期。"}
          {stale ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.location.reload()}
            >
              刷新页面
            </Button>
          ) : null}
        </div>
      ) : null}
      {blocking ? (
        <dialog
          ref={dialog}
          onCancel={(event) => event.preventDefault()}
          aria-labelledby="upgrade-status-title"
          className="fixed inset-0 m-auto w-[calc(100%-2rem)] max-w-md rounded-lg border bg-card p-0 text-card-foreground shadow-lg backdrop:bg-background/95"
        >
          <CardHeader>
            <CardTitle id="upgrade-status-title">
              {phase === "needs_manual"
                ? "更新需要宿主管理员处理"
                : "服务更新中"}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <p>服务正在保护数据，暂时不能登录或操作实验。页面会自动重连。</p>
            <Button variant="outline" onClick={() => window.location.reload()}>
              重新连接
            </Button>
          </CardContent>
        </dialog>
      ) : null}
    </>
  );
}

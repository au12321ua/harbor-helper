import { useState } from "react";
import { api, post } from "@/api";
import { useLoad } from "@/hooks/useLoad";
import { ErrorNotice, Help } from "@/components/shared";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";

const labels: Record<string, string> = {
  preparing: "准备中",
  queued: "排队",
  starting: "启动中",
  running: "执行中",
  cancelling: "取消收尾",
  cleanup_blocked: "资源释放未确认",
  audit_incomplete: "证据审计异常（不占执行容量）",
};
export function ShutdownPanel() {
  const {
    data,
    error: loadError,
    reload,
  } = useLoad(() => api("/admin/shutdown"), "", 2000);
  const [confirmClose, setConfirmClose] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  async function act(mode: "wait" | "cancel" | "abort" | "close") {
    setBusy(true);
    setError(undefined);
    try {
      if (mode === "close") {
        await api("/admin/maintenance", {
          method: "PATCH",
          body: { paused: true, reason: "服务维护" },
        });
        setConfirmClose(false);
        const status = await api("/admin/shutdown");
        if (
          Object.entries(status.counts).every(
            ([key, count]) => key === "audit_incomplete" || count === 0,
          )
        ) {
          await post("/admin/shutdown", { mode: "wait" });
        }
      } else {
        await post("/admin/shutdown", { mode });
        setConfirmCancel(false);
      }
      await reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  const unfinished = data
    ? Object.entries(data.counts).some(
        ([key, count]) => key !== "audit_incomplete" && count > 0,
      )
    : false;
  return (
    <Card>
      <CardHeader>
        <div className="field-heading">
          <CardTitle>正常停止调度器</CardTitle>
          <Help label="正常停止调度器">
            先关闭新受理，再处理全部已受理任务。HTTP
            继续提供观察；完整停机、升级和卸载由主机管理入口完成。
          </Help>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <ErrorNotice error={error || loadError} />
        {data && (
          <>
            <p>
              持久维护开关：
              {data.maintenance.paused
                ? "已关闭新受理（跳过关闭确认）"
                : "仍开放新受理"}
            </p>
            <dl>
              {Object.entries(data.counts).map(([key, count]) => (
                <div key={key} className="flex justify-between gap-4">
                  <dt>{labels[key] || key}</dt>
                  <dd>{count}</dd>
                </div>
              ))}
            </dl>
            <p>
              停止意图：
              {data.intent.phase === "complete"
                ? "已安全排空，调度器已请求正常退出"
                : data.intent.phase === "draining"
                  ? data.intent.mode === "wait"
                    ? "等待全部已受理任务结束"
                    : "取消全部未完成任务并清理资源"
                  : "未请求停止"}
            </p>
            {data.counts.cleanup_blocked > 0 && (
              <Alert>
                <AlertTitle>停止尚未完成</AlertTitle>
                <AlertDescription>
                  执行资源尚未确认释放。保留任务记录，调度器将继续重试清理；可在实验详情查看并恢复处理。
                </AlertDescription>
              </Alert>
            )}
            {confirmClose && !data.maintenance.paused && (
              <Alert>
                <AlertTitle>确认关闭新受理？</AlertTitle>
                <AlertDescription>
                  提交、重跑、重试和恢复将停止受理。查询、取消、已有请求回执仍可用。重启不会自动开放。
                </AlertDescription>
                <div className="button-row">
                  <Button disabled={busy} onClick={() => void act("close")}>
                    同意关闭新受理
                  </Button>
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => setConfirmClose(false)}
                  >
                    拒绝并返回
                  </Button>
                </div>
              </Alert>
            )}
            {confirmCancel && (
              <Alert>
                <AlertTitle>确认取消全部未完成任务？</AlertTitle>
                <AlertDescription>
                  包括准备、排队和执行中的任务。资源清理需要时间；历史保留，可重跑，不会从中断点续跑。
                </AlertDescription>
                <div className="button-row">
                  <Button
                    variant="destructive"
                    disabled={busy}
                    onClick={() => void act("cancel")}
                  >
                    确认取消全部并停止
                  </Button>
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => setConfirmCancel(false)}
                  >
                    返回，不取消
                  </Button>
                </div>
              </Alert>
            )}
          </>
        )}
      </CardContent>
      <CardFooter className="flex flex-wrap gap-2">
        {data &&
          (!data.maintenance.paused ? (
            <Button disabled={busy} onClick={() => setConfirmClose(true)}>
              开始停止流程
            </Button>
          ) : (
            <>
              <Button
                disabled={
                  busy ||
                  data.intent.phase === "complete" ||
                  (data.intent.mode === "cancel" &&
                    data.intent.phase === "draining")
                }
                onClick={() => void act("wait")}
              >
                {unfinished ? "等待全部结束后停止" : "停止空闲调度器"}
              </Button>
              <Button
                variant="destructive"
                disabled={busy || data.intent.phase === "complete"}
                onClick={() => setConfirmCancel(true)}
              >
                取消全部未完成任务后停止
              </Button>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => void act("abort")}
              >
                退出等待，保持入口关闭
              </Button>
            </>
          ))}
      </CardFooter>
    </Card>
  );
}

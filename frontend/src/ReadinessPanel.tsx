import { useState } from "react";
import { api, date, type Readiness } from "./api";
import { useLoad } from "./useLoad";
import { ErrorNotice } from "./shared";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Field, FieldLabel, FieldDescription } from "@/components/ui/field";

function Status({ value }: { value: Readiness }) {
  const activity = value.scheduler;
  return (
    <Alert>
      <AlertTitle>
        {value.accepting ? "允许新受理" : "暂不接受新实验"}
      </AlertTitle>
      <AlertDescription>
        <p>
          {value.maintenance?.paused
            ? `维护暂停：${value.maintenance.reason || "未填写原因"}`
            : "受理取决于调度器当前活动与容量。"}
        </p>
        <p>
          调度器：
          {activity?.state === "ready"
            ? "活动已确认"
            : activity?.state === "unavailable"
              ? "不可用"
              : "活动未知"}{" "}
          · 观察时间 {date(value.observed)}
        </p>
        <p>
          {value.maintenance?.retry_at
            ? `建议重试时间 ${date(value.maintenance.retry_at)}（不会自动恢复）`
            : "等待时长未知，不提供预计开始时间。"}
        </p>
        <p>
          已有任务继续排空，查询、取消与安全报告可用。就绪不保证 Docker、Hub
          或模型执行成功。
        </p>
      </AlertDescription>
    </Alert>
  );
}

export function ReadinessNotice() {
  const { data, error } = useLoad(() => api("/readiness"), "", 4000);
  return (
    <>
      <ErrorNotice error={error} />
      {data ? (
        <>
          <Status value={data} />
          <p className="muted">
            本人待处理 {data.pending.member_pending} /{" "}
            {data.pending.member_limit} · 全局待处理{" "}
            {data.pending.global_pending} / {data.pending.global_limit}
          </p>
        </>
      ) : null}
    </>
  );
}

export function MaintenancePanel({
  readiness,
  saved,
}: {
  readiness?: Readiness;
  saved: () => void;
}) {
  const {
    data,
    error: loadError,
    reload,
  } = useLoad(() => api("/readiness"), "", 4000);
  const value = data || readiness;
  const [reason, setReason] = useState("");
  const [retry, setRetry] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  async function update(paused: boolean) {
    setBusy(true);
    setError(undefined);
    try {
      await api("/admin/maintenance", {
        method: "PATCH",
        body: {
          paused,
          reason: paused ? reason : "",
          retry_at: paused && retry ? new Date(retry).getTime() / 1000 : null,
        },
      });
      reload();
      saved();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>新受理维护开关</CardTitle>
        <CardDescription>
          暂停持久保存，重启保持。已受理任务继续执行；暂停不能代替停写与一致备份。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ErrorNotice error={error || loadError} />
        {value ? <Status value={value} /> : null}
        <Field>
          <FieldLabel htmlFor="maintenance-reason">维护原因</FieldLabel>
          <Textarea
            id="maintenance-reason"
            value={reason}
            maxLength={500}
            onChange={(e) => setReason(e.target.value)}
          />
          <FieldDescription>
            向授权成员显示，请勿填写秘密或内部路径。
          </FieldDescription>
        </Field>
        <Field>
          <FieldLabel htmlFor="maintenance-retry">
            建议重试时间（可选）
          </FieldLabel>
          <Input
            id="maintenance-retry"
            type="datetime-local"
            value={retry}
            onChange={(e) => setRetry(e.target.value)}
          />
        </Field>
        <div className="button-row">
          <Button disabled={busy} onClick={() => void update(true)}>
            暂停新受理
          </Button>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => void update(false)}
          >
            恢复新受理
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

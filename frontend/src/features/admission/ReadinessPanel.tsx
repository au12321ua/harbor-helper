import {
  localCandidates,
  localTime,
  offsetLabel,
  timezone,
  useTimezone,
} from "@/app/timezone";
import { api, type Limits, type Usage, type Readiness } from "@/api";
import { ErrorNotice, Help } from "@/components/shared";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useLoad } from "@/hooks/useLoad";
import { date } from "@/presentation";
import { CircleCheck, TriangleAlert } from "lucide-react";
import { useState } from "react";

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

export function ReadinessSummary({
  value,
  usage,
  limits,
  stale = false,
}: {
  value: Readiness;
  usage?: Usage;
  limits?: Limits;
  stale?: boolean;
}) {
  const normal =
    value.accepting &&
    value.scheduler.state === "ready" &&
    !value.maintenance.paused;
  return (
    <div
      className={`capacity-strip ${stale ? "stale" : ""}`}
      aria-label="受理与容量"
    >
      <span className={`admission-state ${normal ? "" : "warning"}`}>
        {normal ? (
          <CircleCheck aria-hidden="true" />
        ) : (
          <TriangleAlert aria-hidden="true" />
        )}
        {normal
          ? "允许新受理 · 受理正常"
          : value.maintenance.paused
            ? "暂不接受新实验 · 维护暂停"
            : value.scheduler.state === "unavailable"
              ? "暂不接受新实验 · 调度器不可用"
              : "暂不接受新实验 · 调度器活动未知"}
      </span>
      {usage && (
        <>
          <span title="包含启动、运行、取消中及资源清理阻塞的实验">
            实验槽位
            <b>
              {usage.active_jobs} / {limits?.max_jobs ?? "—"}
            </b>
          </span>
          <span title="活动实验预留的 concurrency 之和，不代表实时执行数">
            trial 槽位
            <b>
              {usage.active_trials} / {limits?.max_trials ?? "—"}
            </b>
          </span>
          <span>
            排队<b>{usage.queued_jobs}</b>
          </span>
        </>
      )}
      <span>
        全局待处理
        <b>
          {value.pending.global_pending} / {value.pending.global_limit}
        </b>
      </span>
      <span>
        本人待处理
        <b>
          {value.pending.member_pending} / {value.pending.member_limit}
        </b>
      </span>
      {!normal && (
        <span className="readiness-reason">
          {value.maintenance.paused
            ? `维护暂停：${value.maintenance.reason || "未填写原因"}。${value.maintenance.retry_at ? `建议重试时间 ${date(value.maintenance.retry_at)}。` : ""}不会自动恢复。`
            : `调度器：${value.scheduler.state === "unavailable" ? "不可用" : "活动未知"} · ${value.scheduler.reason || value.reason || "等待活动确认"}`}{" "}
          就绪不保证 Docker、Hub 或模型执行成功。
        </span>
      )}
    </div>
  );
}
export function ReadinessNotice() {
  const { data, error, updatedAt } = useLoad(() => api("/readiness"), "", 4000);
  return (
    <>
      <ErrorNotice error={error} />
      {data && <ReadinessSummary value={data} stale={!!error} />}
      {error && (
        <p className="freshness">
          上次成功更新 {updatedAt ? date(updatedAt / 1000) : "未知"} · 刷新失败
        </p>
      )}
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
  useTimezone();
  const zone = timezone();
  const [retryInput, setRetryInput] = useState({
    text: "",
    zone,
    epoch: null as number | null,
  });
  const [offset, setOffset] = useState("");
  const retry =
    retryInput.epoch !== null
      ? localTime(retryInput.epoch, zone)
      : retryInput.text;
  const candidates = localCandidates(retry, zone);
  const chosen =
    retryInput.epoch ??
    (candidates.length === 1
      ? candidates[0]
      : offset && candidates.includes(Number(offset))
        ? Number(offset)
        : null);
  const needsConfirmation =
    retryInput.epoch === null && retryInput.zone !== zone && !!retry;
  const timeError = !retry
    ? ""
    : needsConfirmation
      ? "时区已变更；尚未解析的输入须在新时区重新确认。"
      : !candidates.length
        ? "此时区中该本地时刻不存在，请修改。"
        : chosen === null
          ? "此时刻重复，请选择明确偏移。"
          : "";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  async function update(paused: boolean) {
    if (paused && timeError) return;
    setBusy(true);
    setError(undefined);
    try {
      await api("/admin/maintenance", {
        method: "PATCH",
        body: {
          paused,
          reason: paused ? reason : "",
          retry_at: paused && retry ? chosen : null,
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
        <div className="field-heading">
          <CardTitle>新受理维护开关</CardTitle>
          <Help label="新受理维护开关">
            暂停持久保存，重启保持。已受理任务继续执行；暂停不能代替停写与一致备份。
          </Help>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
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
            建议重试时间（可选，{zone}）
          </FieldLabel>
          <Input
            id="maintenance-retry"
            type="datetime-local"
            value={retry}
            onChange={(e) => {
              const text = e.target.value,
                matches = localCandidates(text, zone);
              setOffset("");
              setRetryInput({
                text,
                zone,
                epoch: matches.length === 1 ? matches[0] : null,
              });
            }}
          />
        </Field>
        {needsConfirmation && (
          <Button
            variant="outline"
            onClick={() => {
              setOffset("");
              setRetryInput({
                text: retry,
                zone,
                epoch: candidates.length === 1 ? candidates[0] : null,
              });
            }}
          >
            在当前时区重新确认输入
          </Button>
        )}
        {candidates.length > 1 && (
          <Field>
            <FieldLabel htmlFor="maintenance-offset">
              选择重复时刻的明确偏移
            </FieldLabel>
            <select
              id="maintenance-offset"
              value={chosen === null ? "" : String(chosen)}
              onChange={(e) => {
                setOffset(e.target.value);
                if (e.target.value)
                  setRetryInput({
                    text: retry,
                    zone,
                    epoch: Number(e.target.value),
                  });
              }}
            >
              <option value="">请选择</option>
              {candidates.map((epoch) => (
                <option key={epoch} value={epoch}>
                  {offsetLabel(epoch, zone)} ·{" "}
                  {new Date(epoch * 1000).toISOString()}
                </option>
              ))}
            </select>
          </Field>
        )}
        {chosen !== null && retry && (
          <p>
            将提交绝对时刻：{new Date(chosen * 1000).toISOString()}（
            {offsetLabel(chosen, zone)}）
          </p>
        )}
        {timeError && <p role="alert">{timeError}</p>}
        <div className="button-row">
          <Button
            disabled={busy || !!timeError}
            onClick={() => void update(true)}
          >
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

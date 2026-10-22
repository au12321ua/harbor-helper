import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleDashed,
  CircleSlash,
  CircleX,
  Download,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  EmptyNote,
  ErrorAlert,
  JsonBlock,
  Loading,
  PageTitle,
  Pill,
  StatusPill,
} from "@/components/common";
import { API, api, errorText } from "@/lib/api";
import {
  ARTIFACT_STATE,
  ATTEMPT_STATE,
  CLEANUP_STATE,
  RESULT_COMPLETENESS,
  RUN_STATE,
  RUN_TERMINAL,
  TRIAL_STATE,
  fmtBytes,
  fmtTime,
  label,
  shortId,
  type Tone,
} from "@/lib/format";
import { useInterval, useSession } from "@/lib/hooks";
import type { Artifact, Attempt, Run, RunDetail, Trial } from "@/lib/types";
import { cn } from "@/lib/utils";

const TRIAL_TERMINAL = new Set(["scored", "execution_error", "not_started", "cancelled", "interrupted"]);

export function RunDetailPage() {
  const { runId = "" } = useParams();
  return <RunDetailView key={runId} runId={runId} />;
}

function RunDetailView({ runId }: { runId: string }) {
  const { me } = useSession();
  const [run, setRun] = useState<RunDetail>();
  const [trials, setTrials] = useState<Trial[]>();
  const [artifacts, setArtifacts] = useState<Artifact[]>();
  const [error, setError] = useState<unknown>();
  const [cancelling, setCancelling] = useState(false);

  const load = useCallback(async () => {
    try {
      const [r, t, a] = await Promise.all([
        api.get<RunDetail>(`runs/${runId}`),
        api.get<Trial[]>(`runs/${runId}/trials`),
        api.get<Artifact[]>(`runs/${runId}/artifacts`),
      ]);
      setRun(r.data);
      setTrials(t.data);
      setArtifacts(a.data);
      setError(undefined);
    } catch (err) {
      setError(err);
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const active = !!run && !RUN_TERMINAL.has(run.state);
  useInterval(() => void load(), 2000, active);

  const cancel = async () => {
    if (!window.confirm("确定取消该运行？已获得的评分结果会保留，未完成的试次将停止。")) return;
    setCancelling(true);
    try {
      const res = await api.post<Run>(`runs/${runId}/cancel`);
      toast.success(res.data.stop_requested ? "已请求取消" : "已提交取消");
      await load();
    } catch (err) {
      toast.error(`取消失败：${errorText(err)}`);
    } finally {
      setCancelling(false);
    }
  };

  if (!run) {
    return error ? <ErrorAlert error={error} title="无法加载运行" /> : <Loading />;
  }

  return (
    <div className="grid gap-4">
      <PageTitle title={run.name}>
        {active && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            每 2 秒自动刷新
          </span>
        )}
        <Button size="sm" variant="outline" onClick={() => void load()}>
          <RefreshCw />
          刷新
        </Button>
        {run.allowed_actions.includes("cancel") && (
          <Button
            size="sm"
            variant="destructive"
            disabled={cancelling || run.stop_requested}
            onClick={cancel}
          >
            {run.stop_requested ? "取消中…" : "取消运行"}
          </Button>
        )}
      </PageTitle>
      {error !== undefined && <ErrorAlert error={error} title="刷新失败（显示的是上次数据）" />}

      <Card>
        <CardContent className="grid gap-x-6 gap-y-2 pt-6 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <Info label="运行 ID" value={<code>{run.id}</code>} />
          <Info label="提交者" value={run.owner_id === me.id ? `我（${me.username}）` : `${run.owner.display_name}（${run.owner.username}）`} />
          <Info label="提交方式" value={run.pat_id ? <>PAT <code>{run.pat_id}</code></> : "网页会话"} />
          <Info
            label="来源"
            value={
              run.relation === "initial" ? (
                "首次运行"
              ) : (
                <>
                  {run.relation === "rerun" ? "重跑" : "修改后运行"}
                  {run.source_run_id && (
                    <Link className="ml-1 text-primary underline" to={`/runs/${run.source_run_id}`}>
                      {shortId(run.source_run_id)}
                    </Link>
                  )}
                </>
              )
            }
          />
          <Info label="数据集版本" value={<code>{run.dataset_version_id}</code>} />
          <Info label="Operation" value={<code>{run.operation_id}</code>} />
          <Info label="客户端请求标识" value={run.client_request_id ?? "—"} />
          <Info label="受理时间" value={fmtTime(run.accepted_at)} />
          <Info label="开始时间" value={fmtTime(run.started_at)} />
          <Info label="结束时间" value={fmtTime(run.finished_at)} />
          <Info label="总时限" value={fmtTime(run.deadline_at)} />
          {(run.stop_requested || run.stop_reason) && (
            <Info
              label="停止"
              value={
                <span className="text-amber-800">
                  {run.stop_requested ? "已请求停止" : ""} {run.stop_reason ?? ""}
                </span>
              }
            />
          )}
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Dimension title="生命周期" value={label(RUN_STATE, run.state)} raw={run.state} />
        <Dimension
          title="评分覆盖"
          value={label(RESULT_COMPLETENESS, run.result_completeness)}
          raw={run.result_completeness}
        />
        <Dimension title="产物保存" value={label(ARTIFACT_STATE, run.artifact_state)} raw={run.artifact_state} />
        <Dimension title="环境清理" value={label(CLEANUP_STATE, run.cleanup_state)} raw={run.cleanup_state} />
      </div>

      <Card>
        <CardContent className="flex flex-wrap gap-x-6 gap-y-2 pt-6 text-sm">
          <Count label="计划" value={run.counts.planned} />
          <Count label="排队" value={run.counts.queued} />
          <Count label="进行中" value={run.counts.active} />
          <Count label="已终结" value={run.counts.terminal} />
          <Count label="已评分" value={run.counts.scored} tone="good" />
          <Count label="执行错误" value={run.counts.errors} tone={run.counts.errors ? "bad" : undefined} />
          <Count label="未开始" value={run.counts.not_started} />
          <Count label="已取消" value={run.counts.cancelled} />
          <Count label="已中断" value={run.counts.interrupted} tone={run.counts.interrupted ? "bad" : undefined} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">配置快照</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm">
          <div className="grid gap-1 sm:grid-cols-3">
            <Info label="config_digest" value={<Digest value={run.snapshot.config_digest} />} />
            <Info label="snapshot_digest" value={<Digest value={run.snapshot.snapshot_digest} />} />
            <Info label="comparison_digest" value={<Digest value={run.snapshot.comparison_digest} />} />
          </div>
          <JsonBlock summary="生效配置（effective）" value={run.snapshot.effective} />
          <JsonBlock summary="来源（provenance）" value={run.snapshot.provenance} />
          <JsonBlock summary="策略（policy）" value={run.snapshot.policy} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">试次</CardTitle>
        </CardHeader>
        <CardContent>
          {!trials && <Loading />}
          {trials && trials.length === 0 && <EmptyNote>没有试次。</EmptyNote>}
          {trials && trials.length > 0 && (
            <TrialsTable trials={trials} artifacts={artifacts ?? []} />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">产物</CardTitle>
        </CardHeader>
        <CardContent>
          {!artifacts && <Loading />}
          {artifacts && artifacts.length === 0 && <EmptyNote>暂无产物。</EmptyNote>}
          {artifacts && artifacts.length > 0 && (
            <ArtifactTable artifacts={artifacts} trials={trials ?? []} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Info({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="break-all">{value}</div>
    </div>
  );
}

function Digest({ value }: { value: string }) {
  return (
    <code className="text-xs" title={value}>
      {shortId(value, 24)}
    </code>
  );
}

function Dimension({ title, value, raw }: { title: string; value: [string, Tone]; raw: string }) {
  return (
    <Card>
      <CardContent className="grid gap-1 pt-4 pb-4">
        <div className="text-xs text-muted-foreground">{title}</div>
        <div className="flex items-center gap-2">
          <StatusPill value={value} />
          <code className="text-xs text-muted-foreground">{raw}</code>
        </div>
      </CardContent>
    </Card>
  );
}

function Count({ label, value, tone }: { label: string; value: number; tone?: "good" | "bad" }) {
  return (
    <div>
      <span className="text-muted-foreground">{label} </span>
      <span
        className={cn(
          "font-semibold tabular-nums",
          tone === "good" && "text-emerald-700",
          tone === "bad" && "text-red-700",
        )}
      >
        {value}
      </span>
    </div>
  );
}

/** Score cell: 0 is a real zero; null is "未评分" with the reason. Never render null as 0. */
function ScoreCell({ trial }: { trial: Trial }) {
  const score = trial.result?.score;
  if (score !== null && score !== undefined) {
    return <span className="font-semibold tabular-nums">{String(score)}</span>;
  }
  const reason =
    trial.reason_code ??
    trial.result?.failure_cause ??
    trial.result?.exception_type ??
    (TRIAL_TERMINAL.has(trial.state) ? null : "进行中");
  return (
    <span className="text-muted-foreground">
      未评分
      {reason && <span className="ml-1 text-xs">（{reason}）</span>}
      {trial.result && !trial.result.reward_valid && trial.result.raw_score !== null && (
        <span className="ml-1 text-xs">原始值 {String(trial.result.raw_score)} 无效</span>
      )}
    </span>
  );
}

function TrialsTable({ trials, artifacts }: { trials: Trial[]; artifacts: Artifact[] }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) => {
    const next = new Set(open);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setOpen(next);
  };
  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-8" />
            <TableHead>任务</TableHead>
            <TableHead>重复</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>得分</TableHead>
            <TableHead>尝试次数</TableHead>
            <TableHead>原因</TableHead>
            <TableHead>产物 / 清理</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trials.map((trial) => {
            const expanded = open.has(trial.id);
            return [
              <TableRow
                key={trial.id}
                className="cursor-pointer"
                onClick={() => toggle(trial.id)}
                data-testid="trial-row"
              >
                <TableCell>
                  {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                </TableCell>
                <TableCell className="font-mono text-xs">{trial.task_key}</TableCell>
                <TableCell className="tabular-nums">{trial.repetition_index}</TableCell>
                <TableCell>
                  <StatusPill value={label(TRIAL_STATE, trial.state)} />
                  {trial.phase && !TRIAL_TERMINAL.has(trial.state) && (
                    <span className="ml-1 text-xs text-muted-foreground">{trial.phase}</span>
                  )}
                </TableCell>
                <TableCell>
                  <ScoreCell trial={trial} />
                </TableCell>
                <TableCell className="tabular-nums">{trial.attempts.length}</TableCell>
                <TableCell className="text-xs">
                  {trial.reason_code ?? trial.result?.failure_cause ?? "—"}
                </TableCell>
                <TableCell className="text-xs">
                  {label(ARTIFACT_STATE, trial.artifact_state)[0]} /{" "}
                  {label(CLEANUP_STATE, trial.cleanup_state)[0]}
                </TableCell>
              </TableRow>,
              expanded && (
                <TableRow key={`${trial.id}-detail`} className="bg-muted/30 hover:bg-muted/30">
                  <TableCell />
                  <TableCell colSpan={7}>
                    <AttemptSteps trial={trial} />
                    {trial.result && (
                      <div className="mt-2 text-xs text-muted-foreground">
                        验证：{trial.result.verifier_status ?? "—"} · 原始分{" "}
                        {trial.result.raw_score ?? "无"} · reward_valid{" "}
                        {String(trial.result.reward_valid)} · 策略 {trial.result.policy_version}
                      </div>
                    )}
                    <TrialArtifacts artifacts={artifacts.filter((a) => a.trial_id === trial.id)} />
                  </TableCell>
                </TableRow>
              ),
            ];
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function stepIcon(state: string) {
  switch (state) {
    case "completed":
      return <CircleCheck className="size-4 text-emerald-600" />;
    case "failed":
    case "interrupted":
      return <CircleX className="size-4 text-red-600" />;
    case "cancelled":
      return <CircleSlash className="size-4 text-amber-600" />;
    case "starting":
    case "preparing":
    case "executing":
    case "verifying":
      return <Loader2 className="size-4 animate-spin text-sky-600" />;
    default:
      return <CircleDashed className="size-4 text-muted-foreground" />;
  }
}

function duration(attempt: Attempt): string {
  if (!attempt.ended_at) return "进行中";
  const ms = new Date(attempt.ended_at).getTime() - new Date(attempt.started_at).getTime();
  if (Number.isNaN(ms)) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function AttemptSteps({ trial }: { trial: Trial }) {
  if (trial.attempts.length === 0) {
    return <div className="text-xs text-muted-foreground">尚无执行尝试。</div>;
  }
  return (
    <ol className="grid gap-1">
      {trial.attempts.map((attempt) => {
        const err = attempt.error;
        return (
          <li key={attempt.id} className="rounded-md border bg-background px-3 py-2">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              {stepIcon(attempt.state)}
              <span className="font-medium">第 {attempt.attempt_index} 次尝试</span>
              <StatusPill value={label(ATTEMPT_STATE, attempt.state)} />
              {attempt.phase && <Pill tone="muted">阶段 {attempt.phase}</Pill>}
              <span className="ml-auto text-xs text-muted-foreground">
                {fmtTime(attempt.started_at)} · {duration(attempt)}
              </span>
            </div>
            {err && (
              <div className="mt-1 rounded bg-red-50 px-2 py-1 font-mono text-xs text-red-800">
                {String(err.code ?? "ERROR")}
                {err.message ? `：${String(err.message)}` : ""}
                {err.stage ? `（stage ${String(err.stage)}）` : ""}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function TrialArtifacts({ artifacts }: { artifacts: Artifact[] }) {
  if (artifacts.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2 text-xs">
      {artifacts.map((a) => (
        <ArtifactLink key={a.id} artifact={a} />
      ))}
    </div>
  );
}

function ArtifactLink({ artifact }: { artifact: Artifact }) {
  const name = artifact.relative_path.split("/").pop() || artifact.relative_path;
  if (artifact.status !== "available") {
    return (
      <span className="text-muted-foreground" title={artifact.relative_path}>
        {name}（{artifact.status}）
      </span>
    );
  }
  return (
    <a
      className="inline-flex items-center gap-1 text-primary hover:underline"
      href={`${API}/artifacts/${artifact.id}/download`}
      title={artifact.relative_path}
    >
      <Download className="size-3" />
      {name}
    </a>
  );
}

function ArtifactTable({ artifacts, trials }: { artifacts: Artifact[]; trials: Trial[] }) {
  const trialName = new Map(trials.map((t) => [t.id, `${t.task_key} #${t.repetition_index}`]));
  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>文件</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>试次</TableHead>
            <TableHead>大小</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>到期</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {artifacts.map((a) => (
            <TableRow key={a.id}>
              <TableCell>
                <ArtifactLink artifact={a} />
                <div className="font-mono text-xs text-muted-foreground">{a.relative_path}</div>
              </TableCell>
              <TableCell className="text-xs">{a.kind}</TableCell>
              <TableCell className="text-xs">
                {a.trial_id ? trialName.get(a.trial_id) ?? shortId(a.trial_id) : "运行级"}
              </TableCell>
              <TableCell className="text-xs tabular-nums">{fmtBytes(a.size_bytes)}</TableCell>
              <TableCell>
                <Pill tone={a.status === "available" ? "good" : a.status === "expired" ? "warn" : "neutral"}>
                  {a.status}
                </Pill>
              </TableCell>
              <TableCell className="text-xs">{fmtTime(a.expires_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

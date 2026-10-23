import { useState, type ReactNode } from "react";
import { AlertTriangle, Check, Copy, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, errorText } from "@/lib/api";
import { fmtNum, type Tone } from "@/lib/format";
import type { RunScoring } from "@/lib/types";
import { cn } from "@/lib/utils";

const TONES: Record<Tone, string> = {
  neutral: "border-slate-300 bg-slate-100 text-slate-800",
  info: "border-sky-300 bg-sky-50 text-sky-800",
  good: "border-emerald-300 bg-emerald-50 text-emerald-800",
  warn: "border-amber-300 bg-amber-50 text-amber-900",
  bad: "border-red-300 bg-red-50 text-red-800",
  muted: "border-slate-200 bg-white text-slate-500",
};

export function Pill({
  tone,
  children,
  title,
}: {
  tone: Tone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONES[tone],
      )}
    >
      {children}
    </span>
  );
}

export function StatusPill({ value }: { value: [string, Tone] }) {
  return <Pill tone={value[1]}>{value[0]}</Pill>;
}

export function ErrorAlert({ error, title = "请求失败" }: { error: unknown; title?: string }) {
  if (!error) return null;
  const api = error instanceof ApiError ? error : null;
  return (
    <Alert variant="destructive" className="bg-red-50">
      <AlertTriangle className="size-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <div>{errorText(error)}</div>
        {api && api.body.field_errors.length > 0 && (
          <ul className="mt-1 list-disc pl-4 text-xs">
            {api.body.field_errors.map((f) => (
              <li key={`${f.path}-${f.code}`}>
                <code>{f.path}</code>：{f.message ?? f.code}
                {f.limit != null && `（限制 ${f.limit}）`}
              </li>
            ))}
          </ul>
        )}
        {api?.requestId && (
          <div className="mt-1 text-xs opacity-70">request_id: {api.requestId}</div>
        )}
      </AlertDescription>
    </Alert>
  );
}

export function Loading({ text = "加载中…" }: { text?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" />
      {text}
    </div>
  );
}

export function PageTitle({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-xl font-semibold">{title}</h1>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

export function JsonBlock({ value, summary }: { value: unknown; summary: string }) {
  return (
    <details className="rounded-md border bg-muted/40">
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium">{summary}</summary>
      <pre className="max-h-96 overflow-auto border-t px-3 py-2 text-xs">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

export function TextField({
  id,
  label,
  error,
  hint,
  ...props
}: React.ComponentProps<typeof Input> & {
  id: string;
  label: string;
  error?: string;
  hint?: string;
}) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} aria-invalid={error ? true : undefined} {...props} />
      {hint && !error && <p className="text-xs text-muted-foreground">{hint}</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

export function SelectField({
  id,
  label,
  error,
  children,
  ...props
}: React.ComponentProps<"select"> & { id: string; label: string; error?: string }) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        className="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        {...props}
      >
        {children}
      </select>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

/** A secret shown exactly once after creation (PAT or invitation link). */
export function OneTimeSecret({
  title,
  value,
  onDismiss,
}: {
  title: string;
  value: string;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast.success("已复制");
    } catch {
      toast.error("复制失败，请手动选择文本复制");
    }
  };
  return (
    <Alert className="border-amber-400 bg-amber-50">
      <AlertTriangle className="size-4 text-amber-700" />
      <AlertTitle className="text-amber-900">{title} · 只显示一次</AlertTitle>
      <AlertDescription className="grid gap-2">
        <p className="text-sm text-amber-900">
          离开或关闭后无法再次查看，请立即复制并妥善保存。
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <code
            data-testid="one-time-secret"
            className="max-w-full break-all rounded border bg-white px-2 py-1 text-xs"
          >
            {value}
          </code>
          <Button size="sm" variant="outline" onClick={copy}>
            {copied ? <Check /> : <Copy />}
            复制
          </Button>
          <Button size="sm" variant="ghost" onClick={onDismiss}>
            我已保存，关闭
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed py-8 text-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}

/** Mean with its coverage, never a bare mean: "0.5 · 已评分 4/5". */
export function ScoreCoverage({ scoring }: { scoring: RunScoring | null }) {
  if (!scoring) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="whitespace-nowrap tabular-nums" data-testid="score-coverage">
      <span className={cn("font-semibold", scoring.mean == null && "text-muted-foreground")}>
        {fmtNum(scoring.mean)}
      </span>
      <span className="text-xs text-muted-foreground">
        {" "}
        · 已评分 {scoring.scored_trials}/{scoring.planned_trials}
      </span>
    </span>
  );
}

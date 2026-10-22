import { useState, type FormEvent } from "react";
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
import {
  EmptyNote,
  ErrorAlert,
  Loading,
  OneTimeSecret,
  PageTitle,
  SelectField,
  StatusPill,
  TextField,
} from "@/components/common";
import { ApiError, api, errorText } from "@/lib/api";
import { PAT_STATE, fmtTime, label } from "@/lib/format";
import { limit, useLoad, useSession } from "@/lib/hooks";
import type { IssuedPat, Pat, Scope } from "@/lib/types";

export function SettingsPage() {
  const { me } = useSession();
  return (
    <div className="grid gap-4">
      <PageTitle title="个人设置" />
      <Card>
        <CardHeader>
          <CardTitle className="text-base">我的账户</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm sm:grid-cols-3">
          <div>
            <div className="text-xs text-muted-foreground">用户名</div>
            {me.username}
          </div>
          <div>
            <div className="text-xs text-muted-foreground">显示名称</div>
            {me.display_name || "—"}
          </div>
          <div>
            <div className="text-xs text-muted-foreground">角色</div>
            {me.role === "admin" ? "管理员" : "成员"}
          </div>
          <div>
            <div className="text-xs text-muted-foreground">用户 ID</div>
            <code className="text-xs">{me.id}</code>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">创建时间</div>
            {fmtTime(me.created_at)}
          </div>
          <div>
            <div className="text-xs text-muted-foreground">状态</div>
            {me.status === "active" ? "正常" : "已停用"}
          </div>
        </CardContent>
      </Card>
      <PasswordCard />
      <PatCard />
    </div>
  );
}

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (next !== confirm) {
      setError(new Error("两次输入的新密码不一致"));
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      await api.post("me/password", { current_password: current, new_password: next });
      toast.success("密码已修改");
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };
  const field = (name: string) => (error instanceof ApiError ? error.field(name) : undefined);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">修改密码</CardTitle>
      </CardHeader>
      <CardContent>
        <form className="grid max-w-md gap-3" onSubmit={submit}>
          <TextField
            id="pw-current"
            label="当前密码"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            error={field("current_password")}
            required
          />
          <TextField
            id="pw-new"
            label="新密码"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            error={field("new_password")}
            required
          />
          <TextField
            id="pw-confirm"
            label="确认新密码"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
          <ErrorAlert error={error} title="修改失败" />
          <div>
            <Button type="submit" disabled={busy}>
              {busy ? "提交中…" : "修改密码"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function PatCard() {
  const { capabilities } = useSession();
  const pats = useLoad(async () => (await api.get<Pat[]>("me/pats")).data);
  const defaultDays = limit(capabilities, "pat_default_days", 30);
  const maxDays = limit(capabilities, "pat_max_days", 365);
  const defaultRuns = limit(capabilities, "pat_default_run_limit", 1000);
  const maxRuns = limit(capabilities, "pat_max_run_limit", 1000);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<Scope>("experiment");
  const [days, setDays] = useState(String(defaultDays));
  const [runs, setRuns] = useState(String(defaultRuns));
  const [issued, setIssued] = useState<IssuedPat | null>(null);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const res = await api.post<IssuedPat>("me/pats", {
        name,
        scope,
        expires_in_days: days ? Number(days) : null,
        run_limit: runs ? Number(runs) : null,
      });
      setIssued(res.data);
      setName("");
      await pats.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (pat: Pat) => {
    if (!window.confirm(`撤销访问令牌「${pat.name}」？使用它的脚本将立即失效。`)) return;
    try {
      await api.del(`me/pats/${pat.id}`);
      toast.success("已撤销");
      await pats.reload();
    } catch (err) {
      toast.error(`撤销失败：${errorText(err)}`);
    }
  };
  const field = (n: string) => (error instanceof ApiError ? error.field(n) : undefined);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">个人访问令牌（PAT）</CardTitle>
        <CardDescription>
          供 SDK 与脚本使用。read 只能读取；experiment 还能提交和取消自己的运行。PAT
          不具备管理员权限。运行上限按受理的运行数扣减。
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {issued && (
          <OneTimeSecret
            title={`新令牌「${issued.name}」`}
            value={issued.token}
            onDismiss={() => setIssued(null)}
          />
        )}
        <form className="grid gap-3 md:grid-cols-5 md:items-end" onSubmit={submit}>
          <TextField
            id="pat-name"
            label="名称"
            value={name}
            onChange={(e) => setName(e.target.value)}
            error={field("name")}
            required
          />
          <SelectField
            id="pat-scope"
            label="权限范围"
            value={scope}
            onChange={(e) => setScope(e.target.value as Scope)}
            error={field("scope")}
          >
            <option value="experiment">experiment（提交与读取）</option>
            <option value="read">read（只读）</option>
          </SelectField>
          <TextField
            id="pat-days"
            label={`有效天数（≤ ${maxDays}）`}
            type="number"
            min={1}
            max={maxDays}
            value={days}
            onChange={(e) => setDays(e.target.value)}
            error={field("expires_in_days")}
          />
          <TextField
            id="pat-runs"
            label={`运行上限（≤ ${maxRuns}）`}
            type="number"
            min={1}
            max={maxRuns}
            value={runs}
            onChange={(e) => setRuns(e.target.value)}
            error={field("run_limit")}
          />
          <Button type="submit" disabled={busy}>
            {busy ? "创建中…" : "创建令牌"}
          </Button>
        </form>
        <ErrorAlert error={error} title="创建失败" />
        <ErrorAlert error={pats.error} title="无法加载令牌" />
        {pats.loading && !pats.data && <Loading />}
        {pats.data && pats.data.length === 0 && <EmptyNote>还没有令牌。</EmptyNote>}
        {pats.data && pats.data.length > 0 && (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>名称</TableHead>
                  <TableHead>前缀</TableHead>
                  <TableHead>范围</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>运行（已用 / 上限）</TableHead>
                  <TableHead>到期</TableHead>
                  <TableHead>最近使用</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {pats.data.map((pat) => (
                  <TableRow key={pat.id}>
                    <TableCell>{pat.name}</TableCell>
                    <TableCell className="font-mono text-xs">{pat.token_prefix}…</TableCell>
                    <TableCell>{pat.scope}</TableCell>
                    <TableCell>
                      <StatusPill value={label(PAT_STATE, pat.state)} />
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {pat.accepted_runs} / {pat.run_limit}
                      <span className="ml-1 text-xs text-muted-foreground">
                        （剩余 {pat.remaining_runs}）
                      </span>
                    </TableCell>
                    <TableCell className="text-xs">{fmtTime(pat.expires_at)}</TableCell>
                    <TableCell className="text-xs">{fmtTime(pat.last_used_at)}</TableCell>
                    <TableCell className="text-right">
                      {pat.state === "active" && (
                        <Button size="sm" variant="outline" onClick={() => void revoke(pat)}>
                          撤销
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

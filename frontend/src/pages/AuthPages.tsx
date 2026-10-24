import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorAlert, Loading, TextField } from "@/components/common";
import { ApiError, api } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import type { InvitationInfo, SessionInfo } from "@/lib/types";

type SignedIn = (session: SessionInfo) => void;

function AuthCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="text-sm font-semibold tracking-wide text-primary">Maestro</div>
          <CardTitle className="text-xl">
            <h1>{title}</h1>
          </CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </CardHeader>
        <CardContent>{children}</CardContent>
      </Card>
    </div>
  );
}

function fieldOf(error: unknown, name: string) {
  return error instanceof ApiError ? error.field(name) : undefined;
}

export function SetupPage({ onSignedIn }: { onSignedIn: SignedIn }) {
  const [form, setForm] = useState({
    setup_token: "",
    username: "",
    display_name: "",
    password: "",
  });
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const res = await api.post("/setup", {
        body: {
          ...form,
          display_name: form.display_name || null,
        },
      });
      onSignedIn(res.data);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCard
      title="初始化管理员"
      description={
        <>
          首次使用需创建第一个管理员。一次性初始化令牌由服务器上的 <code>maestro init</code>{" "}
          打印。
        </>
      }
    >
      <form className="grid gap-4" onSubmit={submit}>
        <TextField
          id="setup-token"
          label="初始化令牌"
          autoComplete="off"
          value={form.setup_token}
          onChange={set("setup_token")}
          error={fieldOf(error, "setup_token")}
          required
        />
        <TextField
          id="setup-username"
          label="管理员用户名"
          autoComplete="username"
          value={form.username}
          onChange={set("username")}
          error={fieldOf(error, "username")}
          required
        />
        <TextField
          id="setup-display"
          label="显示名称（可选）"
          value={form.display_name}
          onChange={set("display_name")}
          error={fieldOf(error, "display_name")}
        />
        <TextField
          id="setup-password"
          label="密码"
          type="password"
          autoComplete="new-password"
          value={form.password}
          onChange={set("password")}
          error={fieldOf(error, "password")}
          required
        />
        <ErrorAlert error={error} title="初始化失败" />
        <Button type="submit" disabled={busy}>
          {busy ? "提交中…" : "创建管理员并登录"}
        </Button>
      </form>
    </AuthCard>
  );
}

export function LoginPage({ onSignedIn }: { onSignedIn: SignedIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const res = await api.post("/session", { body: { username, password } });
      onSignedIn(res.data);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCard title="登录" description="账户由管理员邀请创建；忘记密码请联系管理员生成重置链接。">
      <form className="grid gap-4" onSubmit={submit}>
        <TextField
          id="login-username"
          label="用户名"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          error={fieldOf(error, "username")}
          required
        />
        <TextField
          id="login-password"
          label="密码"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={fieldOf(error, "password")}
          required
        />
        <ErrorAlert error={error} title="登录失败" />
        <Button type="submit" disabled={busy}>
          {busy ? "登录中…" : "登录"}
        </Button>
      </form>
    </AuthCard>
  );
}

function tokenFromLocation(hash: string, search: string): string {
  const fromHash = hash.replace(/^#/, "");
  if (fromHash) return decodeURIComponent(fromHash);
  return new URLSearchParams(search).get("token") ?? "";
}

export function InvitePage({ onSignedIn }: { onSignedIn: SignedIn }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [token] = useState(() => tokenFromLocation(location.hash, location.search));
  const [info, setInfo] = useState<InvitationInfo>();
  const [lookupError, setLookupError] = useState<unknown>();
  const [form, setForm] = useState({ username: "", display_name: "", password: "" });
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Drop the token from the address bar so it does not linger in history.
    if (location.hash || location.search) {
      window.history.replaceState(null, "", location.pathname);
    }
    if (!token) return;
    api
      .post("/invitations/lookup", { body: { token } })
      .then((res) => setInfo(res.data))
      .catch(setLookupError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!info) return;
    setBusy(true);
    setError(undefined);
    try {
      const body =
        info.kind === "invitation"
          ? {
              token,
              username: form.username,
              display_name: form.display_name || null,
              password: form.password,
            }
          : { token, password: form.password };
      const res = await api.post("/invitations/accept", { body: body });
      onSignedIn(res.data);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  if (!token) {
    return (
      <AuthCard title="邀请链接无效" description="链接中没有令牌。请向管理员索取完整链接。">
        <Link className="text-sm text-primary underline" to="/">
          返回登录
        </Link>
      </AuthCard>
    );
  }
  if (lookupError) {
    return (
      <AuthCard title="无法使用此链接">
        <div className="grid gap-3">
          <ErrorAlert error={lookupError} title="链接不可用" />
          <Link className="text-sm text-primary underline" to="/">
            返回登录
          </Link>
        </div>
      </AuthCard>
    );
  }
  if (!info) return <AuthCard title="检查链接">{<Loading />}</AuthCard>;

  const reset = info.kind === "password_reset";
  return (
    <AuthCard
      title={reset ? "重置密码" : "接受邀请"}
      description={
        reset ? (
          <>为账户 <b>{info.username ?? "—"}</b> 设置新密码。</>
        ) : (
          <>
            你被邀请为{info.role === "admin" ? "管理员" : "成员"}。设置用户名和密码后直接登录。
          </>
        )
      }
    >
      <form className="grid gap-4" onSubmit={submit}>
        <p className="text-xs text-muted-foreground">链接有效期至 {fmtTime(info.expires_at)}</p>
        {!reset && (
          <>
            <TextField
              id="invite-username"
              label="用户名"
              autoComplete="username"
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              error={fieldOf(error, "username")}
              required
            />
            <TextField
              id="invite-display"
              label="显示名称（可选）"
              value={form.display_name}
              onChange={(e) => setForm({ ...form, display_name: e.target.value })}
              error={fieldOf(error, "display_name")}
            />
          </>
        )}
        <TextField
          id="invite-password"
          label={reset ? "新密码" : "密码"}
          type="password"
          autoComplete="new-password"
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
          error={fieldOf(error, "password")}
          required
        />
        <ErrorAlert error={error} title="提交失败" />
        <Button type="submit" disabled={busy}>
          {busy ? "提交中…" : reset ? "设置新密码并登录" : "创建账户并登录"}
        </Button>
      </form>
    </AuthCard>
  );
}

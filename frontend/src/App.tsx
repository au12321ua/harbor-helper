import { useCallback, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { AlertTriangle, LogOut } from "lucide-react";
import { Toaster, toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ErrorAlert, Loading, Pill } from "@/components/common";
import { ApiError, api, errorText, setCsrfToken, setUnauthorizedHandler } from "@/lib/api";
import { SessionContext, useInterval, useSession, type SessionState } from "@/lib/hooks";
import type { Capabilities, Health, Me, SessionInfo } from "@/lib/types";
import { cn } from "@/lib/utils";
import { InvitePage, LoginPage, SetupPage } from "@/pages/AuthPages";
import { RunListPage } from "@/pages/RunListPage";
import { NewRunPage } from "@/pages/NewRunPage";
import { RunDetailPage } from "@/pages/RunDetailPage";
import { DatasetsPage } from "@/pages/DatasetsPage";
import { ExportsPage } from "@/pages/ExportsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { AdminPage } from "@/pages/AdminPage";

type Boot =
  | { phase: "loading" }
  | { phase: "error"; error: unknown }
  | { phase: "setup" }
  | { phase: "signed-out" }
  | { phase: "signed-in"; me: Me };

function useBoot() {
  const [boot, setBoot] = useState<Boot>({ phase: "loading" });

  const load = useCallback(async () => {
    try {
      const setup = await api.get<{ needs_setup: boolean }>("setup");
      if (setup.data.needs_setup) {
        setBoot({ phase: "setup" });
        return;
      }
      try {
        const session = await api.get<SessionInfo>("session");
        setCsrfToken(session.data.csrf_token);
        setBoot({ phase: "signed-in", me: session.data.user });
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) setBoot({ phase: "signed-out" });
        else throw err;
      }
    } catch (err) {
      setBoot({ phase: "error", error: err });
    }
  }, []);

  useEffect(() => {
    void load();
    setUnauthorizedHandler(() => {
      setCsrfToken(null);
      setBoot((current) => {
        if (current.phase === "signed-in") toast.error("登录已失效，请重新登录");
        return current.phase === "signed-in" ? { phase: "signed-out" } : current;
      });
    });
    return () => setUnauthorizedHandler(null);
  }, [load]);

  const signedIn = useCallback((session: SessionInfo) => {
    setCsrfToken(session.csrf_token);
    setBoot({ phase: "signed-in", me: session.user });
  }, []);

  return { boot, setBoot, signedIn, reload: load };
}

export default function App() {
  return (
    <BrowserRouter>
      <Toaster richColors position="top-right" />
      <Root />
    </BrowserRouter>
  );
}

function Root() {
  const { boot, setBoot, signedIn, reload } = useBoot();
  const location = useLocation();

  if (location.pathname === "/invite") return <InvitePage onSignedIn={signedIn} />;

  switch (boot.phase) {
    case "loading":
      return (
        <div className="p-8">
          <Loading />
        </div>
      );
    case "error":
      return (
        <div className="mx-auto max-w-xl p-8">
          <ErrorAlert error={boot.error} title="无法连接 Maestro 服务" />
          <Button className="mt-4" variant="outline" onClick={() => void reload()}>
            重试
          </Button>
        </div>
      );
    case "setup":
      return <SetupPage onSignedIn={signedIn} />;
    case "signed-out":
      return <LoginPage onSignedIn={signedIn} />;
    case "signed-in":
      return (
        <SignedIn
          me={boot.me}
          onMe={(me) => setBoot({ phase: "signed-in", me })}
          onSignedOut={() => setBoot({ phase: "signed-out" })}
        />
      );
  }
}

function SignedIn({
  me,
  onMe,
  onSignedOut,
}: {
  me: Me;
  onMe: (me: Me) => void;
  onSignedOut: () => void;
}) {
  // undefined while loading; null when unavailable (pages fall back to built-in limits).
  const [capabilities, setCapabilities] = useState<Capabilities | null | undefined>(undefined);

  useEffect(() => {
    api
      .get<Capabilities>("capabilities")
      .then((res) => setCapabilities(res.data))
      .catch(() => setCapabilities(null));
  }, []);

  const session = useMemo<SessionState>(
    () => ({
      me,
      capabilities: capabilities ?? null,
      signOut: async () => {
        try {
          await api.del("session");
        } catch (err) {
          if (!(err instanceof ApiError && err.status === 401)) {
            toast.error(`退出失败：${errorText(err)}`);
            return;
          }
        }
        setCsrfToken(null);
        onSignedOut();
      },
      refreshMe: async () => {
        const res = await api.get<Me>("me");
        onMe(res.data);
      },
    }),
    [me, capabilities, onMe, onSignedOut],
  );

  if (capabilities === undefined) {
    return (
      <div className="p-8">
        <Loading />
      </div>
    );
  }

  return (
    <SessionContext.Provider value={session}>
      <Shell>
        <Routes>
          <Route path="/" element={<Navigate to="/runs" replace />} />
          <Route path="/runs" element={<RunListPage />} />
          <Route path="/runs/new" element={<NewRunPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/datasets" element={<DatasetsPage />} />
          <Route path="/exports" element={<ExportsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route
            path="/admin"
            element={me.role === "admin" ? <AdminPage /> : <Navigate to="/runs" replace />}
          />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Shell>
    </SessionContext.Provider>
  );
}

function NotFound() {
  return <ErrorAlert error={new Error("页面不存在")} title="404" />;
}

function Shell({ children }: { children: React.ReactNode }) {
  const { me, signOut } = useSession();
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<unknown>();
  const pollHealth = useCallback(async () => {
    try {
      const res = await api.get<Health>("system-status");
      setHealth(res.data);
      setHealthError(undefined);
    } catch (err) {
      setHealthError(err);
    }
  }, []);
  useEffect(() => {
    void pollHealth();
  }, [pollHealth]);
  useInterval(() => void pollHealth(), 30000, true);
  const links = [
    { to: "/runs", label: "运行" },
    { to: "/datasets", label: "数据集" },
    { to: "/exports", label: "导出" },
    { to: "/settings", label: "个人设置" },
    ...(me.role === "admin" ? [{ to: "/admin", label: "管理" }] : []),
  ];
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b bg-sidebar text-sidebar-foreground">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2">
          <NavLink to="/runs" className="text-lg font-semibold tracking-wide text-sidebar-primary">
            Maestro
          </NavLink>
          <nav className="flex flex-wrap gap-1">
            {links.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-1.5 text-sm",
                    isActive ? "bg-sidebar-accent text-white" : "hover:bg-sidebar-accent/60",
                  )
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <SystemIndicator health={health} error={healthError} />
            <span title={me.id}>
              {me.display_name || me.username}
              <span className="ml-1 opacity-70">({me.role === "admin" ? "管理员" : "成员"})</span>
            </span>
            <Button
              size="sm"
              variant="ghost"
              className="text-sidebar-foreground hover:bg-sidebar-accent hover:text-white"
              onClick={() => void signOut()}
            >
              <LogOut />
              退出
            </Button>
          </div>
        </div>
      </header>
      <SystemNotice health={health} />
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}

function SystemIndicator({ health, error }: { health: Health | null; error: unknown }) {
  if (error) return <Pill tone="bad" title={errorText(error)}>状态未知</Pill>;
  if (!health) return null;
  if (health.status !== "ready") return <Pill tone="bad">维护中</Pill>;
  return health.accepting_runs ? (
    <Pill tone="good">可受理运行</Pill>
  ) : (
    <Pill tone="warn">暂不受理运行</Pill>
  );
}

function SystemNotice({ health }: { health: Health | null }) {
  if (!health || (health.accepting_runs && health.status === "ready")) return null;
  const detail = health.detail ?? {};
  const reasons: string[] = [];
  if (health.status !== "ready") reasons.push(`服务状态：${health.status}`);
  if (detail.master_key_available === false) reasons.push("主密钥不可用");
  if (!detail.executor) reasons.push("未配置执行器");
  if (detail.worker_running === false) reasons.push("执行进程未运行");
  const storage = detail.storage as { level?: string } | undefined;
  if (storage?.level && storage.level !== "ok") reasons.push("存储空间不足");
  return (
    <div className="border-b border-amber-300 bg-amber-50 text-amber-900">
      <div className="mx-auto flex max-w-7xl items-start gap-2 px-4 py-2 text-sm">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        <div>
          <b>当前无法受理新运行。</b> {reasons.join("；") || "原因未知"}。已有记录仍可查看。
          <details className="mt-1">
            <summary className="cursor-pointer text-xs">详情</summary>
            <pre className="text-xs">{JSON.stringify(detail, null, 2)}</pre>
          </details>
        </div>
      </div>
    </div>
  );
}

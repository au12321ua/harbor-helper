import { useEffect, useRef, useState } from "react";
import { api, post, type User } from "@/api";
import { Button } from "@/components/ui/button";
import { CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorNotice } from "@/components/shared";

type Version = Awaited<ReturnType<typeof loadVersion>>;
const loadVersion = () => api("/version");
const loadUpdates = () => api("/admin/updates");
type Updates = Awaited<ReturnType<typeof loadUpdates>>;
type Check = {
  check_id: string;
  target_sha: string;
  config_digest: string;
  relation: string;
  message?: string;
  metadata?: string;
};
const phases: Record<string, string> = {
  preparing: "准备与在线预探测",
  waiting: "等待实验自然结束",
  backup: "离线备份与恢复检查",
  adapting: "完整离线适配",
  migrating: "显式迁移",
  switching: "切换版本",
  verifying: "屏障内验证",
  restoring: "恢复原版本",
  commit_decided: "已决定放行",
  releasing: "正在恢复服务",
  succeeded: "升级成功",
  failed: "升级失败",
  cancelled: "已取消升级",
  needs_manual: "需要宿主管理员处理",
};
const relations: Record<string, string> = {
  current: "已是当前版本",
  update: "发现可更新版本",
  behind: "目标落后，拒绝降级",
  diverged: "历史分叉",
  unknown: "关系未知",
  check_failed: "检查失败",
};

function checked(value: unknown): Check | undefined {
  if (!value || typeof value !== "object") return;
  const row = value as Record<string, unknown>;
  if (
    ["check_id", "target_sha", "config_digest", "relation"].every(
      (k) => typeof row[k] === "string",
    )
  )
    return row as Check;
}

export function VersionFooter({ user }: { user: User }) {
  const [version, setVersion] = useState<Version>();
  const [open, setOpen] = useState(false);
  const [updates, setUpdates] = useState<Updates>();
  const [updatesStatus, setUpdatesStatus] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const [publicPhase, setPublicPhase] = useState<string>();
  const [error, setError] = useState<unknown>();
  const [pending, setPending] = useState<string>();
  const [sending, setSending] = useState(false);
  const [stale, setStale] = useState(false);
  const initialBuild = useRef<string | undefined>(
    document.querySelector<HTMLMetaElement>('meta[name="hh-build"]')?.content,
  );
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    loadVersion()
      .then((value) => {
        setVersion(value);
        if (initialBuild.current && initialBuild.current !== value.build)
          setStale(true);
        initialBuild.current ??= value.build;
      })
      .catch(setError);
  }, []);
  useEffect(() => {
    if (!open) return;
    dialog.current?.showModal();
    let live = true;
    let refreshing = false;
    const refresh = async () => {
      if (refreshing) return;
      refreshing = true;
      try {
        const value = await loadVersion();
        if (!live) return;
        setVersion(value);
        if (initialBuild.current && value.build !== initialBuild.current)
          setStale(true);
        if (user.role === "admin") {
          const status = await loadUpdates();
          if (!live) return;
          setUpdates(status);
          setUpdatesStatus("ready");
          setPublicPhase(undefined);
          setPending((previous) =>
            status.results.some((item) => item.request_id === previous)
              ? undefined
              : previous,
          );
        }
        setError(undefined);
      } catch (failure) {
        if (!live) return;
        setError(failure);
        setUpdatesStatus("error");
        // Public projection remains available while authenticated APIs are stopped.
        const value: { upgrading: boolean; phase: string | null } | undefined =
          await fetch("/api/v1/upgrade-phase", { cache: "no-store" })
            .then((response) => (response.ok ? response.json() : undefined))
            .catch(() => undefined);
        if (live)
          setPublicPhase(
            value?.upgrading ? (value.phase ?? undefined) : undefined,
          );
      } finally {
        refreshing = false;
      }
    };
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 2500);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [open, user.role]);
  const last = updates?.results[0];
  const check = checked(last?.result);
  const job = updates?.job;
  const phase =
    publicPhase ?? (typeof job?.phase === "string" ? job.phase : undefined);
  const active = phase && !["succeeded", "failed", "cancelled"].includes(phase);
  async function send(
    action: "check" | "upgrade" | "cancel" | "cancel-all",
    payload: Record<string, string> = {},
  ) {
    setSending(true);
    try {
      const response = await post("/admin/updates", {
        action,
        request_id: crypto.randomUUID(),
        payload,
      });
      setPending(response.request_id);
      setError(undefined);
    } catch (failure) {
      setError(failure);
    } finally {
      setSending(false);
    }
  }
  function close() {
    dialog.current?.close();
    setOpen(false);
  }
  return (
    <>
      <Button
        variant="link"
        onClick={() => {
          setUpdates(undefined);
          setUpdatesStatus("loading");
          setPublicPhase(undefined);
          setError(undefined);
          setOpen(true);
        }}
        aria-label="查看运行版本与更新"
      >
        Harbor Helper {version?.version || "版本信息"}
        {version?.release ? ` · ${version.release.slice(0, 8)}` : ""}
      </Button>
      {open ? (
        <dialog
          ref={dialog}
          onClose={() => setOpen(false)}
          onCancel={(event) => {
            event.preventDefault();
            close();
          }}
          aria-labelledby="version-title"
          className="fixed inset-0 m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-xl overflow-auto rounded-lg border bg-card p-0 text-card-foreground shadow-lg backdrop:bg-black/50"
        >
          <CardHeader>
            <CardTitle id="version-title">运行版本与更新</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {version ? (
              <dl className="grid grid-cols-[auto_1fr] gap-2 break-all">
                <dt>包版本</dt>
                <dd>{version.version}</dd>
                <dt>运行提交</dt>
                <dd>{version.release || "未记录"}</dd>
                <dt>构建摘要</dt>
                <dd>{version.build}</dd>
                <dt>当前安装来源</dt>
                <dd>
                  {version.source
                    ? `${version.source.repository} · ${version.source.branch}`
                    : "来源未记录"}
                </dd>
              </dl>
            ) : null}
            {stale ? (
              <div role="status">
                页面构建已过期。
                <Button onClick={() => window.location.reload()}>
                  刷新页面
                </Button>
              </div>
            ) : null}
            {user.role === "admin" ? (
              <>
                {updatesStatus === "loading" ? (
                  <p role="status">正在加载更新配置与启用状态…</p>
                ) : updatesStatus === "error" ? (
                  <p role="alert">更新状态读取失败，将自动重试。</p>
                ) : null}
                {updatesStatus === "ready" && updates ? (
                  <>
                    <p>
                      下一次更新源：
                      {updates?.source
                        ? `${updates.source.repository} · ${updates.source.branch === "dev" ? "测试" : "稳定"}`
                        : "未配置"}
                    </p>
                    {!updates?.enabled ? (
                      <p>本安装尚未启用网页更新，请由部署者完成一次性接入。</p>
                    ) : (
                      <>
                        <p>
                          默认关闭新受理并等待实验自然结束，不自动取消任务。
                        </p>
                        <Button
                          disabled={sending || !!pending || !!active}
                          onClick={() => void send("check")}
                        >
                          检查更新
                        </Button>
                        {pending ? (
                          <p role="status">
                            请求已持久提交，等待执行器处理；关闭页面不影响执行。
                          </p>
                        ) : null}
                        {check ? (
                          <div>
                            <p>
                              {relations[check.relation] || "检查失败"} ·{" "}
                              {check.target_sha.slice(0, 12)}
                            </p>
                            <p>{check.message}</p>
                            {check.metadata === "passed" ? (
                              <p>
                                元数据检查通过；完整适配将在离线备份后执行。
                              </p>
                            ) : null}
                            {check.relation === "update" ? (
                              <Button
                                disabled={sending || !!pending || !!active}
                                onClick={() =>
                                  void send("upgrade", {
                                    check_id: check.check_id,
                                    target_sha: check.target_sha,
                                    config_digest: check.config_digest,
                                  })
                                }
                              >
                                更新到此固定提交
                              </Button>
                            ) : null}
                          </div>
                        ) : null}
                        {updates.results[0]?.error ? (
                          <p role="alert">
                            检查或请求失败，请检查宿主更新配置；当前版本状态未知。
                          </p>
                        ) : null}
                        {phase === "waiting" && typeof job?.id === "string" ? (
                          <div className="flex flex-wrap gap-2">
                            <Button
                              variant="outline"
                              disabled={sending}
                              onClick={() =>
                                void send("cancel", { job: job.id as string })
                              }
                            >
                              取消升级，保留实验
                            </Button>
                            <Button
                              variant="destructive"
                              disabled={sending}
                              onClick={() => {
                                if (
                                  window.confirm(
                                    "取消所有未完成任务不可撤销，之后继续升级。确认？",
                                  )
                                )
                                  void send("cancel-all", {
                                    job: job.id as string,
                                  });
                              }}
                            >
                              改为取消全部任务
                            </Button>
                          </div>
                        ) : null}
                      </>
                    )}
                  </>
                ) : null}
                {phase ? (
                  <p role="status">
                    {phases[phase] || phase}。刷新页面可继续查看。
                  </p>
                ) : null}
              </>
            ) : null}
            {error ? <ErrorNotice error={error} /> : null}
            <Button variant="outline" onClick={close}>
              关闭
            </Button>
          </CardContent>
        </dialog>
      ) : null}
    </>
  );
}

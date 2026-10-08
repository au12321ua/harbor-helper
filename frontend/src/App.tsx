import { useCallback, useEffect, useState, useRef } from "react";
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";
import {
  ArrowUpRight,
  FlaskConical,
  LayoutList,
  Plus,
  GitCompareArrows,
  Settings2,
  LogOut,
  RefreshCw,
  ArrowLeft,
  Download,
  Trash2,
  LoaderCircle,
} from "lucide-react";
import {
  api,
  post,
  date,
  labels,
  terminal,
  type Item,
  ApiError,
  newIdempotencyKey,
} from "./api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import {
  Table,
  TableHeader,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Field,
  FieldLabel,
  FieldDescription,
  FieldGroup,
} from "@/components/ui/field";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { toast, Toaster } from "sonner";
import "./App.css";

function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <Alert variant="destructive">
      <AlertTitle>操作未完成</AlertTitle>
      <AlertDescription>
        {error instanceof Error ? error.message : String(error)}
        {error instanceof ApiError && error.requestId ? (
          <small>请求编号：{error.requestId}</small>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
function Status({ value }: { value: string }) {
  return (
    <Badge
      className="whitespace-nowrap"
      variant={
        value === "failed" ||
        value === "cleanup_blocked" ||
        value === "incomplete"
          ? "destructive"
          : value === "succeeded" || value === "clean"
            ? "default"
            : "secondary"
      }
    >
      {labels[value] || value || "—"}
    </Badge>
  );
}
function Title({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
function SelectField({
  label,
  name,
  value,
  onChange,
  children,
  description,
  required = true,
}: {
  label: string;
  name: string;
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
  description?: string;
  required?: boolean;
}) {
  return (
    <Field>
      <FieldLabel htmlFor={name}>{label}</FieldLabel>
      <select
        id={name}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
      >
        {children}
      </select>
      {description ? <FieldDescription>{description}</FieldDescription> : null}
    </Field>
  );
}
function EmptyState({
  title = "暂无实验",
  description = "提交第一个实验后，它会出现在团队共享列表中。",
}: {
  title?: string;
  description?: string;
}) {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}
function Loading() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-12 w-64" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}
function useLoad<T>(loader: () => Promise<T>, dependency = "", poll = 0) {
  const loaderRef = useRef(loader);
  const [data, setData] = useState<T>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    loaderRef.current = loader;
  }, [loader]);
  const reload = useCallback(async () => {
    try {
      setData(await loaderRef.current());
      setError(undefined);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload();
    if (poll) {
      const id = setInterval(() => {
        if (document.visibilityState === "visible") void reload();
      }, poll);
      return () => clearInterval(id);
    }
  }, [reload, dependency, poll]);
  return { data, error, loading, reload };
}

function Login({ onLogin }: { onLogin: (user: Item) => void }) {
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  return (
    <div className="login-page">
      <div className="login-brand">
        <FlaskConical />
        <span>Harbor Helper</span>
      </div>
      <Card className="login-card">
        <CardHeader>
          <CardTitle>
            <h1>登录团队实验室</h1>
          </CardTitle>
          <CardDescription>使用管理员为你创建的受邀账户。</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError(undefined);
              const f = new FormData(e.currentTarget);
              try {
                const value = await post("/auth/login", {
                  username: f.get("username"),
                  password: f.get("password"),
                });
                onLogin(value.user || value);
              } catch (err) {
                setError(err);
              } finally {
                setBusy(false);
              }
            }}
          >
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="username">账户</FieldLabel>
                <Input
                  id="username"
                  name="username"
                  autoComplete="username"
                  required
                  autoFocus
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="password">密码</FieldLabel>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                />
              </Field>
              <ErrorNotice error={error} />
              <Button disabled={busy} type="submit">
                {busy ? (
                  <LoaderCircle
                    data-icon="inline-start"
                    className="animate-spin"
                  />
                ) : null}
                登录
              </Button>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
      <p className="login-footer">团队共享实验 · 无开放注册</p>
    </div>
  );
}
function ExperimentList() {
  const { data, error, loading, reload } = useLoad(
    () => Promise.all([api("/runs"), api("/usage")]),
    "",
    4000,
  );
  const [filter, setFilter] = useState("");
  if (loading) return <Loading />;
  const runs: Item[] = data?.[0].runs || [],
    submissions: Item[] = data?.[0].submissions || [],
    usage = data?.[1] || {};
  const shown = runs.filter((r) =>
    JSON.stringify([r.id, r.submitter, r.dataset, r.status])
      .toLowerCase()
      .includes(filter.toLowerCase()),
  );
  return (
    <>
      <Title
        title="共享实验"
        description="团队的每一次尝试，都在这里留下记录。"
        action={
          <Button asChild>
            <Link to="/new">
              <Plus data-icon="inline-start" />
              新建实验
            </Link>
          </Button>
        }
      />
      <ErrorNotice error={error} />
      <div className="usage-strip">
        <div>
          <span>累计实验</span>
          <strong>{usage.total_runs ?? runs.length}</strong>
        </div>
        <div>
          <span>运行中</span>
          <strong>
            {usage.active_jobs ?? "—"}
            <small> 个任务</small>
          </strong>
        </div>
        <div>
          <span>排队中</span>
          <strong>{usage.queued_jobs ?? "—"}</strong>
        </div>
        <div>
          <span>累计提交</span>
          <strong>{usage.total_submissions ?? submissions.length}</strong>
        </div>
      </div>
      <div className="section-bar">
        <h2>
          实验记录 <span>{runs.length}</span>
        </h2>
        <div className="flex gap-2">
          <Input
            aria-label="搜索实验"
            placeholder="搜索编号、成员、数据集…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <Button
            variant="outline"
            size="icon"
            aria-label="刷新实验"
            onClick={() => void reload()}
          >
            <RefreshCw />
          </Button>
        </div>
      </div>
      <div className="table-shell">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>实验 / 数据集</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>提交者</TableHead>
              <TableHead>创建时间</TableHead>
              <TableHead>审计</TableHead>
              <TableHead className="text-right">详情</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((r) => (
              <TableRow key={r.id}>
                <TableCell>
                  <Link className="run-link" to={`/runs/${r.id}`}>
                    {r.id}
                  </Link>
                  <div className="cell-secondary">
                    {typeof r.dataset === "string"
                      ? r.dataset
                      : r.dataset?.ref || r.dataset?.name || "—"}
                  </div>
                </TableCell>
                <TableCell>
                  <Status value={r.status} />
                </TableCell>
                <TableCell>{r.submitter || "—"}</TableCell>
                <TableCell className="whitespace-nowrap">
                  {date(r.created)}
                </TableCell>
                <TableCell>
                  <Status value={r.audit_status} />
                </TableCell>
                <TableCell className="text-right">
                  <Button variant="ghost" size="icon" asChild>
                    <Link aria-label={`查看 ${r.id}`} to={`/runs/${r.id}`}>
                      <ArrowUpRight />
                    </Link>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {!shown.length ? (
          <EmptyState
            title={filter ? "没有匹配的实验" : undefined}
            description={filter ? "试试其他编号、成员或数据集。" : undefined}
          />
        ) : null}
      </div>
      {submissions.filter((s) => !s.run_id).length ? (
        <section className="flex flex-col gap-4">
          <h2>准备中的提交</h2>
          {submissions
            .filter((s) => !s.run_id)
            .map((s) => (
              <Card key={s.id}>
                <CardContent className="submission-row">
                  <Link to={`/submissions/${s.id}`}>{s.id}</Link>
                  <Status value={s.status} />
                  <span>{s.submitter}</span>
                  <span className="text-muted-foreground">
                    {s.error || "等待数据源解析与入队"}
                  </span>
                </CardContent>
              </Card>
            ))}
        </section>
      ) : null}
      <p className="quiet-note">
        运行时长和并发限制控制资源使用，不代表准确的费用预算。
      </p>
    </>
  );
}

function NewExperiment() {
  const submitKey = useRef(newIdempotencyKey());
  const { data, error, loading } = useLoad(() => api("/catalog"));
  const navigate = useNavigate();
  const [dataset, setDataset] = useState(""),
    [agent, setAgent] = useState("opencode"),
    [profile, setProfile] = useState(""),
    [bundle, setBundle] = useState(""),
    [busy, setBusy] = useState(false),
    [failure, setFailure] = useState<unknown>(),
    [uploadBusy, setUploadBusy] = useState(false);
  const selectedDataset =
    dataset ||
    (typeof data?.default_dataset === "string"
      ? data.default_dataset
      : data?.default_dataset?.ref || "");
  if (loading) return <Loading />;
  const profiles: Item[] = (data?.model_profiles || []).filter(
    (p: Item) => p.enabled !== false,
  );
  const limits = data?.limits || {};
  return (
    <>
      <Title
        title="新建实验"
        description="选择数据集与模型方案；提交后固定本次实验的配置。"
      />
      <ErrorNotice error={error || failure} />
      <form
        className="form-layout"
        onChange={() => {
          submitKey.current = newIdempotencyKey();
        }}
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setFailure(undefined);
          const f = new FormData(e.currentTarget);
          try {
            const s = await post(
              "/submissions",
              {
                dataset: selectedDataset,
                agent,
                model_profile: agent === "oracle" ? null : profile,
                bundle_id: bundle || null,
                task: f.get("task") || null,
                attempts: Number(f.get("attempts")),
                concurrency: Number(f.get("concurrency")),
                wall_seconds: Number(f.get("wall_seconds")),
              },
              submitKey.current,
            );
            navigate(`/submissions/${s.submission_id || s.id}`);
          } catch (err) {
            setFailure(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>实验输入</CardTitle>
              <CardDescription>
                数据集使用 Hub 引用与版本；服务会记录解析后的固定来源。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="dataset">数据集</FieldLabel>
                  <Input
                    id="dataset"
                    value={selectedDataset}
                    onChange={(e) => setDataset(e.target.value)}
                    placeholder="owner/dataset@version"
                    required
                  />
                  <FieldDescription>
                    可以切换为团队可访问的其他数据集。
                  </FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="task">任务筛选（可选）</FieldLabel>
                  <Input
                    id="task"
                    name="task"
                    placeholder="任务名；留空运行整个数据集"
                  />
                </Field>
                <SelectField
                  label="执行方案"
                  name="agent"
                  value={agent}
                  onChange={setAgent}
                >
                  <option value="opencode">模型 · OpenCode</option>
                  <option value="oracle">Oracle · 数据集参考解</option>
                </SelectField>
                {agent === "opencode" ? (
                  <SelectField
                    label="模型方案"
                    name="profile"
                    value={profile}
                    onChange={setProfile}
                    description="使用管理员配置的团队凭据，密钥不会展示给成员。"
                  >
                    <option value="">选择模型方案</option>
                    {profiles.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · {p.model}
                      </option>
                    ))}
                  </SelectField>
                ) : (
                  <Alert>
                    <AlertTitle>Oracle 模式</AlertTitle>
                    <AlertDescription>
                      运行数据集自带的参考解，不发起模型请求。
                    </AlertDescription>
                  </Alert>
                )}
                <Field>
                  <FieldLabel htmlFor="bundle">实验包（可选 ZIP）</FieldLabel>
                  <Input
                    id="bundle"
                    type="file"
                    accept=".zip,application/zip"
                    disabled={uploadBusy}
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      setUploadBusy(true);
                      setBundle("");
                      setFailure(undefined);
                      try {
                        const body = new FormData();
                        body.set("file", file);
                        const value = await api("/bundles", {
                          method: "POST",
                          body,
                        });
                        setBundle(value.bundle_id || value.id);
                        toast.success("实验包已上传");
                      } catch (err) {
                        setFailure(err);
                      } finally {
                        setUploadBusy(false);
                      }
                    }}
                  />
                  <FieldDescription>
                    {bundle
                      ? `已绑定实验包：${bundle}`
                      : "服务校验包大小、路径和文件安全，不接受密钥文件。"}
                  </FieldDescription>
                </Field>
              </FieldGroup>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>运行限制</CardTitle>
              <CardDescription>
                所有成员的实验共用同一队列与容量。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <FieldGroup className="numeric-fields">
                <Field>
                  <FieldLabel htmlFor="attempts">每任务尝试次数</FieldLabel>
                  <Input
                    id="attempts"
                    name="attempts"
                    type="number"
                    min="1"
                    max={limits.max_attempts || 3}
                    defaultValue="1"
                    required
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="concurrency">实验并发数</FieldLabel>
                  <Input
                    id="concurrency"
                    name="concurrency"
                    type="number"
                    min="1"
                    max={limits.max_trials || 2}
                    defaultValue="1"
                    required
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="wall_seconds">最长运行秒数</FieldLabel>
                  <Input
                    id="wall_seconds"
                    name="wall_seconds"
                    type="number"
                    min="1"
                    max={limits.max_wall_seconds || 1800}
                    defaultValue={Math.min(
                      600,
                      limits.max_wall_seconds || 1800,
                    )}
                    required
                  />
                </Field>
              </FieldGroup>
            </CardContent>
          </Card>
        </div>
        <aside className="form-aside">
          <h2>提交前确认</h2>
          <p>全部团队成员都可以查看实验、日志、报告和产物。</p>
          <Separator />
          <p>提交者记为当前账户。重跑时创建新的实验记录，不覆盖历史结果。</p>
          <p>提供商、模型与参数在提交后固定；执行前会再次检查凭据是否可用。</p>
          <Button
            type="submit"
            disabled={busy || uploadBusy || (agent === "opencode" && !profile)}
          >
            {busy ? (
              <LoaderCircle data-icon="inline-start" className="animate-spin" />
            ) : (
              <Plus data-icon="inline-start" />
            )}
            提交实验
          </Button>
        </aside>
      </form>
    </>
  );
}
function Submission({ user }: { user: Item }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useLoad(
    () => api(`/submissions/${id}`),
    id || "",
    2000,
  );
  useEffect(() => {
    if (data?.run_id) navigate(`/runs/${data.run_id}`, { replace: true });
  }, [data?.run_id, navigate]);
  if (loading) return <Loading />;
  return (
    <>
      <Title title="实验准备" description={`提交 ${id}`} />
      <ErrorNotice error={error} />
      <Card>
        <CardHeader>
          <CardTitle>
            <Status value={data?.status} />
          </CardTitle>
          <CardDescription>
            数据源解析与准备完成后，自动进入统一队列。
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <p>提交者：{data?.submitter || "—"}</p>
          {data?.error ? (
            <Alert variant="destructive">
              <AlertDescription>
                {typeof data.error === "string"
                  ? data.error
                  : JSON.stringify(data.error)}
              </AlertDescription>
            </Alert>
          ) : null}
          {data &&
          !terminal(data.status) &&
          (user.role === "admin" || data.submitter === user.username) ? (
            <Button
              variant="outline"
              onClick={async () => {
                try {
                  await post(`/submissions/${id}/cancel`);
                  await reload();
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
            >
              取消提交
            </Button>
          ) : null}
          <Button variant="ghost" asChild>
            <Link to="/">返回实验列表</Link>
          </Button>
        </CardContent>
      </Card>
    </>
  );
}
function RunDetail({ user }: { user: Item }) {
  const { id } = useParams();
  return <RunDetailContent key={id} user={user} />;
}
function Rewards({ report }: { report: Item }) {
  return (
    <>
      <div className="report-summary">
        <div>
          <span>有效尝试</span>
          <strong>
            {report.valid_attempts ?? "—"} / {report.expected_attempts ?? "—"}
          </strong>
        </div>
        <div>
          <span>缺失尝试</span>
          <strong>{report.missing_attempts ?? "—"}</strong>
        </div>
        <div>
          <span>报告状态</span>
          <strong>{report.complete ? "完整" : "不完整"}</strong>
        </div>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>任务</TableHead>
            <TableHead>有效尝试</TableHead>
            <TableHead>评分</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(report.tasks || []).map((t: Item, i: number) => (
            <TableRow key={t.task || i}>
              <TableCell>{t.task}</TableCell>
              <TableCell>
                {t.valid_attempts} / {t.expected_attempts}
              </TableCell>
              <TableCell>
                {t.mean_rewards == null ? (
                  <span className="text-muted-foreground">缺失评分</span>
                ) : (
                  Object.entries(t.mean_rewards).map(([name, value]) => (
                    <div key={name}>
                      {name}: <strong>{String(value)}</strong>
                    </div>
                  ))
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {!report.complete ? (
        <p className="quiet-note">
          报告尚不完整。缺失评分不等于零分；执行失败由任务状态单独表示。
        </p>
      ) : null}
    </>
  );
}
function RunDetailContent({ user }: { user: Item }) {
  const rerunKey = useRef(newIdempotencyKey());
  const { id } = useParams();
  const { data, error, loading, reload } = useLoad(
    () => api(`/runs/${id}`),
    id || "",
    3000,
  );
  const [tab, setTab] = useState("overview"),
    [logs, setLogs] = useState<string>(),
    [logError, setLogError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  useEffect(() => {
    if (tab === "logs") {
      let active = true;
      api(`/runs/${id}/logs`)
        .then((v) => {
          if (active) {
            setLogs(v.text);
            setLogError(undefined);
          }
        })
        .catch((e) => {
          if (active) setLogError(e);
        });
      return () => {
        active = false;
      };
    }
  }, [tab, id, data?.row?.status]);
  if (loading) return <Loading />;
  const row = data?.row || {},
    manifest = data?.manifest || {};
  const canCancel =
    !terminal(row.status) &&
    (user.role === "admin" || row.submitter === user.username);
  return (
    <>
      <Button variant="ghost" className="back-link" asChild>
        <Link to="/">
          <ArrowLeft data-icon="inline-start" />
          全部实验
        </Link>
      </Button>
      <Title
        title={id || "实验详情"}
        description={`由 ${row.submitter || "—"} 提交于 ${date(row.created)}`}
        action={
          <div className="flex gap-2">
            {canCancel ? (
              <Button
                variant="outline"
                disabled={busy}
                onClick={async () => {
                  if (!window.confirm("确认取消此实验？已启动资源会完成清理。"))
                    return;
                  setBusy(true);
                  try {
                    await post(`/runs/${id}/cancel`);
                    await reload();
                  } catch (e) {
                    toast.error((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                取消实验
              </Button>
            ) : null}
            <Button
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const s = await post(
                    `/runs/${id}/rerun`,
                    {},
                    rerunKey.current,
                  );
                  navigate(`/submissions/${s.submission_id || s.id}`);
                } catch (e) {
                  toast.error((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <RefreshCw data-icon="inline-start" />
              重跑实验
            </Button>
          </div>
        }
      />
      <ErrorNotice error={error} />
      <div className="detail-status">
        <Status value={row.status} />
        <Status value={row.audit_status} />
        {row.parent ? (
          <Link to={`/runs/${row.parent}`}>来源实验 {row.parent}</Link>
        ) : null}
      </div>
      {row.audit_status === "incomplete" ? (
        <Alert variant="destructive">
          <AlertTitle>日志安全审计异常</AlertTitle>
          <AlertDescription>
            相关日志和产物暂不可展示。资源清理确认后会正常释放容量；安全摘要仍可查看。
          </AlertDescription>
        </Alert>
      ) : null}
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="overview">配置与状态</TabsTrigger>
          <TabsTrigger value="report">评分报告</TabsTrigger>
          <TabsTrigger value="logs">运行日志</TabsTrigger>
          <TabsTrigger value="artifacts">实验产物</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <Card>
            <CardHeader>
              <CardTitle>本次实验快照</CardTitle>
              <CardDescription>
                这些记录属于当前实验，后续配置变更不会改写历史输入。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="detail-grid">
                {Object.entries({
                  数据集:
                    row.dataset || manifest.source?.dataset || manifest.source,
                  模型方案: row.model_profile || manifest.model_profile,
                  开始时间: date(row.started),
                  完成时间: date(row.finished),
                  执行并发: row.concurrency,
                  状态原因: row.reason || "—",
                }).map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>
                      {v == null
                        ? "—"
                        : typeof v === "object"
                          ? JSON.stringify(v)
                          : String(v)}
                    </dd>
                  </div>
                ))}
              </dl>
              <details className="raw-details">
                <summary>查看非敏感配置快照</summary>
                <pre>{JSON.stringify(manifest, null, 2)}</pre>
              </details>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="report">
          {data?.report ? (
            <Card>
              <CardHeader>
                <CardTitle>评分报告</CardTitle>
                <CardDescription>
                  保留合法零分，单独记录缺失和无效尝试。
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Rewards report={data.report} />
              </CardContent>
            </Card>
          ) : (
            <EmptyState
              title="报告暂不可用"
              description={
                row.audit_status === "incomplete"
                  ? "审计异常限制了报告展示。"
                  : "等待任务运行、资源收尾与报告发布。"
              }
            />
          )}
        </TabsContent>
        <TabsContent value="logs">
          <Button
            variant="outline"
            size="sm"
            className="mb-4"
            onClick={async () => {
              try {
                const value = await api(`/runs/${id}/logs`);
                setLogs(value.text);
                setLogError(undefined);
              } catch (e) {
                setLogError(e);
              }
            }}
          >
            <RefreshCw data-icon="inline-start" />
            刷新日志
          </Button>
          <ErrorNotice error={logError} />
          {logs !== undefined ? (
            <pre className="log-view">{logs || "暂无日志内容"}</pre>
          ) : !logError ? (
            <Loading />
          ) : null}
        </TabsContent>
        <TabsContent value="artifacts">
          <div className="table-shell">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>产物名称</TableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data?.artifacts || []).map((a: Item) => (
                  <TableRow key={a.id}>
                    <TableCell>
                      {a.name}
                      {a.deleted ? (
                        <Badge variant="secondary">已删除</Badge>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={
                            a.deleted || row.audit_status === "incomplete"
                          }
                          onClick={() => {
                            window.location.href = `/api/v1/runs/${id}/artifacts/${encodeURIComponent(a.id)}`;
                          }}
                        >
                          <Download data-icon="inline-start" />
                          下载
                        </Button>
                        {user.role === "admin" &&
                        terminal(row.status) &&
                        !a.deleted ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={async () => {
                              if (
                                !window.confirm(
                                  `删除产物 ${a.name}？此操作不可撤销。`,
                                )
                              )
                                return;
                              try {
                                await api(
                                  `/runs/${id}/artifacts/${encodeURIComponent(a.id)}`,
                                  { method: "DELETE" },
                                );
                                await reload();
                                toast.success("产物已删除");
                              } catch (e) {
                                toast.error((e as Error).message);
                              }
                            }}
                          >
                            <Trash2 data-icon="inline-start" />
                            删除
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {!data?.artifacts?.length ? (
              <EmptyState
                title="暂无可展示产物"
                description="产物在运行与安全审计完成后展示。"
              />
            ) : null}
          </div>
        </TabsContent>
      </Tabs>
    </>
  );
}
function ComparisonResult({ value }: { value: Item }) {
  return (
    <div className="flex flex-col gap-5">
      {value.reasons?.length ? (
        <Alert>
          <AlertTitle>可比性检查</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {value.reasons.map((reason: string) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}
      {value.comparable && value.mean_task_delta != null ? (
        <div className="report-summary">
          {Object.entries(value.mean_task_delta).map(([metric, delta]) => (
            <div key={metric}>
              <span>{metric} · 平均任务变化 (B − A)</span>
              <strong>{String(delta)}</strong>
            </div>
          ))}
        </div>
      ) : null}
      {value.tasks?.length && value.comparable ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>任务</TableHead>
              <TableHead>指标</TableHead>
              <TableHead>实验 A</TableHead>
              <TableHead>实验 B</TableHead>
              <TableHead>B − A</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {value.tasks.flatMap((task: Item) =>
              Object.keys(task.delta || {}).map((metric) => (
                <TableRow key={task.task + metric}>
                  <TableCell>{task.task}</TableCell>
                  <TableCell>{metric}</TableCell>
                  <TableCell>{String(task.left[metric])}</TableCell>
                  <TableCell>{String(task.right[metric])}</TableCell>
                  <TableCell>{String(task.delta[metric])}</TableCell>
                </TableRow>
              )),
            )}
          </TableBody>
        </Table>
      ) : null}
      <details className="raw-details">
        <summary>完整对比记录</summary>
        <pre>{JSON.stringify(value, null, 2)}</pre>
      </details>
    </div>
  );
}
function Compare() {
  const { data, error, loading } = useLoad(() => api("/runs"));
  const [left, setLeft] = useState(""),
    [right, setRight] = useState(""),
    [result, setResult] = useState<Item>(),
    [failure, setFailure] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  if (loading) return <Loading />;
  return (
    <>
      <Title
        title="实验对比"
        description="仅在数据源、评分与运行条件可比时展示聚合结果。"
      />
      <ErrorNotice error={error || failure} />
      <Card>
        <CardHeader>
          <CardTitle>选择两次实验</CardTitle>
          <CardDescription>
            跨数据集或配置不一致会明确说明，避免误导性对比。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setResult(undefined);
              setFailure(undefined);
              try {
                setResult(await post("/compare", { left, right }));
              } catch (err) {
                setFailure(err);
              } finally {
                setBusy(false);
              }
            }}
          >
            <FieldGroup className="comparison-form">
              <SelectField
                label="实验 A"
                name="left"
                value={left}
                onChange={setLeft}
              >
                <option value="">选择实验</option>
                {(data?.runs || []).map((r: Item) => (
                  <option key={r.id} value={r.id}>
                    {r.id} · {r.submitter} · {labels[r.status] || r.status}
                  </option>
                ))}
              </SelectField>
              <SelectField
                label="实验 B"
                name="right"
                value={right}
                onChange={setRight}
              >
                <option value="">选择实验</option>
                {(data?.runs || []).map((r: Item) => (
                  <option key={r.id} value={r.id}>
                    {r.id} · {r.submitter} · {labels[r.status] || r.status}
                  </option>
                ))}
              </SelectField>
              <Button disabled={busy || !left || !right || left === right}>
                开始对比
              </Button>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
      {result ? (
        <Card>
          <CardHeader>
            <CardTitle>
              {result.comparable === false ? "实验不可比" : "对比结果"}
            </CardTitle>
            <CardDescription>
              {result.comparable === false
                ? "未生成聚合评分；请检查下面的差异原因。"
                : "结果遵循服务端评分与可比性判断。"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ComparisonResult value={result} />
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}
const limitLabels: Record<string, string> = {
  max_jobs: "全局任务并发",
  max_trials: "全局 Trial 并发",
  max_queue: "最大队列长度",
  max_wall_seconds: "最长运行秒数",
  max_attempts: "每任务最大尝试数",
  max_cpus_per_trial: "每 Trial CPU 上限",
  max_memory_mb_per_trial: "每 Trial 内存 MB",
  max_upload_bytes: "最大上传字节数",
  log_retention_days: "日志保留天数",
  artifact_retention_days: "产物保留天数",
};
function rowsOf(value: Item | Item[] | undefined, key: string): Item[] {
  return Array.isArray(value) ? value : value?.[key] || [];
}
function AdminForm({
  title,
  description,
  fields,
  onSave,
}: {
  title: string;
  description: string;
  fields: {
    name: string;
    label: string;
    type?: string;
    options?: { value: string; label: string }[];
    defaultValue?: string;
    required?: boolean;
  }[];
  onSave: (value: Item) => Promise<unknown>;
}) {
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const form = e.currentTarget;
            setBusy(true);
            setError(undefined);
            const value = Object.fromEntries(new FormData(form));
            try {
              await onSave(value);
              form.reset();
              toast.success("配置已保存");
            } catch (err) {
              setError(err);
            } finally {
              const secrets = form.querySelectorAll<HTMLInputElement>(
                'input[type="password"]',
              );
              secrets.forEach((input) => {
                input.value = "";
              });
              setBusy(false);
            }
          }}
        >
          <FieldGroup>
            {fields.map((f) => (
              <Field key={f.name}>
                <FieldLabel htmlFor={`${title}-${f.name}`}>
                  {f.label}
                </FieldLabel>
                {f.options ? (
                  <select
                    id={`${title}-${f.name}`}
                    name={f.name}
                    required={f.required !== false}
                    defaultValue={f.defaultValue || ""}
                  >
                    {!f.defaultValue ? <option value="">请选择</option> : null}
                    {f.options.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                ) : f.type === "textarea" ? (
                  <Textarea
                    id={`${title}-${f.name}`}
                    name={f.name}
                    required={f.required !== false}
                    defaultValue={f.defaultValue}
                  />
                ) : (
                  <Input
                    id={`${title}-${f.name}`}
                    name={f.name}
                    type={f.type || "text"}
                    required={f.required !== false}
                    defaultValue={f.defaultValue}
                    autoComplete={
                      f.type === "password" ? "new-password" : "off"
                    }
                  />
                )}
              </Field>
            ))}
            <ErrorNotice error={error} />
            <Button disabled={busy} type="submit">
              {busy ? (
                <LoaderCircle
                  data-icon="inline-start"
                  className="animate-spin"
                />
              ) : null}
              保存
            </Button>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  );
}
function Admin() {
  const { data, error, loading, reload } = useLoad(
    () => Promise.all([api("/admin/users"), api("/catalog")]),
    "",
  );
  const [rotation, setRotation] = useState("");
  const [tab, setTab] = useState("users");
  if (loading) return <Loading />;
  const users = rowsOf(data?.[0], "users"),
    catalog = data?.[1] || {},
    providers: Item[] = catalog.providers || [],
    credentials: Item[] = catalog.credentials || [],
    profiles: Item[] = catalog.model_profiles || [];
  async function save(path: string, value: Item) {
    await post(path, value);
    await reload();
  }
  async function mutate(path: string, method = "POST", body: Item = {}) {
    try {
      await api(path, { method, body: JSON.stringify(body) });
      await reload();
      toast.success("已更新");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <>
      <Title
        title="团队管理"
        description="管理受邀账户、团队模型方案与共享容量。"
      />
      <ErrorNotice error={error} />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="admin-tabs">
          <TabsTrigger value="users">受邀账户</TabsTrigger>
          <TabsTrigger value="providers">提供商</TabsTrigger>
          <TabsTrigger value="credentials">凭据</TabsTrigger>
          <TabsTrigger value="profiles">模型方案</TabsTrigger>
          <TabsTrigger value="limits">容量与保留</TabsTrigger>
        </TabsList>
        <TabsContent value="users">
          <div className="admin-layout">
            <div className="table-shell">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>账户</TableHead>
                    <TableHead>角色</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((u) => (
                    <TableRow key={u.id}>
                      <TableCell>{u.username}</TableCell>
                      <TableCell>
                        {u.role === "admin" ? "管理员" : "成员"}
                      </TableCell>
                      <TableCell>
                        {u.enabled === false ? "停用" : "启用"}
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            void mutate(`/admin/users/${u.id}`, "PATCH", {
                              enabled: u.enabled === false,
                            })
                          }
                        >
                          {u.enabled === false ? "启用" : "停用"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <AdminForm
              title="创建受邀账户"
              description="不提供公开注册。成员共享查看权限，管理员负责全局管理。"
              fields={[
                { name: "username", label: "用户名" },
                { name: "password", label: "初始密码", type: "password" },
                {
                  name: "role",
                  label: "角色",
                  defaultValue: "member",
                  options: [
                    { value: "member", label: "成员" },
                    { value: "admin", label: "管理员" },
                  ],
                },
              ]}
              onSave={(value) => save("/admin/users", value)}
            />
          </div>
        </TabsContent>
        <TabsContent value="providers">
          <div className="admin-layout">
            <div className="table-shell">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>提供商</TableHead>
                    <TableHead>端点</TableHead>
                    <TableHead>状态</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {providers.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell>
                        {p.name}
                        <div className="cell-secondary">{p.id}</div>
                      </TableCell>
                      <TableCell className="break-all">{p.endpoint}</TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            void save("/admin/providers", {
                              ...p,
                              enabled: p.enabled === false,
                            }).catch((e) => toast.error(e.message))
                          }
                        >
                          {p.enabled === false ? "启用" : "停用"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {!providers.length ? (
                <EmptyState
                  title="尚未配置提供商"
                  description="新增兼容端点，再为其添加团队凭据。"
                />
              ) : null}
            </div>
            <AdminForm
              title="新增 / 更新提供商"
              description="首版支持 OpenAI-compatible 协议；使用同一 ID 更新配置。"
              fields={[
                { name: "id", label: "提供商 ID" },
                { name: "name", label: "名称" },
                { name: "endpoint", label: "API 端点", type: "url" },
                {
                  name: "protocol",
                  label: "协议",
                  defaultValue: "openai-compatible",
                  options: [
                    { value: "openai-compatible", label: "OpenAI-compatible" },
                  ],
                },
              ]}
              onSave={(value) =>
                save("/admin/providers", { ...value, enabled: true })
              }
            />
          </div>
        </TabsContent>
        <TabsContent value="credentials">
          <Alert>
            <AlertTitle>密钥只写入，不回显</AlertTitle>
            <AlertDescription>
              密钥加密保存；轮换创建新版本。旧版本仅在实际运行或审计仍依赖时保留。停用后拒绝新执行。
            </AlertDescription>
          </Alert>
          <div className="admin-layout">
            <div className="table-shell">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>凭据</TableHead>
                    <TableHead>提供商</TableHead>
                    <TableHead>版本 / 状态</TableHead>
                    <TableHead>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {credentials.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell>
                        {c.label}
                        <div className="cell-secondary">{c.id}</div>
                      </TableCell>
                      <TableCell>{c.provider_id}</TableCell>
                      <TableCell>
                        {c.current_version ?? c.version ?? "—"} ·{" "}
                        {c.enabled === false ? "停用" : "可用"}
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setRotation(c.id)}
                          >
                            轮换
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={c.enabled === false}
                            onClick={() =>
                              void mutate(`/admin/credentials/${c.id}/disable`)
                            }
                          >
                            停用
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {!credentials.length ? (
                <EmptyState
                  title="暂无团队凭据"
                  description="管理员添加密钥后，成员通过模型方案使用。"
                />
              ) : null}
            </div>
            <div className="flex flex-col gap-6">
              <AdminForm
                title="新增团队凭据"
                description="输入内容仅本次提交使用，不保存在浏览器。"
                fields={[
                  { name: "id", label: "凭据 ID" },
                  { name: "label", label: "显示名称" },
                  {
                    name: "provider_id",
                    label: "所属提供商",
                    options: providers.map((p) => ({
                      value: p.id,
                      label: p.name,
                    })),
                  },
                  { name: "key", label: "密钥", type: "password" },
                ]}
                onSave={(value) => save("/admin/credentials", value)}
              />
              {rotation ? (
                <AdminForm
                  key={rotation}
                  title={`轮换 ${rotation}`}
                  description="模型方案保持不变，后续新提交绑定此凭据的当前可用版本。"
                  fields={[{ name: "key", label: "新密钥", type: "password" }]}
                  onSave={async (value) => {
                    await save(`/admin/credentials/${rotation}/rotate`, value);
                    setRotation("");
                  }}
                />
              ) : null}
            </div>
          </div>
        </TabsContent>
        <TabsContent value="profiles">
          <div className="admin-layout">
            <div className="table-shell">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>模型方案</TableHead>
                    <TableHead>模型 / 凭据</TableHead>
                    <TableHead>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {profiles.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell>
                        {p.name}
                        <div className="cell-secondary">{p.id}</div>
                      </TableCell>
                      <TableCell>
                        {p.model}
                        <div className="cell-secondary">{p.credential_id}</div>
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            void save("/admin/model-profiles", {
                              ...p,
                              enabled: p.enabled === false,
                            }).catch((e) => toast.error(e.message))
                          }
                        >
                          {p.enabled === false ? "启用" : "停用"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {!profiles.length ? (
                <EmptyState
                  title="暂无模型方案"
                  description="方案明确引用提供商、凭据和模型。"
                />
              ) : null}
            </div>
            <AdminForm
              title="新增 / 更新模型方案"
              description="使用同一 ID 更新。已有实验继续保留提交时的配置快照。"
              fields={[
                { name: "id", label: "方案 ID" },
                { name: "name", label: "名称" },
                {
                  name: "provider_id",
                  label: "提供商",
                  options: providers.map((p) => ({
                    value: p.id,
                    label: p.name,
                  })),
                },
                {
                  name: "credential_id",
                  label: "凭据",
                  options: credentials.map((c) => ({
                    value: c.id,
                    label: `${c.label} · ${c.provider_id}`,
                  })),
                },
                { name: "model", label: "模型 ID" },
                {
                  name: "params",
                  label: "模型参数 JSON",
                  type: "textarea",
                  defaultValue: "{}",
                },
              ]}
              onSave={(value) =>
                save("/admin/model-profiles", {
                  ...value,
                  params: JSON.parse(value.params),
                  opencode_version: "1.18.35",
                  enabled: true,
                })
              }
            />
          </div>
        </TabsContent>
        <TabsContent value="limits">
          <Card>
            <CardHeader>
              <CardTitle>全局容量与保留参数</CardTitle>
              <CardDescription>
                CLI 与 Web
                共用。缩小容量不强制中断已运行的实验；对后续调度生效。保留期不代表无条件删除依赖数据。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  const value = Object.fromEntries(
                    [...new FormData(e.currentTarget).entries()].map(
                      ([k, v]) => [k, Number(v)],
                    ),
                  );
                  await mutate("/admin/limits", "PATCH", value);
                }}
              >
                <FieldGroup className="limits-grid">
                  {Object.entries(catalog.limits || {})
                    .filter(([name]) => name in limitLabels)
                    .map(([name, value]) => (
                      <Field key={name}>
                        <FieldLabel htmlFor={name}>
                          {limitLabels[name]}
                        </FieldLabel>
                        <Input
                          id={name}
                          name={name}
                          type="number"
                          min="1"
                          defaultValue={String(value)}
                          required
                        />
                      </Field>
                    ))}
                </FieldGroup>
                <Button className="mt-6">保存容量配置</Button>
              </form>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </>
  );
}
function Shell({ user, onLogout }: { user: Item; onLogout: () => void }) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" to="/">
          <FlaskConical />
          <span>
            Harbor<span className="brand-sub">团队实验室</span>
          </span>
        </Link>
        <nav aria-label="主导航">
          <NavLink end to="/">
            <LayoutList />
            共享实验
          </NavLink>
          <NavLink to="/new">
            <Plus />
            新建实验
          </NavLink>
          <NavLink to="/compare">
            <GitCompareArrows />
            实验对比
          </NavLink>
          {user.role === "admin" ? (
            <NavLink to="/admin">
              <Settings2 />
              团队管理
            </NavLink>
          ) : null}
        </nav>
        <div className="sidebar-bottom">
          <div className="avatar">
            {String(user.username || "?")
              .slice(0, 1)
              .toUpperCase()}
          </div>
          <div>
            <strong>{user.username}</strong>
            <span>{user.role === "admin" ? "管理员" : "团队成员"}</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="退出登录"
            onClick={async () => {
              try {
                await post("/auth/logout");
                onLogout();
              } catch (e) {
                toast.error((e as Error).message);
              }
            }}
          >
            <LogOut />
          </Button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span>团队工作空间</span>
          <span>全部实验共享可见</span>
        </header>
        <main>
          <Routes>
            <Route path="/" element={<ExperimentList />} />
            <Route path="/new" element={<NewExperiment />} />
            <Route
              path="/submissions/:id"
              element={<Submission user={user} />}
            />
            <Route path="/runs/:id" element={<RunDetail user={user} />} />
            <Route path="/compare" element={<Compare />} />
            <Route
              path="/admin"
              element={
                user.role === "admin" ? (
                  <Admin />
                ) : (
                  <EmptyState
                    title="需要管理员权限"
                    description="你仍可查看团队实验并提交自己的任务。"
                  />
                )
              }
            />
            <Route
              path="*"
              element={
                <EmptyState
                  title="页面不存在"
                  description="请从主导航选择实验或管理页面。"
                />
              }
            />
          </Routes>
        </main>
        <footer>
          Harbor Helper <span>共享队列 · 可追溯实验</span>
        </footer>
      </div>
    </div>
  );
}
function App() {
  const [user, setUser] = useState<Item | null>(null),
    [loading, setLoading] = useState(true),
    [failure, setFailure] = useState<unknown>();
  useEffect(() => {
    api("/me")
      .then((value) => setUser(value.user || value))
      .catch((e) => {
        if (!(e instanceof ApiError && e.code === "unauthorized"))
          setFailure(e);
      })
      .finally(() => setLoading(false));
    const expired = () => setUser(null);
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  return (
    <BrowserRouter>
      {loading ? (
        <div className="initial-loading">
          <LoaderCircle className="animate-spin" />
          <p>正在连接团队实验室…</p>
        </div>
      ) : user ? (
        <Shell user={user} onLogout={() => setUser(null)} />
      ) : (
        <>
          <Login
            onLogin={(value) => {
              setFailure(undefined);
              setUser(value);
            }}
          />
          {failure ? (
            <div className="connection-error">
              <ErrorNotice error={failure} />
            </div>
          ) : null}
        </>
      )}
      <Toaster position="bottom-right" richColors />
    </BrowserRouter>
  );
}
export default App;

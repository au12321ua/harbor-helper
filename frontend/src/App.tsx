import { useLoad } from "./useLoad";
import { Admin, SetupPage, AccountPage } from "./ConfigurationPages";
import {
  ErrorNotice,
  Status,
  Title,
  SelectField,
  EmptyState,
  Loading,
} from "./shared";
import { useEffect, useState, useRef } from "react";
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useNavigate,
  useParams,
  useLocation,
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
import { Separator } from "@/components/ui/separator";
import { toast, Toaster } from "sonner";
import "./App.css";

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
    JSON.stringify([r.id, r.name, r.submitter, r.dataset, r.status])
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
                    {r.name || r.id}
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
                  <Link to={`/submissions/${s.id}`}>
                    {s.request?.name || s.id}
                  </Link>
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
  const restored = useLocation().state?.request || {};
  const submitKey = useRef(newIdempotencyKey());
  const { data, error, loading } = useLoad(() => api("/catalog"));
  const navigate = useNavigate();
  const [dataset, setDataset] = useState(restored.dataset_id || ""),
    [agent, setAgent] = useState(restored.agent || "opencode"),
    [profile, setProfile] = useState(restored.model_profile || ""),
    [bundle, setBundle] = useState(restored.bundle_id || ""),
    [wall, setWall] = useState<number | undefined>(restored.wall_seconds),
    [busy, setBusy] = useState(false),
    [failure, setFailure] = useState<unknown>(),
    [uploadBusy, setUploadBusy] = useState(false);
  const datasets: Item[] = (data?.datasets || []).filter((d: Item) => d.ready);
  const selectedDataset =
    dataset || data?.settings?.default_dataset_id || datasets[0]?.id || "";
  const selected = datasets.find((d: Item) => d.id === selectedDataset);
  const selectedProfile =
    profile || data?.settings?.default_model_profile || "";
  if (loading) return <Loading />;
  const profiles: Item[] = (data?.model_profiles || []).filter(
    (p: Item) =>
      p.enabled !== false &&
      (data?.providers || []).some(
        (v: Item) => v.id === p.provider_id && v.enabled,
      ) &&
      (data?.credentials || []).some(
        (v: Item) => v.id === p.credential_id && v.enabled,
      ),
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
                dataset_id: selectedDataset,
                name: f.get("experiment_name") || "",
                agent,
                model_profile: agent === "oracle" ? null : selectedProfile,
                bundle_id: bundle || null,
                task: f.get("task") || null,
                attempts: Number(f.get("attempts")),
                concurrency: Number(f.get("concurrency")),
                wall_seconds: Number(f.get("wall_seconds")),
                environment_build_timeout_multiplier: Number(
                  f.get("environment_build_timeout_multiplier"),
                ),
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
                按名称选择团队验证过的数据集与任务，提交后固定本次来源与环境。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <FieldGroup>
                {!datasets.length ? (
                  <Alert>
                    <AlertTitle>团队尚无可用数据集</AlertTitle>
                    <AlertDescription>
                      请管理员在团队管理中登记并验证 benchmark 来源。
                    </AlertDescription>
                  </Alert>
                ) : null}
                <Field>
                  <FieldLabel htmlFor="experiment_name">
                    实验名称（可选）
                  </FieldLabel>
                  <Input
                    id="experiment_name"
                    name="experiment_name"
                    maxLength={128}
                    defaultValue={restored.name}
                    placeholder="例如：基线参考解 / 参数 A"
                  />
                </Field>
                <SelectField
                  label="数据集"
                  name="dataset"
                  value={selectedDataset}
                  onChange={setDataset}
                  description={
                    selected
                      ? `${selected.reference} · 已验证版本 ${selected.version}`
                      : "选择管理员验证的数据集"
                  }
                >
                  <option value="">选择数据集</option>
                  {datasets.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </SelectField>
                <Field>
                  <FieldLabel htmlFor="task">任务</FieldLabel>
                  <select
                    key={selectedDataset}
                    id="task"
                    name="task"
                    defaultValue={restored.task || ""}
                  >
                    <option value="">全部任务</option>
                    {(selected?.tasks || []).map((t: Item) => (
                      <option key={t.name} value={t.name}>
                        {t.name}
                      </option>
                    ))}
                  </select>
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
                    value={selectedProfile}
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
          <details>
            <summary>高级参数：启动等待、尝试次数、并发与运行时长</summary>
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
                    <FieldLabel htmlFor="environment_build_timeout_multiplier">
                      环境启动等待倍数
                    </FieldLabel>
                    <Input
                      id="environment_build_timeout_multiplier"
                      name="environment_build_timeout_multiplier"
                      type="number"
                      min="1"
                      step="0.1"
                      defaultValue={
                        restored.environment_build_timeout_multiplier ?? 10
                      }
                      required
                    />
                    <FieldDescription>
                      这是实验准备等待调整，作者声明的时限与文件保持不变。作者
                      build_timeout_sec ×
                      此倍数，覆盖构建、拉取与容器启动等待。默认10：作者30秒时等待300秒；1保留作者时限。整体运行时长仍可提前终止，安装依赖与推理时限不受此项影响。提交后冻结，重跑沿用。
                    </FieldDescription>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="attempts">每任务尝试次数</FieldLabel>
                    <Input
                      id="attempts"
                      name="attempts"
                      type="number"
                      min="1"
                      max={limits.max_attempts || 3}
                      defaultValue={restored.attempts || 1}
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
                      defaultValue={restored.concurrency || 1}
                      required
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="wall_seconds">
                      实验总时长上限（秒，含准备）
                    </FieldLabel>
                    <Input
                      id="wall_seconds"
                      name="wall_seconds"
                      type="number"
                      min="1"
                      max={limits.max_wall_seconds || 1800}
                      value={
                        wall ?? Math.min(1800, limits.max_wall_seconds || 1800)
                      }
                      onChange={(e) => setWall(Number(e.target.value))}
                      required
                    />
                    <FieldDescription>
                      从实验进入执行阶段计时，包含环境准备、代理工具准备与安装、模型执行和评分；不含此前来源准备与排队。环境启动用作者时限×倍数，代理准备沿Harbor默认360秒保护，模型执行另受作者agent时限约束。总上限更早到期会中止；资源清理可能晚于上限完成。
                    </FieldDescription>
                  </Field>
                </FieldGroup>
              </CardContent>
            </Card>
          </details>
        </div>
        <aside className="form-aside">
          <h2>提交前确认</h2>
          <p>全部团队成员都可以查看实验、日志、报告和产物。</p>
          <Separator />
          <p>提交者记为当前账户。重跑时创建新的实验记录，不覆盖历史结果。</p>
          <p>提供商、模型与参数在提交后固定；执行前会再次检查凭据是否可用。</p>
          {selected?.author_parameters?.discovery?.budgets?.map(
            (budget: Item) => (
              <p key={budget.task}>
                作者预算 {budget.task}：agent {budget.agent_seconds ?? "未知"}秒
                + verifier {budget.verifier_seconds ?? "未知"}秒。
                {(wall ?? Math.min(1800, limits.max_wall_seconds || 1800)) <=
                budget.agent_seconds + budget.verifier_seconds
                  ? "警告：整体上限不足以覆盖作者预算及准备；建议显式增加总时长。"
                  : "整体时长还需覆盖构建与工具准备。"}
              </p>
            ),
          )}
          {!selected?.author_parameters?.discovery ? (
            <p>
              作者预算尚未检查；管理员可在数据集页检查作者参数。总时长包含准备，默认1800秒。
            </p>
          ) : null}
          <p>预算估算仅单task，重复尝试/多任务另需余量。</p>
          <p>
            新实验环境准备等待默认为作者时限×10，可在高级参数改为1或其他倍数；整体运行上限仍生效。
          </p>
          <p>
            新模型实验先复用匹配的预装OpenCode；否则在任务网络外下载校验固定公共工具，再上传到作者容器离线安装。任务仍按作者网络运行，所选模型地址沿Harbor显式允许主机策略。
          </p>
          <Button
            type="submit"
            disabled={
              busy ||
              uploadBusy ||
              !selected ||
              (agent === "opencode" &&
                !profiles.some((p) => p.id === selectedProfile))
            }
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
  const recoveryKey = useRef(newIdempotencyKey());
  const [recovering, setRecovering] = useState(false);
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
      <Title
        title={
          data?.request?.name ||
          (data?.status === "failed"
            ? "实验准备失败"
            : data?.status === "cancelled"
              ? "实验已取消"
              : "实验准备")
        }
        description={`提交 ${id}`}
      />
      <ErrorNotice error={error} />
      {data?.legacy_override_removed ? (
        <Alert>
          <AlertDescription>
            本次重跑沿用父实验作者任务快照与模型参数，旧 helper
            镜像覆盖不再沿用；实际环境可能变化。
          </AlertDescription>
        </Alert>
      ) : null}
      <Card>
        <CardHeader>
          <CardTitle>
            <Status value={data?.status} />
          </CardTitle>
          <CardDescription>
            {data?.status === "failed"
              ? "本次准备已停止。修复配置或修改输入后重新提交，会创建新的实验。"
              : data?.status === "cancelled"
                ? "本次提交已取消。"
                : "数据源解析与准备完成后，自动进入统一队列。"}
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
          {data?.status === "failed" ? (
            <>
              <Button
                disabled={recovering}
                onClick={async () => {
                  setRecovering(true);
                  try {
                    const result = await post(
                      `/submissions/${id}/retry`,
                      {},
                      recoveryKey.current,
                    );
                    navigate(`/submissions/${result.id}`);
                  } catch (error) {
                    toast.error((error as Error).message);
                  } finally {
                    setRecovering(false);
                  }
                }}
              >
                按当前配置再次提交（保留原来源）
              </Button>
              {data.diagnosis?.map((issue: Item, index: number) => (
                <p key={index}>
                  {issue.task}：{issue.variables.join("、")} · {issue.reason}
                </p>
              ))}
              <Button variant="outline" asChild>
                <Link to="/new" state={{ request: data.request }}>
                  修改输入后新提交
                </Link>
              </Button>
              {user.role === "admin" ? (
                <Button variant="outline" asChild>
                  <Link to="/admin">修复团队配置</Link>
                </Button>
              ) : (
                <p>数据源权限或运行镜像问题请联系管理员在网页修复。</p>
              )}
            </>
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
  const retryKey = useRef(newIdempotencyKey());
  const [retryWall, setRetryWall] = useState<number | undefined>();
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
  const retryBudgets =
    manifest.service?.author_input_diagnostics?.budgets ||
    manifest.startup_policy?.tasks ||
    [];
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
        title={data?.row?.name || id || "实验详情"}
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
              variant="outline"
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
              按原条件重跑
            </Button>
          </div>
        }
      />
      <ErrorNotice error={error} />
      {row.status === "failed" ? (
        <Card>
          <CardHeader>
            <CardTitle>修复后重试</CardTitle>
            <CardDescription>
              保留父作者快照及研究因素；仅补缺失工具策略/启动倍率，按当前数据集参数重新检查。普通重跑保持原冻结条件。
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Field>
              <FieldLabel htmlFor="retry-wall">
                总时长（秒；默认保留父值）
              </FieldLabel>
              <Input
                id="retry-wall"
                type="number"
                min="1"
                value={retryWall ?? manifest.effective?.wall_seconds ?? 600}
                onChange={(event) => {
                  setRetryWall(Number(event.target.value));
                  retryKey.current = newIdempotencyKey();
                }}
              />
            </Field>
            <p>
              父总时长 {manifest.effective?.wall_seconds}秒。作者预算：
              {(
                manifest.service?.author_input_diagnostics?.budgets ||
                manifest.startup_policy?.tasks ||
                []
              )
                .map(
                  (budget: Item) =>
                    `${budget.task}：agent ${budget.agent_seconds ?? "未知"} + verifier ${budget.verifier_seconds ?? "未知"}秒`,
                )
                .join("；")}
              。预算估算仅单task，重复尝试/多任务另需余量。总时长包含构建及工具准备；根据作者预算显式设置总时长，改值会记录差异。
            </p>
            {(
              manifest.service?.author_input_diagnostics?.budgets ||
              manifest.startup_policy?.tasks ||
              []
            ).some(
              (budget: Item) =>
                Number.isFinite(budget.agent_seconds) &&
                Number.isFinite(budget.verifier_seconds) &&
                (retryWall ?? manifest.effective?.wall_seconds ?? 600) <=
                  budget.agent_seconds + budget.verifier_seconds,
            ) ? (
              <Alert>
                <AlertDescription>
                  警告：总时长不足以覆盖作者预算和准备。保留父值，不自动修改。
                </AlertDescription>
              </Alert>
            ) : null}
            {!retryBudgets.length ||
            retryBudgets.some(
              (budget: Item) =>
                !Number.isFinite(budget.agent_seconds) ||
                !Number.isFinite(budget.verifier_seconds),
            ) ? (
              <Alert>
                <AlertDescription>
                  作者预算未知，无法判断总时长是否足够；保留父值，不自动修改。
                </AlertDescription>
              </Alert>
            ) : null}
            <Button
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const result = await post(
                    `/runs/${id}/retry`,
                    retryWall === undefined ? {} : { wall_seconds: retryWall },
                    retryKey.current,
                  );
                  navigate(`/submissions/${result.id}`);
                } catch (error) {
                  toast.error((error as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              修复后重试
            </Button>
          </CardContent>
        </Card>
      ) : null}
      {manifest.service?.retry_changes &&
      Object.keys(manifest.service.retry_changes).length ? (
        <Alert>
          <AlertDescription>
            修复差异：{JSON.stringify(manifest.service.retry_changes)}
          </AlertDescription>
        </Alert>
      ) : null}
      {data?.failure_diagnosis ? (
        <Alert variant="destructive">
          <AlertDescription>{data.failure_diagnosis.message}</AlertDescription>
        </Alert>
      ) : null}
      <div className="detail-status">
        <Status value={row.status} />
        <Status value={row.audit_status} />
        {row.parent ? (
          <Link to={`/runs/${row.parent}`}>来源实验 {row.parent}</Link>
        ) : null}
      </div>
      {manifest.legacy_override_removed ? (
        <Alert>
          <AlertDescription>
            本次重跑沿用父作者任务快照与模型参数，旧 helper
            镜像覆盖不再沿用，实际环境可能变化。
          </AlertDescription>
        </Alert>
      ) : null}
      {manifest.execution_mode !== "harbor-native" ? (
        <Alert>
          <AlertDescription>
            此历史实验使用旧 helper
            镜像覆盖。重跑将按父作者定义执行，旧覆盖不再沿用。
          </AlertDescription>
        </Alert>
      ) : null}
      {row.audit_status === "incomplete" ? (
        <Alert variant="destructive">
          <AlertTitle>日志安全审计异常</AlertTitle>
          <AlertDescription>
            相关日志和产物暂不可展示。资源清理确认后会正常释放容量；安全摘要仍可查看。
          </AlertDescription>
        </Alert>
      ) : null}
      {data?.report?.tasks
        ?.flatMap((task: Item) => task.attempts || [])
        .filter((attempt: Item) => attempt.diagnosis)
        .map((attempt: Item) => (
          <Card key={attempt.trial || attempt.task}>
            <CardHeader>
              <CardTitle>
                {attempt.valid ? "执行阶段与耗时" : "失败定位与阶段耗时"} ·{" "}
                {attempt.task}
              </CardTitle>
              <CardDescription>{attempt.diagnosis.hint}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {attempt.diagnosis.model_status === "not_reached" ? (
                <p>未执行模型（尚未到代理执行阶段）</p>
              ) : null}
              <p>
                最后到达：
                {(
                  {
                    environment_setup: "环境启动",
                    agent_setup: "代理安装与准备",
                    agent_execution: "推理/参考解执行",
                    verifier: "评分",
                  } as Record<string, string>
                )[attempt.diagnosis.phase] || "未知"}{" "}
                · 启动倍数 {attempt.diagnosis.startup_multiplier}
              </p>
              <p>
                {attempt.diagnosis.phases
                  .map(
                    (phase: Item) =>
                      `${({ environment_setup: "环境启动", agent_setup: "代理准备", agent_execution: "执行", verifier: "评分" } as Record<string, string>)[phase.phase]}：${phase.reached ? (phase.seconds == null ? "耗时未知" : `${phase.seconds.toFixed(3)}秒`) : "未到达"}`,
                  )
                  .join("；")}
              </p>
              {attempt.diagnosis.agent_installation?.missing_dependencies
                ?.length ? (
                <p>
                  代理安装缺少：
                  {attempt.diagnosis.agent_installation.missing_dependencies.join(
                    "、",
                  )}
                  ；请查看作者网络约束与已审计日志。
                </p>
              ) : null}
              {attempt.diagnosis.agent_installation?.strategy ===
              "offline-npm-binary-v1" ? (
                <p>
                  代理工具：任务外联网准备 → 容器内离线安装；阶段{" "}
                  {attempt.diagnosis.agent_installation.stage}，状态{" "}
                  {attempt.diagnosis.agent_installation.status}，缓存
                  {attempt.diagnosis.agent_installation.cache_hit
                    ? "复用"
                    : "首次准备或未完成"}
                  。
                  {attempt.diagnosis.agent_installation.preparation_error_type
                    ? `公共材料准备错误：${attempt.diagnosis.agent_installation.preparation_error_type}`
                    : ""}
                </p>
              ) : null}
              {attempt.diagnosis.agent_installation?.binary_sha256 ? (
                <p style={{ overflowWrap: "anywhere" }}>
                  工具版本 {attempt.diagnosis.agent_installation.version}
                  ；公共准备{" "}
                  {attempt.diagnosis.agent_installation.preparation_seconds?.toFixed(
                    3,
                  ) ?? "未知"}{" "}
                  秒；SHA256{" "}
                  {attempt.diagnosis.agent_installation.binary_sha256}；来源{" "}
                  {attempt.diagnosis.agent_installation.source}。
                </p>
              ) : null}
              <p>
                Compose：
                {Array.isArray(attempt.diagnosis.compose)
                  ? attempt.diagnosis.compose
                      .map(
                        (phase: Item) =>
                          `${phase.phase} ${phase.status} ${phase.seconds == null ? "耗时未知" : `${phase.seconds.toFixed(3)}秒`}`,
                      )
                      .join("；")
                  : "阶段记录未知（旧记录可能未保存）"}
              </p>
            </CardContent>
          </Card>
        ))}
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
                  作者预构建镜像缓存观察:
                    manifest.service?.author_input_diagnostics?.images
                      ?.map(
                        (image: Item) =>
                          `${image.role} ${image.reference}：${image.cached === true ? "已缓存，不证明兼容" : image.cached === false ? "未缓存；Harbor需向registry获取；up未完成请检查registry与阶段记录，不能直接断言网络根因" : "未知"}`,
                      )
                      .join("；") || "无声明或尚未观察",
                  作者启动时限与有效等待:
                    manifest.startup_policy?.tasks
                      ?.map(
                        (task: Item) =>
                          `${task.task}：作者 ${task.author_build_timeout_sec} 秒 × ${manifest.startup_policy.multiplier} = 准备等待 ${task.start_wait_timeout_sec} 秒；作者网络 ${task.author_network_mode}`,
                      )
                      .join("；") || "未知",
                  环境启动策略: `作者 build_timeout_sec × ${manifest.effective?.environment_build_timeout_multiplier ?? 1}（冻结）；整体运行上限 ${manifest.effective?.wall_seconds ?? "未知"} 秒`,
                  代理工具策略:
                    manifest.effective?.agent === "opencode"
                      ? manifest.effective?.agent_tool_preparation ===
                        "offline-npm-binary-v1"
                        ? "匹配预装优先；任务外公共工具准备 / Harbor上传离线安装（冻结）"
                        : "旧受理：任务内安装（未暗改）"
                      : "参考解，无模型工具安装",
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
                <Button
                  variant="outline"
                  onClick={() => {
                    window.location.href = `/api/v1/runs/${id}/report/download`;
                  }}
                >
                  <Download data-icon="inline-start" />
                  下载评分报告
                </Button>
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
                    {r.name || r.id} · {r.dataset_name || r.dataset} ·{" "}
                    {r.submitter} · {labels[r.status] || r.status}
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
                    {r.name || r.id} · {r.dataset_name || r.dataset} ·{" "}
                    {r.submitter} · {labels[r.status] || r.status}
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
function Shell({ user, onLogout }: { user: Item; onLogout: () => void }) {
  const { data: catalog } = useLoad(() => api("/catalog"));
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
          <NavLink to="/account">
            <Settings2 />
            账户与密码
          </NavLink>
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
          <span>{catalog?.settings?.team_name || "团队工作空间"}</span>
          <span>全部实验共享可见</span>
        </header>
        <main>
          <Routes>
            <Route
              path="/account"
              element={<AccountPage logout={onLogout} />}
            />
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
    [setup, setSetup] = useState(false),
    [failure, setFailure] = useState<unknown>();
  useEffect(() => {
    api("/setup")
      .then((status) => {
        if (!status.initialized) {
          setSetup(true);
          return null;
        }
        return api("/me");
      })
      .then((value) => {
        if (value) setUser(value.user || value);
      })
      .catch((e) => {
        if (!(
          e instanceof ApiError &&
          ["unauthorized", "login_required"].includes(e.code)
        ))
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
      ) : setup ? (
        <SetupPage
          done={() => {
            setSetup(false);
            setFailure(undefined);
          }}
        />
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

import { api, newIdempotencyKey, post, type User } from "@/api";
import { ErrorNotice, Loading, Status, Title } from "@/components/shared";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLoad } from "@/hooks/useLoad";
import { date, terminal } from "@/presentation";
import { ArrowLeft, Copy, RefreshCw } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { MaterialsPanel } from "./MaterialsPanel";
import { ArtifactsPanel } from "./ArtifactsPanel";
import { OverviewPanel } from "./OverviewPanel";
import { ReportPanel } from "./ReportPanel";
import { RunLogs } from "./RunLogs";
export function RunDetail({ user }: { user: User }) {
  const { id } = useParams();
  return <RunDetailContent key={id} user={user} />;
}

export function RunDetailContent({ user }: { user: User }) {
  const rerunKey = useRef(newIdempotencyKey());
  const retryKey = useRef(newIdempotencyKey());
  const [retryWall, setRetryWall] = useState<number | undefined>();
  const { id } = useParams();
  const { data, error, loading, reload } = useLoad(
    () => api(`/runs/${id}`),
    id || "",
    3000,
  );
  const [tab, setTab] = useState("overview");
  const [busy, setBusy] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  if (loading) return <Loading />;
  if (!data) return <ErrorNotice error={error} />;
  const row = data.row,
    manifest = data.manifest;
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
        <Link to={location.state?.listUrl || "/"}>
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
                  navigate(`/submissions/${s.id}`);
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
        <div className="detail-id">
          <span>{row.id}</span>
          <Button
            size="icon"
            variant="ghost"
            aria-label="复制实验 ID"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(row.id);
                toast.success("实验 ID 已复制");
              } catch {
                toast.error("无法复制，请手动选择 ID");
              }
            }}
          >
            <Copy />
          </Button>
        </div>
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
      <dl className="detail-meta">
        {Object.entries({
          数据集: row.dataset,
          模型方案: row.model_profile || "—",
          代理: row.agent || manifest.effective?.agent || "—",
          执行并发: row.concurrency,
          总时长上限: `${manifest.effective?.wall_seconds ?? "未知"} s`,
          附件版本: manifest.service?.attachment_version_id || "无附件",
        }).map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="overview">配置与状态</TabsTrigger>
          <TabsTrigger value="report">评分报告</TabsTrigger>
          <TabsTrigger value="logs">运行日志</TabsTrigger>
          <TabsTrigger value="artifacts">实验产物</TabsTrigger>
          <TabsTrigger value="materials">完整资料</TabsTrigger>
        </TabsList>
        {tab === "materials" && <MaterialsPanel id={id || ""} />}
        <OverviewPanel
          row={row}
          manifest={manifest}
          frozen={
            <>
              {" "}
              <Card>
                <CardHeader>
                  <CardTitle>冻结附件引用</CardTitle>
                  <CardDescription>本实验的固定输入谱系</CardDescription>
                </CardHeader>
                <CardContent>
                  <p>
                    {data?.manifest?.service?.attachment_version_id || "无附件"}
                  </p>
                  <p>
                    {data?.manifest?.service?.bundle_id ||
                      "未绑定底层 bundle ID"}
                  </p>
                  <p className="break-all">
                    {data?.manifest?.bundle_digest || "无附件摘要"}
                  </p>
                </CardContent>
              </Card>
            </>
          }
        >
          {!data.report && (
            <div className="diagnosis quiet-note">
              阶段诊断在运行结束、审计完成后随报告提供。当前未发布阶段数据。
            </div>
          )}
          {data?.report?.tasks
            ?.flatMap((task) => task.attempts || [])
            .filter(
              (
                attempt,
              ): attempt is typeof attempt & {
                diagnosis: NonNullable<typeof attempt.diagnosis>;
              } => !!attempt.diagnosis,
            )
            .map((attempt, index) => (
              <details
                className="diagnosis"
                key={`${attempt.task}:${attempt.trial || index}`}
                open={!attempt.valid}
              >
                <summary>
                  <span>
                    {attempt.valid ? "执行阶段与耗时" : "失败定位与阶段耗时"} ·{" "}
                    {attempt.task}
                  </span>
                  <small>
                    {attempt.trial || "尝试记录"} ·{" "}
                    {attempt.valid ? "有效" : "无效"} · {attempt.diagnosis.hint}
                  </small>
                </summary>
                <div className="diagnosis-body">
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
                        (phase) =>
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
                      {attempt.diagnosis.agent_installation
                        .preparation_error_type
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
                            (phase) =>
                              `${phase.phase} ${phase.status} ${phase.seconds == null ? "耗时未知" : `${phase.seconds.toFixed(3)}秒`}`,
                          )
                          .join("；")
                      : "阶段记录未知（旧记录可能未保存）"}
                  </p>
                </div>
              </details>
            ))}
          <RunLogs key={id} id={id || ""} />
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
                      (budget) =>
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
                  (budget) =>
                    typeof budget.agent_seconds === "number" &&
                    Number.isFinite(budget.agent_seconds) &&
                    typeof budget.verifier_seconds === "number" &&
                    Number.isFinite(budget.verifier_seconds) &&
                    (retryWall ?? manifest.effective?.wall_seconds ?? 600) <=
                      (budget.agent_seconds ?? 0) +
                        (budget.verifier_seconds ?? 0),
                ) ? (
                  <Alert>
                    <AlertDescription>
                      警告：总时长不足以覆盖作者预算和准备。保留父值，不自动修改。
                    </AlertDescription>
                  </Alert>
                ) : null}
                {!retryBudgets.length ||
                retryBudgets.some(
                  (budget) =>
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
                        retryWall === undefined
                          ? {}
                          : { wall_seconds: retryWall },
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
        </OverviewPanel>
        <ReportPanel data={data} />
        <TabsContent value="logs">
          <RunLogs key={id} id={id || ""} />
        </TabsContent>
        <ArtifactsPanel data={data} user={user} reload={reload} />
      </Tabs>
    </>
  );
}

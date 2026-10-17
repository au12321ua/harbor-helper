import { api, newIdempotencyKey, post, type Catalog } from "@/api";
import { ErrorNotice, Loading, SelectField, Title } from "@/components/shared";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ReadinessNotice } from "@/features/admission/ReadinessPanel";
import { useLoad } from "@/hooks/useLoad";
import { LoaderCircle, Plus } from "lucide-react";
import {
  initialDraft,
  problems,
  profilesFor,
  submissionBody,
  text,
  type DraftField,
  type NewEntry,
} from "./reuse";
import { useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
const fieldLabels: Record<DraftField, string> = {
  name: "实验名称",
  dataset_id: "数据集",
  task: "任务",
  agent: "执行方案",
  model_profile: "模型方案",
  attachment_version_id: "附件版本",
  attempts: "尝试次数",
  concurrency: "并发数",
  wall_seconds: "总时长",
  environment_build_timeout_multiplier: "环境启动等待倍数",
};
export function NewExperiment() {
  const location = useLocation();
  const { data, error, loading } = useLoad(() => api("/catalog"));
  if (loading) return <Loading />;
  if (!data) return <ErrorNotice error={error} />;
  return (
    <ExperimentForm
      key={location.key}
      data={data}
      entry={location.state?.entry}
    />
  );
}
function ExperimentForm({ data, entry }: { data: Catalog; entry?: NewEntry }) {
  const [draft, setDraft] = useState(() => initialDraft(data, entry));
  const submitKey = useRef(newIdempotencyKey());
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false),
    [failure, setFailure] = useState<unknown>();
  const change = (field: DraftField, value: unknown) => {
    setDraft((d) => ({ ...d, [field]: value }));
    submitKey.current = newIdempotencyKey();
  };
  const issues = problems(draft, data);
  const datasets = data.datasets.filter((d) => d.ready && d.enabled !== false);
  const selectedDataset = text(draft.dataset_id),
    agent = text(draft.agent),
    selectedProfile = text(draft.model_profile),
    version = text(draft.attachment_version_id),
    taskName = text(draft.task),
    wall = Number(draft.wall_seconds);
  const execution = {
    attempts: text(draft.attempts),
    concurrency: text(draft.concurrency),
  };
  const selected = datasets.find((d) => d.id === draft.dataset_id);
  const profiles = profilesFor(data),
    limits = data.limits;
  const originalOption = (field: DraftField) =>
    issues[field] ? (
      <option
        value={draft[field] === undefined ? "__unknown__" : text(draft[field])}
      >
        {draft[field] === undefined
          ? "未知：请明确选择"
          : `原值 ${text(draft[field])}（需修正）`}
      </option>
    ) : null;
  const selectedTasks = (selected?.tasks || []).filter(
    (task) => !taskName || task.name === taskName,
  );
  const parameters = selected?.author_parameters;
  const checkedBudgets = selectedTasks.flatMap((task) => {
    if (
      !selected?.resolved ||
      !task.ref ||
      parameters?.source !== selected.resolved
    )
      return [];
    const record = parameters?.checked_tasks?.find(
      (record) => record.name === task.name && record.ref === task.ref,
    );
    return record?.discovery?.budgets || [];
  });
  const unknownBudgets =
    selectedTasks.length -
    checkedBudgets.filter(
      (budget) =>
        typeof budget.agent_seconds === "number" &&
        Number.isFinite(budget.agent_seconds) &&
        Number.isFinite(budget.verifier_seconds),
    ).length;
  return (
    <>
      <Title
        title="新建实验"
        description="选择数据集与模型方案；提交后固定本次实验的配置。"
      />
      <ErrorNotice error={failure} />
      {entry?.kind === "history" && (
        <Alert>
          <AlertTitle>从 {entry.source} 复制新建</AlertTitle>
          <AlertDescription>
            按当前目录、模型和附件重新校验并冻结；“按原条件重跑”仍保留原冻结条件。
            {entry.datasetVersion != null &&
            selected &&
            entry.datasetVersion !== selected.version
              ? `来源数据集版本 ${entry.datasetVersion}，当前版本 ${selected.version}。`
              : ""}
          </AlertDescription>
        </Alert>
      )}
      {Object.entries(issues).length > 0 && (
        <Alert variant="destructive">
          <AlertTitle>配置需要明确修正</AlertTitle>
          <AlertDescription>
            {Object.entries(issues).map(([field, reason]) => (
              <p key={field}>
                {fieldLabels[field as DraftField]}：{reason}；原值{" "}
                {draft[field as DraftField] === undefined
                  ? "未知"
                  : text(draft[field as DraftField])}
              </p>
            ))}
          </AlertDescription>
        </Alert>
      )}
      <ReadinessNotice />
      <form
        className="new-experiment-form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (Object.keys(problems(draft, data)).length) return;
          setBusy(true);
          setFailure(undefined);
          try {
            const s = await post(
              "/submissions",
              submissionBody(draft),
              submitKey.current,
            );
            navigate(`/submissions/${s.id}`);
          } catch (err) {
            setFailure(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <fieldset disabled={busy} className="form-layout min-w-0">
          <div className="flex flex-col gap-4">
            <Card>
              <CardHeader>
                <CardTitle>实验输入</CardTitle>
              </CardHeader>
              <CardContent>
                <FieldGroup className="experiment-inputs">
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
                      value={text(draft.name)}
                      onChange={(e) => change("name", e.target.value)}
                      placeholder="例如：基线参考解 / 参数 A"
                    />
                  </Field>
                  <SelectField
                    label="数据集"
                    name="dataset"
                    value={
                      draft.dataset_id === undefined
                        ? "__unknown__"
                        : selectedDataset
                    }
                    onChange={(value) => {
                      change("dataset_id", value);
                      // Require an explicit task choice after changing dataset.
                      change("task", undefined);
                    }}
                    description={
                      selected
                        ? `${selected.reference} · 已验证版本 ${selected.version}`
                        : "选择管理员验证的数据集"
                    }
                  >
                    {originalOption("dataset_id")}
                    {draft.dataset_id !== undefined && (
                      <option value="">选择数据集</option>
                    )}
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
                      value={
                        draft.task === undefined ? "__unknown__" : taskName
                      }
                      onChange={(e) => change("task", e.target.value)}
                    >
                      {originalOption("task")}
                      <option value="">全部任务</option>
                      {(selected?.tasks || []).map((t) => (
                        <option key={t.name} value={t.name}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <SelectField
                    label="执行方案"
                    name="agent"
                    value={draft.agent === undefined ? "__unknown__" : agent}
                    onChange={(v) => change("agent", v)}
                  >
                    {originalOption("agent")}
                    <option value="opencode">模型 · OpenCode</option>
                    <option value="oracle">Oracle · 数据集参考解</option>
                  </SelectField>
                  {agent !== "oracle" ? (
                    <SelectField
                      label="模型方案"
                      name="profile"
                      value={
                        draft.model_profile === undefined
                          ? "__unknown__"
                          : selectedProfile
                      }
                      onChange={(v) => change("model_profile", v)}
                      description="使用管理员配置的团队凭据，密钥不会展示给成员。"
                    >
                      {originalOption("model_profile")}
                      <option value="">选择模型方案</option>
                      {profiles.map((p) => (
                        <option key={p.id} value={p.id}>
                          {String(p.name || p.id)} · {p.model}
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
                  <SelectField
                    label="团队附件版本（可选）"
                    required={false}
                    name="attachment_version"
                    value={
                      draft.attachment_version_id === undefined
                        ? "__unknown__"
                        : version
                    }
                    onChange={(v) => change("attachment_version_id", v)}
                  >
                    {originalOption("attachment_version_id")}
                    <option value="">无附件</option>
                    {(data?.attachments || []).flatMap((a) =>
                      a.versions.map((v) => (
                        <option
                          key={v.id}
                          value={v.id}
                          disabled={
                            !a.enabled ||
                            !v.enabled ||
                            v.availability !== "available"
                          }
                        >
                          {a.name} · v{v.number} · {v.id}
                        </option>
                      )),
                    )}
                  </SelectField>
                  <div className="attachment-baseline">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        change("attachment_version_id", "");
                        submitKey.current = newIdempotencyKey();
                      }}
                    >
                      清除附件，使用无附件基线
                    </Button>
                    <p>
                      {version
                        ? `当前附件版本：${version}`
                        : "当前选择：无附件"}
                    </p>
                  </div>
                </FieldGroup>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>执行参数</CardTitle>
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
                      type="text"
                      inputMode="numeric"
                      aria-describedby="environment-multiplier-hint"
                      value={text(draft.environment_build_timeout_multiplier)}
                      onChange={(e) =>
                        change(
                          "environment_build_timeout_multiplier",
                          e.target.value,
                        )
                      }
                      required
                    />
                    <p id="environment-multiplier-hint" className="quiet-note">
                      等待倍数必须为正整数（至少 1），不支持小数。
                    </p>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="attempts">每任务尝试次数</FieldLabel>
                    <Input
                      id="attempts"
                      name="attempts"
                      type="text"
                      inputMode="decimal"
                      min="1"
                      max={limits?.max_attempts || 3}
                      value={text(draft.attempts)}
                      onChange={(e) => change("attempts", e.target.value)}
                      required
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="concurrency">实验并发数</FieldLabel>
                    <Input
                      id="concurrency"
                      name="concurrency"
                      type="text"
                      inputMode="decimal"
                      min="1"
                      max={limits?.max_trials || 2}
                      value={text(draft.concurrency)}
                      onChange={(e) => change("concurrency", e.target.value)}
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
                      type="text"
                      inputMode="decimal"
                      min="1"
                      max={limits?.max_wall_seconds || 1800}
                      value={text(draft.wall_seconds)}
                      onChange={(e) => change("wall_seconds", e.target.value)}
                      required
                    />
                  </Field>
                </FieldGroup>
              </CardContent>
            </Card>
            <details>
              <summary>高级参数：启动等待、尝试次数、并发与运行时长</summary>
              <p>
                这是实验准备等待调整，作者声明的时限与文件保持不变。作者
                build_timeout_sec ×
                此倍数，覆盖构建、拉取与容器启动等待。默认10：作者30秒时等待300秒；1保留作者时限。整体运行时长仍可提前终止，安装依赖与推理时限不受此项影响。提交后冻结，重跑沿用。
              </p>
              <p>
                从实验进入执行阶段计时，包含环境准备、代理工具准备与安装、模型执行和评分；不含此前来源准备与排队。环境启动用作者时限×倍数，代理准备沿Harbor默认360秒保护，模型执行另受作者agent时限约束。总上限更早到期会中止；资源清理可能晚于上限完成。
              </p>
              <div className="policy-notes">
                {" "}
                <p>
                  新实验环境准备等待默认为作者时限×10，可在高级参数改为1或其他倍数；整体运行上限仍生效。
                </p>
                <p>
                  新模型实验先复用匹配的预装OpenCode；否则在任务网络外下载校验固定公共工具，再上传到作者容器离线安装。任务仍按作者网络运行，所选模型地址沿Harbor显式允许主机策略。
                </p>
              </div>
            </details>
            <div className="budget-notes">
              {" "}
              {checkedBudgets.map((budget) => (
                <p key={budget.task}>
                  作者预算 {budget.task}：agent {budget.agent_seconds ?? "未知"}
                  秒 + verifier {budget.verifier_seconds ?? "未知"}秒。
                  {typeof budget.agent_seconds === "number" &&
                  Number.isFinite(budget.agent_seconds) &&
                  typeof budget.verifier_seconds === "number" &&
                  Number.isFinite(budget.verifier_seconds) &&
                  (wall ?? Math.min(1800, limits?.max_wall_seconds || 1800)) <=
                    (budget.agent_seconds ?? 0) + (budget.verifier_seconds ?? 0)
                    ? "警告：整体上限不足以覆盖作者预算及准备；建议显式增加总时长。"
                    : "整体时长还需覆盖构建与工具准备。"}
                </p>
              ))}
              {unknownBudgets > 0 ? (
                <p>
                  另有 {unknownBudgets}{" "}
                  个所选任务作者预算未知，无法判断总时长是否足够；管理员可选择任务检查。默认1800秒，总时长包含准备。
                </p>
              ) : null}
              <p>预算估算仅单task，重复尝试/多任务另需余量。</p>
            </div>
            <div className="submission-actions">
              {" "}
              <ReadinessNotice />
              <Button
                type="submit"
                disabled={busy || Object.keys(issues).length > 0}
              >
                {busy ? (
                  <LoaderCircle
                    data-icon="inline-start"
                    className="animate-spin"
                  />
                ) : (
                  <Plus data-icon="inline-start" />
                )}
                提交实验
              </Button>
            </div>
          </div>
          <aside className="form-aside">
            <div className="submission-summary">
              <h2>提交摘要</h2>
              <dl>
                {Object.entries({
                  数据集: selected?.reference || "—",
                  任务:
                    draft.task === undefined ? "未知" : taskName || "全部任务",
                  模型方案:
                    agent === "oracle" ? "Oracle" : selectedProfile || "—",
                  附件: version || "无附件",
                  "尝试 / 并发": `${execution.attempts} / ${execution.concurrency}`,
                  总时长: `${draft.wall_seconds === undefined ? "未知" : text(draft.wall_seconds)} s`,
                }).map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{String(v)}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <p>
              全部团队成员共享实验、日志、报告与产物；来源和运行配置在提交后固定。
            </p>
          </aside>
        </fieldset>
      </form>
    </>
  );
}

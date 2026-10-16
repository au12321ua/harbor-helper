import { api, newIdempotencyKey, post } from "@/api";
import { ErrorNotice, Loading, SelectField, Title } from "@/components/shared";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ReadinessNotice } from "@/features/admission/ReadinessPanel";
import { useLoad } from "@/hooks/useLoad";
import { LoaderCircle, Plus } from "lucide-react";
import { useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
export function NewExperiment() {
  const restored = useLocation().state?.request || {};
  const [execution, setExecution] = useState({
    attempts: restored.attempts || 1,
    concurrency: restored.concurrency || 1,
  });
  const submitKey = useRef(newIdempotencyKey());
  const { data, error, loading } = useLoad(() => api("/catalog"));
  const navigate = useNavigate();
  const [dataset, setDataset] = useState(restored.dataset_id || ""),
    [agent, setAgent] = useState(restored.agent || "opencode"),
    [profile, setProfile] = useState(restored.model_profile || ""),
    [version, setVersion] = useState(restored.attachment_version_id || ""),
    [taskName, setTaskName] = useState(restored.task || ""),
    [wall, setWall] = useState<number | undefined>(restored.wall_seconds),
    [busy, setBusy] = useState(false),
    [failure, setFailure] = useState<unknown>();
  const datasets = (data?.datasets || []).filter((d) => d.ready);
  const selectedDataset =
    dataset || data?.settings?.default_dataset_id || datasets[0]?.id || "";
  const selected = datasets.find((d) => d.id === selectedDataset);
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
  const selectedProfile =
    profile || String(data?.settings?.default_model_profile || "");
  if (loading) return <Loading />;
  const profiles = (data?.model_profiles || []).filter(
    (p) =>
      p.enabled !== false &&
      (data?.providers || []).some(
        (v) => v.id === p.provider_id && v.enabled,
      ) &&
      (data?.credentials || []).some(
        (v) => v.id === p.credential_id && v.enabled,
      ),
  );
  const limits = data?.limits;
  return (
    <>
      <Title
        title="新建实验"
        description="选择数据集与模型方案；提交后固定本次实验的配置。"
      />
      <ErrorNotice error={error || failure} />
      <ReadinessNotice />
      <form
        className="new-experiment-form"
        onChange={(event) => {
          const values = new FormData(event.currentTarget);
          setExecution({
            attempts: Number(values.get("attempts")),
            concurrency: Number(values.get("concurrency")),
          });
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
                name: String(f.get("experiment_name") || ""),
                agent,
                model_profile: agent === "oracle" ? null : selectedProfile,
                attachment_version_id: version || null,
                task: String(f.get("task") || "") || null,
                attempts: Number(f.get("attempts")),
                concurrency: Number(f.get("concurrency")),
                wall_seconds: Number(f.get("wall_seconds")),
                environment_build_timeout_multiplier: Number(
                  f.get("environment_build_timeout_multiplier"),
                ),
              },
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
                      defaultValue={restored.name}
                      placeholder="例如：基线参考解 / 参数 A"
                    />
                  </Field>
                  <SelectField
                    label="数据集"
                    name="dataset"
                    value={selectedDataset}
                    onChange={(value) => {
                      setDataset(value);
                      setTaskName("");
                    }}
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
                      value={taskName}
                      onChange={(e) => setTaskName(e.target.value)}
                    >
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
                    value={version}
                    onChange={setVersion}
                  >
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
                        setVersion("");
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
                      type="number"
                      min="1"
                      step="0.1"
                      defaultValue={
                        restored.environment_build_timeout_multiplier ?? 10
                      }
                      required
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="attempts">每任务尝试次数</FieldLabel>
                    <Input
                      id="attempts"
                      name="attempts"
                      type="number"
                      min="1"
                      max={limits?.max_attempts || 3}
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
                      max={limits?.max_trials || 2}
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
                      max={limits?.max_wall_seconds || 1800}
                      value={
                        wall ?? Math.min(1800, limits?.max_wall_seconds || 1800)
                      }
                      onChange={(e) => setWall(Number(e.target.value))}
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
                disabled={
                  busy ||
                  !selected ||
                  (agent === "opencode" &&
                    !profiles.some((p) => p.id === selectedProfile))
                }
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
                  任务: taskName || "全部任务",
                  模型方案:
                    agent === "oracle" ? "Oracle" : selectedProfile || "—",
                  附件: version || "无附件",
                  "尝试 / 并发": `${execution.attempts} / ${execution.concurrency}`,
                  总时长: `${wall ?? Math.min(1800, limits?.max_wall_seconds || 1800)} s`,
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

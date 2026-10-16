import { api, ApiError, post, type Comparison } from "@/api";
import { ErrorNotice, Loading, SelectField, Title } from "@/components/shared";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { FieldGroup } from "@/components/ui/field";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useLoad } from "@/hooks/useLoad";
import { canCompare, labels, metricNumber } from "@/presentation";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
function NumberCell({ value }: { value: number | null | undefined }) {
  return (
    <TableCell className="num" title={value == null ? "缺失" : String(value)}>
      {metricNumber(value)}
    </TableCell>
  );
}
export function ComparisonResult({ value }: { value: Comparison }) {
  const a = value.attachment_inputs?.left,
    b = value.attachment_inputs?.right;
  const attachmentChanged =
    (a?.attachment_version_id || "") !== (b?.attachment_version_id || "") ||
    (a?.digest || value.bundle_change?.left || "") !==
      (b?.digest || value.bundle_change?.right || "");
  return (
    <div className="flex flex-col gap-4">
      <Alert>
        <AlertTitle>{value.comparable ? "实验可比" : "实验不可比"}</AlertTitle>
        <AlertDescription>
          {value.comparable
            ? "结果遵循服务端评分与可比性判断。"
            : "未生成聚合评分或逐任务变化；请检查差异原因。"}
          {!!value.reasons?.length && (
            <ul className="list-disc pl-4">
              {value.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
        </AlertDescription>
      </Alert>
      {value.comparable && value.mean_task_delta != null && (
        <div className="report-summary">
          {Object.entries(value.mean_task_delta).map(([metric, delta]) => (
            <div key={metric}>
              <span>{metric} · 平均任务变化 (B − A)</span>
              <strong title={String(delta)}>{metricNumber(delta)}</strong>
            </div>
          ))}
        </div>
      )}
      {value.comparable && !!value.tasks?.length && (
        <>
          <div className="section-bar">
            <h2>逐任务结果</h2>
            <span className="quiet-note">
              变化表示数值差；不推断未知指标的优劣方向
            </span>
          </div>
          <div className="table-shell compare-table">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>任务</TableHead>
                  <TableHead className="metric-column">指标</TableHead>
                  <TableHead className="num">A</TableHead>
                  <TableHead className="num">B</TableHead>
                  <TableHead className="num">Δ</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {value.tasks.flatMap((task) =>
                  Array.from(
                    new Set([
                      ...Object.keys(task.left || {}),
                      ...Object.keys(task.right || {}),
                      ...Object.keys(task.delta || {}),
                    ]),
                  ).map((metric) => (
                    <TableRow key={`${task.task}:${metric}`}>
                      <TableCell className="mono">
                        {task.task}
                        <small className="mobile-metric">{metric}</small>
                      </TableCell>
                      <TableCell className="metric-column mono">
                        {metric}
                      </TableCell>
                      <NumberCell value={task.left?.[metric]} />
                      <NumberCell value={task.right?.[metric]} />
                      <NumberCell value={task.delta?.[metric]} />
                    </TableRow>
                  )),
                )}
              </TableBody>
            </Table>
          </div>
        </>
      )}
      <div className="section-bar">
        <h2>输入差异</h2>
        <span className="quiet-note">配置与附件的可追溯证据</span>
      </div>
      <div className="table-shell">
        <Table className="diff-table">
          <TableHeader>
            <TableRow>
              <TableHead>因素</TableHead>
              <TableHead>实验 A</TableHead>
              <TableHead>实验 B</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell>附件版本</TableCell>
              <TableCell>{a?.attachment_version_id || "无附件"}</TableCell>
              <TableCell>{b?.attachment_version_id || "无附件"}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>附件摘要</TableCell>
              <TableCell>
                {a?.digest || value.bundle_change?.left || "无附件摘要"}
              </TableCell>
              <TableCell>
                {b?.digest || value.bundle_change?.right || "无附件摘要"}
              </TableCell>
            </TableRow>
            {Object.entries(value.config_changes || {}).map(
              ([factor, change]) => (
                <TableRow key={factor}>
                  <TableCell>{factor}</TableCell>
                  <TableCell>{JSON.stringify(change.left ?? null)}</TableCell>
                  <TableCell>{JSON.stringify(change.right ?? null)}</TableCell>
                </TableRow>
              ),
            )}
          </TableBody>
        </Table>
      </div>
      <p className="quiet-note">
        {attachmentChanged
          ? "附件版本或摘要存在差异。"
          : "附件相同或双方均无附件。"}
        可比性仍检查任务、评分、基础 agent/模型及其他固定条件。
      </p>
      <details className="raw-details">
        <summary>完整对比记录与环境观察</summary>
        <pre>{JSON.stringify(value, null, 2)}</pre>
      </details>
    </div>
  );
}
export function Compare() {
  const { data, error, loading } = useLoad(() => api("/runs"));
  const [params, setParams] = useSearchParams();
  const left = params.get("left") || "",
    right = params.get("right") || "";
  const key = JSON.stringify([left, right]);
  const currentKey = useRef(key);
  const requestId = useRef(0);
  useEffect(() => {
    currentKey.current = key;
    requestId.current++;
  }, [key]);
  const [result, setResult] = useState<{ key: string; value: Comparison }>();
  const [failure, setFailure] = useState<{ key: string; error: unknown }>();
  const [busy, setBusy] = useState<string>();
  useEffect(
    () => () => {
      requestId.current++;
    },
    [],
  );
  function choose(side: string, id: string) {
    requestId.current++;
    setBusy(undefined);
    setResult(undefined);
    setFailure(undefined);
    const next = new URLSearchParams(params);
    if (id) next.set(side, id);
    else next.delete(side);
    setParams(next, { replace: true });
  }
  if (loading) return <Loading />;
  const runs = data?.runs || [];
  const eligible =
    runs.some((r) => r.id === left && canCompare(r)) &&
    runs.some((r) => r.id === right && canCompare(r));
  const currentFailure = failure?.key === key ? failure.error : undefined;
  const unavailable =
    currentFailure instanceof ApiError &&
    ["report_pending", "audit_incomplete", "evidence_expired"].includes(
      currentFailure.code,
    );
  return (
    <>
      <Title title="实验对比" description="逐任务检查配置与评分差异。" />
      <ErrorNotice error={error || (!unavailable && currentFailure)} />
      <form
        className="compare-selector"
        onSubmit={async (e) => {
          e.preventDefault();
          const token = ++requestId.current;
          const submittedKey = key;
          setBusy(key);
          setResult(undefined);
          setFailure(undefined);
          try {
            const value = await post("/compare", { left, right });
            if (
              token === requestId.current &&
              submittedKey === currentKey.current
            )
              setResult({ key: submittedKey, value });
          } catch (error) {
            if (
              token === requestId.current &&
              submittedKey === currentKey.current
            )
              setFailure({ key: submittedKey, error });
          } finally {
            if (token === requestId.current) setBusy(undefined);
          }
        }}
      >
        <FieldGroup className="comparison-form">
          {(["left", "right"] as const).map((side) => (
            <SelectField
              key={side}
              label={side === "left" ? "实验 A" : "实验 B"}
              name={side}
              value={side === "left" ? left : right}
              onChange={(id) => choose(side, id)}
              description={(() => {
                const selected = runs.find(
                  (r) => r.id === (side === "left" ? left : right),
                );
                return selected
                  ? `${selected.dataset || "—"} · ${selected.model_profile || selected.agent || "—"}`
                  : "仅终态且审计完成可选，报告仍可能尚未发布或已过期";
              })()}
            >
              <option value="">选择实验</option>
              {(side === "left" ? left : right) &&
                !runs.some(
                  (r) => r.id === (side === "left" ? left : right),
                ) && (
                  <option value={side === "left" ? left : right} disabled>
                    实验不存在或不可访问
                  </option>
                )}
              {runs.map((r) => (
                <option key={r.id} value={r.id} disabled={!canCompare(r)}>
                  {r.name || r.id} · {r.dataset_name || r.dataset} ·{" "}
                  {r.submitter} · {labels[r.status] || r.status}
                  {!canCompare(r)
                    ? " · 报告未发布：运行未结束或审计未完成"
                    : ""}
                </option>
              ))}
            </SelectField>
          ))}
          <Button disabled={busy === key || !eligible || left === right}>
            {busy === key ? "正在对比…" : "开始对比"}
          </Button>
        </FieldGroup>
      </form>
      {unavailable && (
        <Alert>
          <AlertTitle>
            {currentFailure.code === "evidence_expired"
              ? "证据已过期"
              : "报告尚未发布"}
          </AlertTitle>
          <AlertDescription>
            {currentFailure.code === "evidence_expired"
              ? "保留期结束，无法对比已过期的报告。"
              : currentFailure.code === "audit_incomplete"
                ? "审计未完成或异常，当前报告不可对比。"
                : "运行结束且审计完成后才能获取报告；必要条件已满足时，报告仍可能等待发布，请稍后重试。"}
            <p>{currentFailure.message}</p>
          </AlertDescription>
        </Alert>
      )}
      {result?.key === key && <ComparisonResult value={result.value} />}
    </>
  );
}

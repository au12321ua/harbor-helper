import { api, post, type Comparison } from "@/api";
import { ErrorNotice, Loading, SelectField, Title } from "@/components/shared";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { labels } from "@/presentation";
import { useState } from "react";
export function ComparisonResult({ value }: { value: Comparison }) {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        {(["left", "right"] as const).map((side) => {
          const input = value.attachment_inputs?.[side];
          const digest = input?.digest || value.bundle_change?.[side];
          return (
            <p key={side} className="break-all">
              实验 {side === "left" ? "A" : "B"} 附件：
              {input?.attachment_version_id
                ? `${input.attachment_version_id} · ${digest || "摘要未知"}`
                : "无附件"}
            </p>
          );
        })}
        <p className="text-muted-foreground">
          附件差异是本次实验因素；可比性仍检查任务、评分、基础agent/模型及其他固定条件。
        </p>
      </div>
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
            {value.tasks.flatMap((task) =>
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

export function Compare() {
  const { data, error, loading } = useLoad(() => api("/runs"));
  const [left, setLeft] = useState(""),
    [right, setRight] = useState(""),
    [result, setResult] = useState<Comparison>(),
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
                {(data?.runs || []).map((r) => (
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
                {(data?.runs || []).map((r) => (
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

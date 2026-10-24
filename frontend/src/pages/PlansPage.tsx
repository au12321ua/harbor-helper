// Experiment plans (04 section 1): saved configurations the team shares. The creator edits;
// others copy to change; the creator or an administrator archives or deletes.
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyNote, ErrorAlert, Loading, PageTitle, Pill, TextField } from "@/components/common";
import { ApiError, api } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { useLoad } from "@/lib/hooks";
import type { Plan, PlanTemplate } from "@/lib/types";

const FIELD_NAME: Record<string, string> = {
  dataset_version_id: "数据集版本",
  task_selection: "任务范围",
  execution_mode: "执行方式",
  model_config_id: "模型",
  model_revision: "模型修订",
  harness_version_id: "Harness",
  harness_params: "Harness 参数",
  attachments: "附件",
  repetitions: "重复次数",
  concurrency: "并发",
  run_deadline_hours: "总时限",
  resources: "资源",
  timeouts: "时限",
  parameters: "作者参数",
};

function Editor({ plan, onDone }: { plan: Plan; onDone: () => void }) {
  const [name, setName] = useState(plan.name);
  const [description, setDescription] = useState(plan.description);
  const [template, setTemplate] = useState(JSON.stringify(plan.template, null, 2));
  const [error, setError] = useState<unknown>();
  const save = async () => {
    setError(undefined);
    try {
      let parsed: unknown;
      try {
        parsed = JSON.parse(template);
      } catch {
        throw new Error("配置不是合法的 JSON");
      }
      await api.put("/plans/{plan_id}", {
        path: { plan_id: plan.id },
        body: {
          expected_revision: plan.revision,
          name,
          description,
          template: parsed as PlanTemplate,
        },
      });
      toast.success("已保存为新修订；已经用过旧修订的运行不受影响");
      onDone();
    } catch (err) {
      setError(err);
    }
  };
  const fieldErrors = error instanceof ApiError ? error.body.field_errors : [];
  return (
    <div className="grid gap-2">
      <TextField id={`plan-${plan.id}-name`} label="名称" value={name} onChange={(e) => setName(e.target.value)} />
      <TextField
        id={`plan-${plan.id}-description`}
        label="说明"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <label className="grid gap-1 text-sm">
        配置（JSON，字段同新建运行的请求，都可省略）
        <textarea
          className="min-h-48 rounded-md border bg-background p-2 font-mono text-xs"
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
        />
      </label>
      <ErrorAlert error={error} title="保存失败" />
      {fieldErrors.length > 0 && (
        <ul className="font-mono text-xs text-destructive">
          {fieldErrors.map((e, i) => (
            <li key={i}>
              {e.path} · {e.code}
              {e.message ? ` · ${e.message}` : ""}
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <Button size="sm" onClick={() => void save()}>
          保存
        </Button>
        <Button size="sm" variant="outline" onClick={onDone}>
          取消
        </Button>
      </div>
    </div>
  );
}

export function PlansPage() {
  const [archived, setArchived] = useState(false);
  const list = useLoad(
    async () => (await api.get("/plans", { query: { include_archived: archived } })).data,
    [archived],
  );
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<unknown>();
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setError(undefined);
    try {
      await fn();
      toast.success(done);
      await list.reload();
    } catch (err) {
      setError(err);
    }
  };

  return (
    <div className="grid gap-4">
      <PageTitle title="实验方案">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={archived}
            onChange={(e) => setArchived(e.target.checked)}
          />
          显示已归档
        </label>
      </PageTitle>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">团队的方案</CardTitle>
          <CardDescription>
            方案是一组保存下来的运行配置，在“新建运行”页选用或另存。每次修改都是新修订，用过旧修订的运行保持原值。只有创建者能修改，其他人可以复制后再改；归档后不能再选用，已有运行不受影响。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm">
          {list.loading && !list.data && <Loading />}
          <ErrorAlert error={list.error ?? error} />
          {list.data && list.data.length === 0 && (
            <EmptyNote>还没有方案。在“新建运行”页填好配置后可以另存为方案。</EmptyNote>
          )}
          {list.data && list.data.length > 0 && (
            <div className="overflow-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>名称</TableHead>
                    <TableHead>创建者</TableHead>
                    <TableHead>包含的设置</TableHead>
                    <TableHead>修订</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {list.data.map((plan) => (
                    <TableRow key={plan.id}>
                      <TableCell>
                        <span className="font-medium">{plan.name}</span>
                        {plan.archived_at && (
                          <span className="ml-2">
                            <Pill tone="muted">已归档</Pill>
                          </span>
                        )}
                        {plan.description && (
                          <div className="text-xs text-muted-foreground">{plan.description}</div>
                        )}
                        {editing === plan.id && (
                          <div className="mt-2">
                            <Editor
                              plan={plan}
                              onDone={() => {
                                setEditing(null);
                                void list.reload();
                              }}
                            />
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="text-xs">{plan.owner_username}</TableCell>
                      <TableCell className="text-xs">
                        {Object.keys(plan.template)
                          .map((k) => FIELD_NAME[k] ?? k)
                          .join("、") || "—"}
                      </TableCell>
                      <TableCell className="text-xs">
                        {plan.revision}
                        <div className="text-muted-foreground">{fmtTime(plan.updated_at)}</div>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right">
                        {plan.allowed_actions.includes("use") && (
                          <Button asChild size="sm" variant="outline">
                            <Link to={`/runs/new?plan=${plan.id}`}>用它新建运行</Link>
                          </Button>
                        )}{" "}
                        {plan.allowed_actions.includes("edit") && (
                          <Button size="sm" variant="outline" onClick={() => setEditing(plan.id)}>
                            修改
                          </Button>
                        )}{" "}
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            void act(
                              () =>
                                api.post("/plans/{plan_id}/copy", {
                                  path: { plan_id: plan.id },
                                  body: {},
                                }),
                              "已复制为你的方案",
                            )
                          }
                        >
                          复制
                        </Button>{" "}
                        {plan.allowed_actions.includes("archive") && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              void act(
                                () =>
                                  api.post("/plans/{plan_id}/archive", {
                                    path: { plan_id: plan.id },
                                    body: {
                                      archived: plan.archived_at == null,
                                    },
                                  }),
                                plan.archived_at == null ? "已归档" : "已取消归档",
                              )
                            }
                          >
                            {plan.archived_at == null ? "归档" : "取消归档"}
                          </Button>
                        )}{" "}
                        {plan.allowed_actions.includes("delete") && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              void act(
                                () => api.del("/plans/{plan_id}", { path: { plan_id: plan.id } }),
                                "已移入回收站",
                              )
                            }
                          >
                            删除
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

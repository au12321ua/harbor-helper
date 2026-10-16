import { date } from "@/presentation";
import { AdminForm } from "./AdminForm";

import { mutation, type CatalogDataset, type Docker } from "@/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { useState } from "react";
export function AuthorInputs({
  dataset,
  save,
  check,
  docker,
}: {
  dataset: CatalogDataset;
  save: typeof mutation;
  check: (
    path: `/admin/datasets/${string}/author-inputs/check`,
    value?: { task_names: string[] },
  ) => void;
  docker?: Docker;
}) {
  const [taskNames, setTaskNames] = useState<string[]>([]);
  const parameters = dataset.author_parameters;
  const variables = parameters.discovery?.variables || {};
  return (
    <div className="flex flex-col gap-3">
      <p>
        作者运行参数 · v{parameters.version || 0} ·{" "}
        {parameters.status === "checked"
          ? "运行参数已检查"
          : parameters.status?.startsWith("partial_")
            ? "部分任务已检查（不代表全集就绪）"
            : parameters.status === "blocked"
              ? "检查失败"
              : parameters.status === "missing"
                ? "缺配置"
                : "尚未检查"}
        {parameters.checked ? ` · ${date(parameters.checked)}` : ""}
      </p>
      <p className="text-sm text-muted-foreground">
        仅非秘密：值进入任务快照、Job与报告，agent可见。此检查只检查输入，不证明构建、评分或模型可用。保存参数不改变来源验证。
      </p>
      {parameters.source ? (
        <p className="break-all text-sm">检查来源：{parameters.source}</p>
      ) : null}
      <Button
        variant="outline"
        disabled={!dataset.ready}
        onClick={() =>
          check(`/admin/datasets/${dataset.id}/author-inputs/check`)
        }
      >
        检查作者参数
      </Button>
      <Field>
        <FieldLabel htmlFor={`check-tasks-${dataset.id}`}>
          检查任务（可多选）
        </FieldLabel>
        <select
          id={`check-tasks-${dataset.id}`}
          multiple
          value={taskNames}
          onChange={(e) =>
            setTaskNames(
              Array.from(e.target.selectedOptions, (option) => option.value),
            )
          }
        >
          {(dataset.tasks || []).map((task) => (
            <option key={task.name} value={task.name}>
              {task.name}
            </option>
          ))}
        </select>
        <FieldDescription>
          选定检查只下载所选任务；未选任务仍未知。上方按钮保留全部任务检查。
        </FieldDescription>
      </Field>
      <Button
        variant="outline"
        disabled={!dataset.ready || !taskNames.length}
        onClick={() =>
          check(`/admin/datasets/${dataset.id}/author-inputs/check`, {
            task_names: taskNames,
          })
        }
      >
        检查选定任务
      </Button>
      {parameters.scope ? (
        <p>
          检查范围：{parameters.scope.complete ? "全集" : "部分任务"} · 已扫描{" "}
          {parameters.scope.tasks.length}/{parameters.scope.total} · 另有{" "}
          {parameters.scope.unknown} 个任务未扫描
        </p>
      ) : null}
      {parameters.issues?.map((issue, index: number) => (
        <Alert key={index} variant="destructive">
          <AlertDescription>
            {issue.task}：{(issue.variables || []).join("、")} ·{" "}
            {issue.reason === "host_template_unsupported"
              ? "宿主模板暂不支持网页赋值"
              : issue.reason}
          </AlertDescription>
        </Alert>
      ))}
      {parameters.discovery?.images?.map((image, index: number) => (
        <p key={index}>
          {image.task} / {image.role}：作者预构建镜像 {image.reference} ·{" "}
          {image.cached === true
            ? "本机已缓存（不证明兼容）"
            : image.cached === false
              ? "本机未缓存；Harbor会向registry获取，检查部署出网与启动阶段"
              : "本机缓存状态未知"}
          。该提示不阻止提交，不修改作者网络。
        </p>
      ))}
      {parameters.discovery ? (
        <>
          {Object.keys(variables).length ? (
            <AdminForm
              key={`${dataset.id}-${parameters.version}`}
              title="作者运行参数"
              description="字段来自已校验作者Compose。留空沿作者默认，必需项留空将阻止受理准备。两侧镜像分别消费各自字段；Oracle可检查作者环境与评分。"
              resetOnSave={false}
              fields={Object.entries(variables).flatMap(([name, raw]) => {
                const uses = raw;
                const imageOptions = (docker?.images || []).flatMap((image) =>
                  (image.reference ? [image.reference] : [])
                    .filter((tag: string) => tag !== "<none>:<none>")
                    .map((tag: string) => ({ value: tag, label: tag })),
                );
                return [
                  ...(name.includes("IMAGE") && imageOptions.length
                    ? [
                        {
                          name: `${name}-inventory`,
                          label: `${name} · 本机镜像（可选）`,
                          required: false,
                          options: imageOptions,
                          copyTo: name,
                        },
                      ]
                    : []),
                  {
                    name,
                    label: name,
                    required: false,
                    defaultValue: parameters.values?.[name] || "",
                    description: uses
                      .map(
                        (use) =>
                          `${use.task} / ${use.file}：${use.required ? "必需" : `可选，作者默认 ${use.default || "空"}`}`,
                      )
                      .join("；"),
                  },
                ];
              })}
              onSave={async (value) => {
                const values = Object.fromEntries(
                  Object.keys(variables)
                    .filter((name) => value[name])
                    .map((name) => [name, value[name]]),
                );
                return save(
                  `/admin/datasets/${dataset.id}/author-inputs`,
                  { values },
                  "PUT",
                );
              }}
            />
          ) : (
            <p>
              已扫描任务没有可网页配置的外部Compose变量；其余任务仍需执行前完整校验。
            </p>
          )}
          <p>
            作者预算：
            {parameters.discovery.budgets
              ?.map(
                (budget) =>
                  `${budget.task}：agent ${budget.agent_seconds}秒 + verifier ${budget.verifier_seconds}秒`,
              )
              .join("；")}
            。预算估算仅单task，重复尝试/多任务另需余量；总时长还需包含环境与工具准备。
          </p>
        </>
      ) : null}
    </div>
  );
}

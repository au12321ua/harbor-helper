import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { runDatasetOperation, useDatasetOperations } from "./datasetOperations";
import { type CatalogDataset, type Dataset } from "@/api";
import { ErrorNotice } from "@/components/shared";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { TabsContent } from "@/components/ui/tabs";
import { AdminForm } from "@/features/admin/AdminForm";
import { AuthorInputs } from "@/features/admin/AuthorInputs";
import { date } from "@/presentation";
import { useState } from "react";
import type { AdminPanelProps } from "./types";
import type { useDockerDiagnostics } from "./useDockerDiagnostics";

export function DatasetsPanel({
  c,
  save,
  action,
  diagnostics,
  refresh,
}: AdminPanelProps & {
  diagnostics: ReturnType<typeof useDockerDiagnostics>;
  refresh: () => Promise<void>;
}) {
  const operations = useDatasetOperations();
  const active = Object.values(operations).find((op) => op.running);
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [resets, setResets] = useState<Record<string, number>>({});
  const [sourceDirty, setSourceDirty] = useState(false);
  function start(
    v: CatalogDataset,
    kind: "verify" | "check",
    tasks?: string[],
  ) {
    if (dirty[v.id] || (edit.dataset?.id === v.id && sourceDirty)) return;
    void runDatasetOperation(v.id, v.name, kind, tasks);
  }
  const [edit, setEdit] = useState<{ dataset?: Dataset }>({});
  const selectedDataset = c.datasets.find(
    (dataset) => dataset.id === edit.dataset?.id,
  );
  const { docker, dockerBusy, dockerError, discoverDocker } = diagnostics;
  function catalogList(kind: "dataset", values: CatalogDataset[]) {
    return (
      <div className="flex flex-col gap-4">
        {values.map((v) => (
          <Card key={v.id}>
            <CardHeader>
              <CardTitle>{v.name}</CardTitle>
              <CardDescription>
                {kind === "dataset" ? v.reference : ""}
              </CardDescription>
              <div className="flex flex-wrap gap-2">
                <Badge variant="secondary">
                  {v.status === "verified"
                    ? "来源已验证"
                    : v.status === "blocked"
                      ? "存在阻碍"
                      : "尚未验证"}
                </Badge>
                <Badge variant="outline">{v.enabled ? "启用" : "停用"}</Badge>
                {c.settings.default_dataset_id === v.id && (
                  <Badge variant="outline">默认数据集</Badge>
                )}
              </div>
              {v.checked != null && (
                <p className="text-sm text-muted-foreground">
                  来源验证：{date(v.checked)}
                </p>
              )}
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {kind === "dataset" ? (
                <>
                  <p>
                    来源验证与运行输入分别检查；环境由Harbor按作者定义运行。
                  </p>
                  <p role="status">{operations[v.id]?.message}</p>
                  {active && (
                    <p className="text-sm text-muted-foreground">
                      当前网页正在进行 {active.label}
                      ；其它检查/验证暂不可启动，同数据集冲突编辑暂不可提交。
                    </p>
                  )}
                  {dirty[v.id] || (edit.dataset?.id === v.id && sourceDirty) ? (
                    <div role="status" className="flex flex-col gap-2">
                      <p>
                        本数据集有未保存草稿。请先保存，或明确放弃后再检查/验证。
                      </p>
                      <Button
                        variant="outline"
                        onClick={() => {
                          if (
                            !window.confirm(
                              "放弃本数据集未保存的作者参数和来源草稿？",
                            )
                          )
                            return;
                          setResets((r) => ({
                            ...r,
                            [v.id]: (r[v.id] || 0) + 1,
                          }));
                          setDirty((d) => ({ ...d, [v.id]: false }));
                          if (edit.dataset?.id === v.id) {
                            setEdit({});
                            setSourceDirty(false);
                          }
                        }}
                      >
                        放弃此数据集草稿
                      </Button>
                    </div>
                  ) : null}
                  <AuthorInputs
                    key={`${v.id}-${resets[v.id] || 0}`}
                    dataset={v}
                    save={save}
                    onDirty={(value) =>
                      setDirty((d) => ({ ...d, [v.id]: value }))
                    }
                    locked={active?.datasetId === v.id}
                    cannotCheck={
                      !!active ||
                      !!dirty[v.id] ||
                      (edit.dataset?.id === v.id && sourceDirty)
                    }
                    check={(tasks) => start(v, "check", tasks)}
                    docker={docker}
                  />
                </>
              ) : null}

              {v.error || v.readiness_error ? (
                <Alert variant="destructive">
                  <AlertDescription>
                    {(v.error || v.readiness_error)?.message}
                  </AlertDescription>
                </Alert>
              ) : null}
              <details className="raw-details">
                <summary>来源详情与内部配置修订</summary>
                <p className="break-all">{v.resolved || "不可变来源未知"}</p>
                <p>
                  配置修订：{v.version} · 参数修订：
                  {v.author_parameters.version}
                </p>
              </details>
              <Button variant="ghost" onClick={() => void refresh()}>
                刷新最近已保存结果
              </Button>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  disabled={active?.datasetId === v.id}
                  onClick={() => {
                    setEdit({ ...edit, [kind]: v });
                  }}
                >
                  编辑
                </Button>
                <Button asChild variant="outline"><Link to="/management">选择并导入来源版本</Link></Button>
                <Button
                  disabled={
                    !!active ||
                    !!dirty[v.id] ||
                    (edit.dataset?.id === v.id && sourceDirty)
                  }
                  onClick={() => start(v, "verify")}
                >
                  验证
                </Button>
                {kind === "dataset" && v.ready ? (
                  <Button
                    variant="outline"
                    onClick={() =>
                      void action(
                        "/admin/settings",
                        { default_dataset_id: v.id },
                        "PATCH",
                      )
                    }
                  >
                    {c.settings?.default_dataset_id === v.id
                      ? "当前默认"
                      : "设为默认"}
                  </Button>
                ) : null}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }
  return (
    <TabsContent value="dataset">
      <Button
        variant="outline"
        disabled={dockerBusy}
        onClick={() => void discoverDocker()}
      >
        发现本机镜像供作者参数选择
      </Button>
      <ErrorNotice error={dockerError} />
      <div className="admin-layout">
        {catalogList("dataset", c.datasets || [])}
        <div className="flex flex-col gap-4">
          <AdminForm
            key={edit.dataset?.id || "new"}
            title={`${edit.dataset ? "编辑" : "添加"}数据集`}
            onDirty={setSourceDirty}
            disabled={!!edit.dataset && active?.datasetId === edit.dataset.id}
            description="保存来源，再验证访问和任务清单。无需统一运行镜像；缺少作者依赖时执行会如实失败。"
            fields={[
              {
                name: "name",
                label: "数据集名称",
                defaultValue: selectedDataset?.name,
              },
              {
                name: "reference",
                label: "Hub 来源（owner/name，可指定版本）",
                defaultValue: selectedDataset?.reference,
                description:
                  "例如 harbor/hello-world@1；网页 rev.1 对应 @1。支持 @latest、@标签或完整 @sha256:摘要，省略版本使用 latest。验证解析具体来源，提交实验时冻结。",
              },
              {
                name: "enabled",
                label: "状态",
                defaultValue: String(selectedDataset?.enabled ?? true),
                options: [
                  { value: "true", label: "启用" },
                  { value: "false", label: "停用" },
                ],
              },
            ]}
            onSave={async (v) => {
              const saved = await save("/admin/catalog/dataset", {
                ...v,
                id: edit.dataset?.id,
                enabled: v.enabled === "true",
              });
              setEdit((current) => ({ ...current, dataset: saved }));
            }}
          />
          <Button
            variant="ghost"
            onClick={() => setEdit({ ...edit, dataset: undefined })}
          >
            新建条目
          </Button>
        </div>
      </div>
    </TabsContent>
  );
}

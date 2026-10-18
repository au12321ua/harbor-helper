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
}: AdminPanelProps & { diagnostics: ReturnType<typeof useDockerDiagnostics> }) {
  const [edit, setEdit] = useState<{ dataset?: Dataset }>({});
  const { docker, dockerBusy, dockerError, discoverDocker } = diagnostics;
  function catalogList(kind: "dataset", values: CatalogDataset[]) {
    return (
      <div className="flex flex-col gap-4">
        {values.map((v) => (
          <Card key={v.id}>
            <CardHeader>
              <CardTitle>
                {v.name} · v{v.version}
              </CardTitle>
              <CardDescription>
                {kind === "dataset" ? v.reference : ""}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {kind === "dataset" ? (
                <>
                  <p>
                    来源验证与运行输入分别检查；环境由Harbor按作者定义运行。
                  </p>
                  <AuthorInputs
                    dataset={v}
                    save={save}
                    check={(path, value) => void action(path, value ?? {})}
                    docker={docker}
                  />
                </>
              ) : null}
              <p>
                {v.status === "verified"
                  ? "来源已验证"
                  : v.status === "blocked"
                    ? "存在阻碍"
                    : "尚未验证"}
                {v.checked ? ` · ${date(v.checked)}` : ""} ·{" "}
                {v.enabled ? "启用" : "停用"}
              </p>
              {v.error || v.readiness_error ? (
                <Alert variant="destructive">
                  <AlertDescription>
                    {(v.error || v.readiness_error)?.message}
                  </AlertDescription>
                </Alert>
              ) : null}
              {v.tasks ? (
                <p>任务：{v.tasks.map((t) => t.name).join("、")}</p>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  onClick={() => setEdit({ ...edit, [kind]: v })}
                >
                  编辑
                </Button>
                <Button
                  onClick={() =>
                    void action(`/admin/catalog/${kind}/${v.id}/verify`, {})
                  }
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
            key={JSON.stringify(edit.dataset || {})}
            title={`${edit.dataset ? "编辑" : "添加"}数据集`}
            description="保存来源，再验证访问和任务清单。无需统一运行镜像；缺少作者依赖时执行会如实失败。"
            fields={[
              {
                name: "name",
                label: "数据集名称",
                defaultValue: edit.dataset?.name,
              },
              {
                name: "reference",
                label: "Hub 来源（owner/name，可指定版本）",
                defaultValue: edit.dataset?.reference,
                description:
                  "例如 harbor/hello-world@1；网页 rev.1 对应 @1。支持 @latest、@标签或完整 @sha256:摘要，省略版本使用 latest。验证解析具体来源，提交实验时冻结。",
              },
              {
                name: "enabled",
                label: "状态",
                defaultValue: String(edit.dataset?.enabled ?? true),
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

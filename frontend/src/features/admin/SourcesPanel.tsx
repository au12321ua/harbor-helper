import { ErrorNotice } from "@/components/shared";
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
import { date } from "@/presentation";
import { useState } from "react";
import type { AdminPanelProps } from "./types";

export function SourcesPanel({ c, save }: Pick<AdminPanelProps, "c" | "save">) {
  const [hubNotice, setHubNotice] = useState("");
  const [hubError, setHubError] = useState<unknown>();
  return (
    <TabsContent value="readiness">
      <div className="admin-layout">
        <Card>
          <CardHeader>
            <CardTitle>实验准备检查</CardTitle>
            <CardDescription>
              目录验证代表该次检查可用；实际提交仍重新校验并保留作者任务快照。
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <p>
              已验证可选数据集：
              {(c.datasets || []).filter((v) => v.ready).length}
            </p>
            <p>
              默认数据集：
              {(c.datasets || []).find(
                (v) => v.id === c.settings?.default_dataset_id,
              )?.name || "尚未选择"}
            </p>
            <p>
              Hub 来源：
              {c.hub?.mode === "team"
                ? `团队凭据 v${c.hub.version}`
                : "匿名（仅公开包）"}
            </p>
            <p>
              私有包需有访问权限的团队 Hub PAT；不会读取部署人员 HOME
              登录。缺镜像或 Docker 权限须由部署负责人修复，再回网页验证。
            </p>
            <p>模型配置保存 ≠ 真实认证成功；本页面不会发起付费模型请求。</p>
            <AdminForm
              title="团队名称"
              description="显示给全体成员"
              fields={[
                {
                  name: "team_name",
                  label: "名称",
                  defaultValue: c.settings?.team_name || "团队实验室",
                },
              ]}
              onSave={(v) => save("/admin/settings", v, "PATCH")}
            />
          </CardContent>
        </Card>
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Hub 凭据状态</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              <p>
                凭据：
                {c.hub?.state === "active" || c.hub?.mode === "team"
                  ? "已设置（启用）"
                  : c.hub?.version
                    ? "已停用"
                    : "未设置"}
              </p>
              <p>
                版本：{c.hub?.version ? `v${c.hub.version}` : "无"} · 更新时间：
                {c.hub?.updated_at
                  ? date(c.hub.updated_at)
                  : c.hub?.version
                    ? "旧版本未记录"
                    : "无"}
              </p>
              <p>
                保存仅代表加密持久化，未验证Hub身份或数据集访问权限。访问验证结果请查看数据集条目的验证状态。
              </p>
              {hubNotice ? <p role="status">{hubNotice}</p> : null}
              <ErrorNotice error={hubError} />
            </CardContent>
          </Card>
          <AdminForm
            title="团队 Hub 来源凭据"
            description="只写入并加密保存。输入 Hub PAT，保存后去数据集页面验证权限；轮换后重新验证数据集。PAT 只用于来源准备，不进入执行环境。"
            fields={[{ name: "key", label: "Hub PAT", type: "password" }]}
            onSave={async (v) => {
              setHubNotice("");
              setHubError(undefined);
              await save("/admin/hub", v);
              setHubNotice(
                "Hub PAT已保存，输入已清空；若已有凭据则完成轮换。请另行验证数据集访问。",
              );
            }}
          />
          <Button
            variant="outline"
            disabled={!c.hub?.version || c.hub?.state === "disabled"}
            onClick={async () => {
              setHubNotice("");
              setHubError(undefined);
              try {
                await save("/admin/hub/disable", {});
                setHubNotice(
                  "Hub凭据已停用，当前使用匿名来源；需要权限的数据集须重新配置凭据。",
                );
              } catch (e) {
                setHubError(e);
              }
            }}
          >
            停用 Hub 凭据，改为匿名来源
          </Button>
        </div>
      </div>
    </TabsContent>
  );
}

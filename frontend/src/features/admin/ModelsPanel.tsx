import { type Provider } from "@/api";
import { EmptyState, SelectField } from "@/components/shared";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { ModelForm } from "@/features/admin/ModelForm";
import { useState } from "react";
import type { AdminPanelProps } from "./types";

export function ModelsPanel({ c, save, action }: AdminPanelProps) {
  const [edit, setEdit] = useState<{ provider?: Provider; profile?: string }>(
    {},
  );
  const [rotation, setRotation] = useState("");
  const [providerFilter, setProviderFilter] = useState("");
  const [keyFilter, setKeyFilter] = useState("");
  const visibleProviders = (c.providers || []).filter(
    (p) => !providerFilter || p.id === providerFilter,
  );
  const visibleKeys = (c.credentials || []).filter(
    (k) =>
      (!providerFilter || k.provider_id === providerFilter) &&
      (!keyFilter || k.id === keyFilter),
  );
  const visibleProfiles = (c.model_profiles || []).filter(
    (p) =>
      (!providerFilter || p.provider_id === providerFilter) &&
      (!keyFilter || p.credential_id === keyFilter),
  );
  // Keep only the selection ID; refreshed catalog versions supply edit defaults.
  const selectedProfile = (c.model_profiles || []).find(
    (p) => p.id === edit.profile,
  );

  return (
    <TabsContent value="models">
      <div className="flex flex-col gap-6">
        <Alert>
          <AlertTitle>明确绑定、版本化配置</AlertTitle>
          <AlertDescription>
            提供商 → 团队 key →
            模型方案。内部标识自动生成。密钥只写入；轮换保持同一 key
            的绑定，停用阻止新执行。
          </AlertDescription>
        </Alert>
        <Card>
          <CardHeader>
            <CardTitle>浏览配置列表</CardTitle>
            <CardDescription>
              以下条件只缩小左侧列表；右侧新建或编辑表单中的提供商与团队 key
              决定保存绑定。筛选不会修改表单或已有配置。
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex flex-wrap gap-4">
              <SelectField
                label="列表范围：提供商"
                name="filter-provider"
                value={providerFilter}
                onChange={(v) => {
                  setProviderFilter(v);
                  setKeyFilter("");
                }}
              >
                <option value="">全部提供商</option>
                {(c.providers || []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {String(p.name || p.id)}
                  </option>
                ))}
              </SelectField>
              <SelectField
                label="列表范围：团队 key"
                name="filter-key"
                value={keyFilter}
                onChange={setKeyFilter}
              >
                <option value="">全部key</option>
                {(c.credentials || [])
                  .filter(
                    (k) => !providerFilter || k.provider_id === providerFilter,
                  )
                  .map((k) => (
                    <option key={k.id} value={k.id}>
                      {String(
                        (c.providers || []).find((p) => p.id === k.provider_id)
                          ?.name || "",
                      )}{" "}
                      → {k.label}
                    </option>
                  ))}
              </SelectField>
              <Button
                variant="outline"
                onClick={() => {
                  setProviderFilter("");
                  setKeyFilter("");
                }}
              >
                显示全部配置
              </Button>
            </div>
            <p>
              当前列表：{visibleProviders.length} 个提供商、
              {visibleKeys.length} 个团队 key、{visibleProfiles.length}{" "}
              个模型方案。提供商条件作用于三种列表；key 条件只作用于 key
              与模型方案。
            </p>
          </CardContent>
        </Card>
        <div className="admin-layout">
          <div className="flex flex-col gap-4">
            <h2>提供商列表</h2>
            {!visibleProviders.length ? (
              <EmptyState
                title="此范围暂无提供商"
                description="显示全部配置或在右侧新建提供商。"
              />
            ) : null}
            {visibleProviders.map((p) => (
              <Card key={p.id}>
                <CardHeader>
                  <CardTitle>{String(p.name || p.id)}</CardTitle>
                  <CardDescription>
                    {p.endpoint} · {p.enabled ? "启用" : "停用"} ·{" "}
                    {
                      (c.credentials || []).filter(
                        (k) => k.provider_id === p.id,
                      ).length
                    }
                    个key ·{" "}
                    {
                      (c.model_profiles || []).filter(
                        (m) => m.provider_id === p.id,
                      ).length
                    }
                    个方案
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex gap-2">
                  <Button
                    variant="outline"
                    onClick={() => setEdit({ ...edit, provider: p })}
                  >
                    编辑提供商
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() =>
                      void action("/admin/providers", {
                        ...p,
                        enabled: !p.enabled,
                      })
                    }
                  >
                    {p.enabled ? "停用" : "启用"}
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
          <div className="flex flex-col gap-3">
            <p>
              {edit.provider
                ? `正在编辑：${edit.provider.name}`
                : "正在新建提供商"}
              ；每个提供商可有多个key，每个key可有多个方案。
            </p>
            <Button
              variant="outline"
              onClick={() =>
                setEdit((current) => ({
                  ...current,
                  provider: undefined,
                }))
              }
            >
              新建提供商
            </Button>
            <AdminForm
              key={JSON.stringify(edit.provider || {})}
              title="提供商配置"
              description="OpenAI-compatible HTTP API；已有实验保留提交时的端点。"
              fields={[
                {
                  name: "name",
                  label: "提供商名称",
                  defaultValue: String(edit.provider?.name || ""),
                },
                {
                  name: "endpoint",
                  label: "API 端点",
                  type: "url",
                  defaultValue: edit.provider?.endpoint,
                },
              ]}
              onSave={async (v) => {
                const saved = await save("/admin/providers", {
                  ...v,
                  id: edit.provider?.id,
                  protocol: "openai-compatible",
                  enabled: edit.provider?.enabled ?? true,
                });
                setEdit((current) => ({ ...current, provider: saved }));
              }}
            />
          </div>
        </div>
        <div className="admin-layout">
          <div className="flex flex-col gap-3">
            <h2>团队 key 列表</h2>
            {!visibleKeys.length ? (
              <EmptyState
                title="此范围暂无团队 key"
                description="调整列表范围；添加时在右侧明确选择所属提供商。"
              />
            ) : null}
            {visibleKeys.map((key) => (
              <Card key={key.id}>
                <CardHeader>
                  <CardTitle>
                    {key.label} · v{key.version}
                  </CardTitle>
                  <CardDescription>
                    {String(
                      (c.providers || []).find((p) => p.id === key.provider_id)
                        ?.name || "",
                    )}{" "}
                    · {key.enabled ? "启用" : "停用"} ·{" "}
                    {
                      (c.model_profiles || []).filter(
                        (m) => m.credential_id === key.id,
                      ).length
                    }
                    个方案
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex gap-2">
                  <Button variant="outline" onClick={() => setRotation(key.id)}>
                    轮换
                  </Button>
                  <Button
                    variant="outline"
                    disabled={!key.enabled}
                    onClick={() =>
                      void action(`/admin/credentials/${key.id}/disable`, {})
                    }
                  >
                    停用
                  </Button>
                </CardContent>
              </Card>
            ))}
            {rotation ? (
              <AdminForm
                key={rotation}
                title="轮换团队 key"
                description={`正在轮换：${(c.credentials || []).find((k) => k.id === rotation)?.label || rotation}。旧版本继续供已绑定运行与审计使用。`}
                fields={[{ name: "key", label: "新密钥", type: "password" }]}
                onSave={async (v) => {
                  await save(`/admin/credentials/${rotation}/rotate`, v);
                  setRotation("");
                }}
              />
            ) : null}
          </div>
          <AdminForm
            title="添加团队 key"
            description="每个提供商可新增多个key。绑定保持不变；轮换或停用已有key，方案可编辑或新增。密钥加密保存，不回显、不保存在浏览器。"
            fields={[
              { name: "label", label: "Key 名称" },
              {
                name: "provider_id",
                label: "提供商",
                options: (c.providers || []).map((p) => ({
                  value: p.id,
                  label: String(p.name || p.id),
                })),
              },
              { name: "key", label: "密钥", type: "password" },
            ]}
            onSave={(v) => save("/admin/credentials", v)}
          />
        </div>
        <div className="admin-layout">
          <div className="flex flex-col gap-4">
            <h2>模型方案列表</h2>
            {!visibleProfiles.length ? (
              <EmptyState
                title="此范围暂无模型方案"
                description="调整列表范围或新建模型方案；保存绑定在右侧编辑。"
              />
            ) : null}
            {visibleProfiles.map((p) => (
              <Card key={p.id}>
                <CardHeader>
                  <CardTitle>
                    {String(p.name || p.id)} · {p.model}
                  </CardTitle>
                  <CardDescription>
                    {String(
                      (c.providers || []).find(
                        (provider) => provider.id === p.provider_id,
                      )?.name || "",
                    )}{" "}
                    →{" "}
                    {
                      (c.credentials || []).find(
                        (k) => k.id === p.credential_id,
                      )?.label
                    }{" "}
                    · v{p.version} · {p.enabled ? "启用" : "停用"}
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    onClick={() => setEdit({ ...edit, profile: p.id })}
                  >
                    编辑方案
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() =>
                      void action("/admin/model-profiles", {
                        ...p,
                        enabled: !p.enabled,
                      })
                    }
                  >
                    {p.enabled ? "停用" : "启用"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() =>
                      void action(
                        "/admin/settings",
                        { default_model_profile: p.id },
                        "PATCH",
                      )
                    }
                  >
                    设为默认模型
                  </Button>
                </CardContent>
              </Card>
            ))}
            <Button
              variant="ghost"
              onClick={() => setEdit({ ...edit, profile: undefined })}
            >
              新建模型方案
            </Button>
          </div>
          <ModelForm
            key={JSON.stringify(selectedProfile || {})}
            catalog={c}
            selected={selectedProfile}
            save={save}
            onSaved={(saved) =>
              setEdit((current) => ({ ...current, profile: saved.id }))
            }
          />
        </div>
      </div>
    </TabsContent>
  );
}

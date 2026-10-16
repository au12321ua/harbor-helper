import { type Provider } from "@/api";
import { EmptyState, SelectField } from "@/components/shared";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
  const visibleProviders = c.providers.filter(
    (p) => !providerFilter || p.id === providerFilter,
  );
  const visibleKeys = c.credentials.filter(
    (k) =>
      (!providerFilter || k.provider_id === providerFilter) &&
      (!keyFilter || k.id === keyFilter),
  );
  const visibleProfiles = c.model_profiles.filter(
    (p) =>
      (!providerFilter || p.provider_id === providerFilter) &&
      (!keyFilter || p.credential_id === keyFilter),
  );
  const selectedProfile = c.model_profiles.find((p) => p.id === edit.profile);
  const providerName = (id: string) =>
    c.providers.find((p) => p.id === id)?.name || id;
  return (
    <TabsContent value="models">
      <div className="models-workspace">
        <div className="section-bar">
          <h2>模型方案</h2>
          <Button
            variant="outline"
            onClick={() => setEdit({ ...edit, profile: undefined })}
          >
            新建模型方案
          </Button>
        </div>
        <p className="quiet-note">
          模型方案明确绑定提供商与团队凭据。密钥值不会返回浏览器。
        </p>
        <div className="model-filters">
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
            {c.providers.map((p) => (
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
            {c.credentials
              .filter(
                (k) => !providerFilter || k.provider_id === providerFilter,
              )
              .map((k) => (
                <option key={k.id} value={k.id}>
                  {String(providerName(k.provider_id))} → {k.label}
                </option>
              ))}
          </SelectField>
          <Button
            variant="ghost"
            onClick={() => {
              setProviderFilter("");
              setKeyFilter("");
            }}
          >
            显示全部配置
          </Button>
        </div>
        <p className="quiet-note">
          列表范围只缩小配置列表，不修改新建或编辑表单的提供商与团队 key 绑定。
        </p>
        <div className="table-shell">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>方案</TableHead>
                <TableHead>提供商 / 模型</TableHead>
                <TableHead>凭据绑定</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleProfiles.map((p) => (
                <TableRow key={p.id}>
                  <TableCell>
                    <span className="mono">{String(p.name || p.id)}</span>
                    <small className="cell-secondary">
                      {p.id} · v{p.version}
                    </small>
                  </TableCell>
                  <TableCell className="mono">
                    {String(providerName(String(p.provider_id)))} / {p.model}
                  </TableCell>
                  <TableCell>
                    {c.credentials.find((k) => k.id === p.credential_id)
                      ?.label || "—"}
                  </TableCell>
                  <TableCell>
                    <span
                      className={p.enabled ? "enabled-state" : "quiet-note"}
                    >
                      {p.enabled ? "启用" : "停用"}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="button-row">
                      <Button
                        variant="ghost"
                        onClick={() => setEdit({ ...edit, profile: p.id })}
                      >
                        编辑方案
                      </Button>
                      <Button
                        variant="ghost"
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
                        variant="ghost"
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
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {!visibleProfiles.length && (
            <EmptyState
              title="此范围暂无模型方案"
              description="调整列表范围或新建模型方案；保存绑定在编辑表单中选择。"
            />
          )}
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
        <section className="configuration-section">
          <div className="section-bar">
            <h2>提供商列表</h2>
            <Button
              variant="outline"
              onClick={() =>
                setEdit((current) => ({ ...current, provider: undefined }))
              }
            >
              新建提供商
            </Button>
          </div>
          <p className="quiet-note">
            每个提供商可有多个key，每个key可有多个方案。
          </p>
          <div className="table-shell">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>提供商</TableHead>
                  <TableHead>API 端点</TableHead>
                  <TableHead>绑定与状态</TableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleProviders.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-semibold">
                      {String(p.name || p.id)}
                    </TableCell>
                    <TableCell className="mono">{p.endpoint}</TableCell>
                    <TableCell>
                      {p.enabled ? "启用" : "停用"} ·{" "}
                      {
                        c.credentials.filter((k) => k.provider_id === p.id)
                          .length
                      }{" "}
                      个key ·{" "}
                      {
                        c.model_profiles.filter((m) => m.provider_id === p.id)
                          .length
                      }{" "}
                      个方案
                    </TableCell>
                    <TableCell>
                      <div className="button-row">
                        <Button
                          variant="ghost"
                          onClick={() => setEdit({ ...edit, provider: p })}
                        >
                          编辑提供商
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() =>
                            void action("/admin/providers", {
                              ...p,
                              enabled: !p.enabled,
                            })
                          }
                        >
                          {p.enabled ? "停用" : "启用"}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <p className="quiet-note">
            {edit.provider
              ? `正在编辑：${edit.provider.name}`
              : "正在新建提供商"}
          </p>
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
        </section>
        <section className="configuration-section">
          <h2>团队 key 列表</h2>
          <Alert>
            <AlertTitle>明确绑定、版本化配置</AlertTitle>
            <AlertDescription>
              提供商 → 团队 key →
              模型方案。内部标识自动生成。密钥只写入；轮换保持同一 key
              的绑定，停用阻止新执行。
            </AlertDescription>
          </Alert>
          <div className="table-shell">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>团队 key</TableHead>
                  <TableHead>提供商</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleKeys.map((key) => (
                  <TableRow key={key.id}>
                    <TableCell>
                      {key.label} · v{key.version}
                    </TableCell>
                    <TableCell>
                      {String(providerName(key.provider_id))}
                    </TableCell>
                    <TableCell>
                      {key.enabled ? "启用" : "停用"} ·{" "}
                      {
                        c.model_profiles.filter(
                          (m) => m.credential_id === key.id,
                        ).length
                      }{" "}
                      个方案
                    </TableCell>
                    <TableCell>
                      <div className="button-row">
                        <Button
                          variant="ghost"
                          onClick={() => setRotation(key.id)}
                        >
                          轮换
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={!key.enabled}
                          onClick={() =>
                            void action(
                              `/admin/credentials/${key.id}/disable`,
                              {},
                            )
                          }
                        >
                          停用
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {!visibleKeys.length && (
              <EmptyState
                title="此范围暂无团队 key"
                description="调整列表范围；添加时明确选择所属提供商。"
              />
            )}
          </div>
          {rotation && (
            <AdminForm
              key={rotation}
              title="轮换团队 key"
              description={`正在轮换：${c.credentials.find((k) => k.id === rotation)?.label || rotation}。旧版本继续供已绑定运行与审计使用。`}
              fields={[{ name: "key", label: "新密钥", type: "password" }]}
              onSave={async (v) => {
                await save(`/admin/credentials/${rotation}/rotate`, v);
                setRotation("");
              }}
            />
          )}
          <AdminForm
            title="添加团队 key"
            description="每个提供商可新增多个key。绑定保持不变；轮换或停用已有key，方案可编辑或新增。密钥加密保存，不回显、不保存在浏览器。"
            fields={[
              { name: "label", label: "Key 名称" },
              {
                name: "provider_id",
                label: "提供商",
                options: c.providers.map((p) => ({
                  value: p.id,
                  label: String(p.name || p.id),
                })),
              },
              { name: "key", label: "密钥", type: "password" },
            ]}
            onSave={(v) => save("/admin/credentials", v)}
          />
        </section>
      </div>
    </TabsContent>
  );
}

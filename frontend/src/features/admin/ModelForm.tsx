function isJsonMapping(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
import { mutation, type Catalog, type Profile } from "@/api";
import { SelectField } from "@/components/shared";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useState } from "react";
import { AdminForm } from "./AdminForm";
export function ModelForm({
  catalog,
  selected,
  save,
  onSaved,
}: {
  catalog: Catalog;
  selected?: Profile;
  save: typeof mutation;
  onSaved: (value: Profile) => void;
}) {
  const [provider, setProvider] = useState(String(selected?.provider_id || ""));
  const credentials = (catalog.credentials || []).filter(
    (c) => c.provider_id === provider && c.enabled,
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{selected ? "编辑模型方案" : "添加模型方案"}</CardTitle>
        <CardDescription>
          按名称绑定提供商与团队
          key。保存只检查配置与可解密性，不代表真实认证或推理成功。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <SelectField
          label="提供商"
          name="model-provider"
          value={provider}
          onChange={setProvider}
        >
          <option value="">选择提供商</option>
          {(catalog.providers || []).map((p) => (
            <option key={p.id} value={p.id}>
              {String(p.name || p.id)}
            </option>
          ))}
        </SelectField>
        {provider && !credentials.length ? (
          <Alert>
            <AlertDescription>
              该提供商暂无启用的团队 key，请先添加或启用凭据再保存方案。
            </AlertDescription>
          </Alert>
        ) : null}
        <AdminForm
          key={`${selected?.id || "new"}-${provider}`}
          resetOnSave={!selected}
          title="模型配置"
          description="常用参数可留空；JSON 高级参数与常用参数合并。已有实验保留旧版本。"
          fields={[
            {
              name: "name",
              label: "方案名称",
              defaultValue: String(selected?.name || ""),
            },
            {
              name: "credential_id",
              label: "团队 key",
              defaultValue:
                selected?.provider_id === provider
                  ? String(selected?.credential_id || "")
                  : undefined,
              options: credentials.map((c) => ({
                value: c.id,
                label: `${(catalog.providers || []).find((p) => p.id === c.provider_id)?.name || c.provider_id} → ${c.label}`,
              })),
            },
            {
              name: "model",
              label: "供应商模型名称",
              defaultValue: selected?.model,
            },
            {
              name: "temperature",
              label: "Temperature（可选）",
              type: "number",
              required: false,
              defaultValue: String(selected?.params?.temperature ?? ""),
            },
            {
              name: "max_tokens",
              label: "最大输出 tokens（可选）",
              type: "number",
              required: false,
              defaultValue: String(selected?.params?.max_tokens ?? ""),
            },
            {
              name: "params",
              label: "高级参数 JSON",
              type: "textarea",
              defaultValue: JSON.stringify(selected?.params || {}),
            },
            {
              name: "opencode_version",
              label: "OpenCode 版本",
              defaultValue: selected?.opencode_version || "1.18.35",
            },
          ]}
          onSave={async (v) => {
            const params: unknown = JSON.parse(v.params);
            if (!isJsonMapping(params)) throw new Error("参数须为 JSON 对象");
            if (v.temperature !== "")
              params.temperature = Number(v.temperature);
            if (v.max_tokens !== "") params.max_tokens = Number(v.max_tokens);
            const saved = await save("/admin/model-profiles", {
              id: selected?.id,
              name: v.name,
              provider_id: provider,
              credential_id: v.credential_id,
              model: v.model,
              params,
              opencode_version: v.opencode_version,
              enabled: selected?.enabled ?? true,
            });
            onSaved(saved);
          }}
        />
      </CardContent>
    </Card>
  );
}

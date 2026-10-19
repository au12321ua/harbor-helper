type FormField = {
  name: string;
  label: string;
  type?: string;
  options?: { value: string; label: string }[];
  defaultValue?: string;
  required?: boolean;
  copyTo?: string;
  description?: string;
};

import { ErrorNotice, Help } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { LoaderCircle } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";
export function AdminForm<const F extends readonly FormField[]>({
  title,
  description,
  fields,
  onSave,
  resetOnSave = true,
  onDirty,
  disabled = false,
}: {
  title: string;
  description: string;
  fields: F;
  onSave: (value: Record<F[number]["name"], string>) => Promise<unknown>;
  resetOnSave?: boolean;
  onDirty?: (dirty: boolean) => void;
  disabled?: boolean;
}) {
  const formId = useId();
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false),
    [saved, setSaved] = useState(false);
  return (
    <Card>
      <CardHeader>
        <div className="field-heading">
          <CardTitle>{title}</CardTitle>
          <Help label={title}>{description}</Help>
        </div>
      </CardHeader>
      <CardContent>
        <form
          onChange={() => {
            onDirty?.(true);
            setSaved(false);
          }}
          onSubmit={async (e) => {
            e.preventDefault();
            const form = e.currentTarget;
            setBusy(true);
            setError(undefined);
            setSaved(false);
            const value = Object.fromEntries(
              fields.map(({ name }) => [
                name,
                String(new FormData(form).get(name) || ""),
              ]),
            ) as Record<F[number]["name"], string>;
            try {
              await onSave(value);
              if (resetOnSave) form.reset();
              onDirty?.(false);
              toast.success("配置已保存");
              setSaved(true);
            } catch (err) {
              setError(err);
            } finally {
              const secrets = form.querySelectorAll<HTMLInputElement>(
                'input[type="password"]',
              );
              secrets.forEach((input) => {
                input.value = "";
              });
              setBusy(false);
            }
          }}
        >
          <fieldset
            disabled={busy || disabled}
            aria-busy={busy}
            className="min-w-0"
          >
            <FieldGroup>
              {fields.map((f) => (
                <Field key={f.name}>
                  <div className="field-heading">
                    <FieldLabel htmlFor={`${formId}-${f.name}`}>
                      {f.label}
                    </FieldLabel>
                    {f.description ? (
                      <Help label={f.label}>{f.description}</Help>
                    ) : null}
                  </div>
                  {f.options ? (
                    <select
                      id={`${formId}-${f.name}`}
                      name={f.name}
                      required={f.required !== false}
                      defaultValue={f.defaultValue || ""}
                      onChange={
                        f.copyTo
                          ? (e) => {
                              const target =
                                e.currentTarget.form?.elements.namedItem(
                                  f.copyTo!,
                                );
                              if (
                                target instanceof HTMLInputElement &&
                                e.currentTarget.value
                              ) {
                                target.value = e.currentTarget.value;
                                onDirty?.(true);
                              }
                            }
                          : undefined
                      }
                    >
                      {!f.defaultValue ? (
                        <option value="">请选择</option>
                      ) : null}
                      {f.options.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  ) : f.type === "textarea" ? (
                    <Textarea
                      id={`${formId}-${f.name}`}
                      name={f.name}
                      required={f.required !== false}
                      defaultValue={f.defaultValue}
                    />
                  ) : (
                    <Input
                      id={`${formId}-${f.name}`}
                      name={f.name}
                      type={f.type || "text"}
                      step={f.type === "number" ? "any" : undefined}
                      required={f.required !== false}
                      defaultValue={f.defaultValue}
                      autoComplete={
                        f.type === "password" ? "new-password" : "off"
                      }
                    />
                  )}
                </Field>
              ))}
              <ErrorNotice error={error} />
              {saved ? (
                <p role="status">保存完成；下方状态以当前配置为准。</p>
              ) : null}
              <Button disabled={busy || disabled} type="submit">
                {busy ? (
                  <LoaderCircle
                    data-icon="inline-start"
                    className="animate-spin"
                  />
                ) : null}
                保存
              </Button>
            </FieldGroup>
          </fieldset>
        </form>
      </CardContent>
    </Card>
  );
}

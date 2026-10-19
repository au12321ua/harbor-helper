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
import { useId, useLayoutEffect, useRef, useState } from "react";
import { toast } from "sonner";
export function AdminForm<const F extends readonly FormField[]>({
  title,
  description,
  fields,
  onSave,
  onDirty,
  disabled = false,
}: {
  title: string;
  description: string;
  fields: F;
  onSave: (value: Record<F[number]["name"], string>) => Promise<unknown>;
  onDirty?: (dirty: boolean) => void;
  disabled?: boolean;
}) {
  const formId = useId();
  // Untouched fields always read the current saved catalog. Only actual local
  // edits belong to this mounted form; refreshes must not turn them into defaults.
  const defaults = Object.fromEntries(
    fields.map((f) => [f.name, f.defaultValue ?? ""]),
  );
  const defaultsKey = JSON.stringify(defaults);
  const [edits, setEdits] = useState<{
    defaultsKey: string;
    draft: Record<string, string>;
  }>({ defaultsKey, draft: {} });
  let draft = edits.draft;
  if (edits.defaultsKey !== defaultsKey) {
    // Removed fields cannot be submitted or resurrected on a later refresh.
    // New fields use the saved value; a draft matching the saved value is clean.
    draft = Object.fromEntries(
      Object.entries(draft).filter(
        ([name, value]) =>
          Object.hasOwn(defaults, name) && value !== defaults[name],
      ),
    );
    setEdits({ defaultsKey, draft });
  }
  const fieldValue = (name: string) =>
    Object.hasOwn(draft, name) ? draft[name] : defaults[name];
  const dirty = Object.keys(draft).length > 0;
  const dirtyCallback = useRef(onDirty);
  useLayoutEffect(() => {
    dirtyCallback.current = onDirty;
  }, [onDirty]);
  useLayoutEffect(() => {
    dirtyCallback.current?.(dirty);
  }, [dirty]);
  useLayoutEffect(
    () => () => {
      dirtyCallback.current?.(false);
    },
    [],
  );
  function change(name: string, value: string, copyTo?: string) {
    const next = { ...draft, [name]: value };
    if (copyTo && value) next[copyTo] = value;
    for (const key of Object.keys(next))
      if (next[key] === defaults[key]) delete next[key];
    setEdits({ defaultsKey, draft: next });
    setSaved(false);
  }
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
              // This save acknowledged this form. Adopt its refreshed, possibly
              // normalized saved values without resetting any unrelated editor.
              setEdits((current) => ({ ...current, draft: {} }));
              toast.success("配置已保存");
              setSaved(true);
            } catch (err) {
              setError(err);
            } finally {
              setEdits((current) => ({
                ...current,
                draft: Object.fromEntries(
                  Object.entries(current.draft).filter(
                    ([name]) =>
                      !fields.some(
                        (f) => f.name === name && f.type === "password",
                      ),
                  ),
                ),
              }));
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
                      value={fieldValue(f.name)}
                      onChange={(e) => change(f.name, e.target.value, f.copyTo)}
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
                      value={fieldValue(f.name)}
                      onChange={(e) => change(f.name, e.target.value)}
                    />
                  ) : (
                    <Input
                      id={`${formId}-${f.name}`}
                      name={f.name}
                      type={f.type || "text"}
                      step={f.type === "number" ? "any" : undefined}
                      required={f.required !== false}
                      value={fieldValue(f.name)}
                      onChange={(e) => change(f.name, e.target.value)}
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

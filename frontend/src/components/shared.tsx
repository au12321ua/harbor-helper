import { ApiError } from "@/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { labels } from "@/presentation";
export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <Alert variant="destructive">
      <AlertTitle>操作未完成</AlertTitle>
      <AlertDescription>
        {error instanceof Error ? error.message : String(error)}
        {error instanceof ApiError && error.requestId ? (
          <small>请求编号：{error.requestId}</small>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
export function Status({ value }: { value: string }) {
  return (
    <Badge
      className="whitespace-nowrap"
      variant={
        value === "failed" ||
        value === "cleanup_blocked" ||
        value === "incomplete"
          ? "destructive"
          : value === "succeeded" || value === "clean"
            ? "default"
            : "secondary"
      }
    >
      {labels[value] || value || "—"}
    </Badge>
  );
}
export function Title({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
export function SelectField({
  label,
  name,
  value,
  onChange,
  children,
  description,
  required = true,
}: {
  label: string;
  name: string;
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
  description?: string;
  required?: boolean;
}) {
  return (
    <Field>
      <FieldLabel htmlFor={name}>{label}</FieldLabel>
      <select
        id={name}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
      >
        {children}
      </select>
      {description ? <FieldDescription>{description}</FieldDescription> : null}
    </Field>
  );
}
export function EmptyState({
  title = "暂无实验",
  description = "提交第一个实验后，它会出现在团队共享列表中。",
}: {
  title?: string;
  description?: string;
}) {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}
export function Loading() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-12 w-64" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

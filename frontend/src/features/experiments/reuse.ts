import type { Catalog, Manifest, SubmissionInput } from "@/api";

export const fields = [
  "name",
  "dataset_id",
  "dataset_source_version_id",
  "task",
  "agent",
  "model_profile",
  "attachment_version_id",
  "attempts",
  "concurrency",
  "wall_seconds",
  "environment_build_timeout_multiplier",
] as const;
export type DraftField = (typeof fields)[number];
export type Draft = Record<DraftField, unknown>;
export type Reuse = {
  kind: "history";
  source: string;
  values: Draft;
  datasetIdentity?: string | null;
  sourceId?: string;
};
export type NewEntry = Reuse | { kind: "attachment"; version: string };
export function fromManifest(
  manifest: Manifest,
  source: string,
  _copyName = true,
): Reuse {
  const e: Partial<Manifest["effective"]> = manifest.effective ?? {},
    s = manifest.service;
  const name = s?.name ?? "";
  return {
    kind: "history",
    source,
    datasetIdentity: e.dataset,
    sourceId: s?.submission_id || undefined,
    values: {
      name,
      dataset_source_version_id: s?.dataset_source_version_id ?? "",
      dataset_id:
        s?.dataset_id ?? (e.dataset ? `引用：${e.dataset}` : undefined),
      task: e.task_filter === null ? "" : e.task_filter,
      agent: e.agent,
      model_profile: s?.model_profile ?? undefined,
      attachment_version_id: s?.attachment_version_id ?? "",
      attempts: e.attempts,
      concurrency: e.concurrency,
      wall_seconds: e.wall_seconds,
      environment_build_timeout_multiplier:
        e.environment_build_timeout_multiplier,
    },
  };
}
export function fromRequest(request: SubmissionInput, source: string): Reuse {
  return {
    kind: "history",
    source: `${source}（公开提交意图，未恢复冻结结果）`,
    values: {
      name: request.name ?? "",
      dataset_source_version_id: request.dataset_source_version_id ?? "",
      dataset_id:
        request.dataset_id ??
        (request.dataset ? `引用：${request.dataset}` : undefined),
      task: request.task ?? "",
      agent: request.agent ?? undefined,
      model_profile: request.model_profile ?? undefined,
      attachment_version_id: request.attachment_version_id ?? "",
      attempts: request.attempts ?? undefined,
      concurrency: request.concurrency ?? undefined,
      wall_seconds: request.wall_seconds ?? undefined,
      environment_build_timeout_multiplier:
        request.environment_build_timeout_multiplier ?? undefined,
    },
  };
}
export function fromParent(
  manifest: Manifest,
  request: SubmissionInput,
  source: string,
): Reuse {
  const result = fromManifest(
    manifest,
    `${source}（父实验配置；修复重试的明确时长覆盖）`,
    false,
  );
  if (
    typeof request.wall_seconds === "number" &&
    Number.isFinite(request.wall_seconds) &&
    request.wall_seconds > 0
  )
    result.values.wall_seconds = request.wall_seconds;
  return result;
}
export function initialDraft(catalog: Catalog, entry?: NewEntry): Draft {
  if (entry?.kind === "history") return { ...entry.values };
  return {
    name: "",
    dataset_source_version_id: "",
    dataset_id:
      catalog.settings.default_dataset_id ||
      catalog.datasets.find((d) => d.ready && d.enabled !== false)?.id ||
      "",
    task: "",
    agent: "opencode",
    model_profile: catalog.settings.default_model_profile || "",
    attachment_version_id: entry?.kind === "attachment" ? entry.version : "",
    attempts: 1,
    concurrency: 1,
    wall_seconds: Math.min(1800, catalog.limits.max_wall_seconds),
    environment_build_timeout_multiplier: 10,
  };
}
export function text(value: unknown): string {
  return value === undefined
    ? ""
    : typeof value === "string"
      ? value
      : JSON.stringify(value);
}
export function profilesFor(catalog: Catalog) {
  return catalog.model_profiles.filter(
    (p) =>
      p.enabled !== false &&
      catalog.providers.some((v) => v.id === p.provider_id && v.enabled) &&
      catalog.credentials.some((v) => v.id === p.credential_id && v.enabled),
  );
}
export function problems(
  draft: Draft,
  catalog: Catalog,
): Partial<Record<DraftField, string>> {
  const issues: Partial<Record<DraftField, string>> = {};
  const dataset = catalog.datasets.find(
    (d) => d.id === draft.dataset_id && d.ready && d.enabled !== false,
  );
  if (!dataset)
    issues.dataset_id =
      draft.dataset_id === undefined
        ? "未知：请明确选择数据集"
        : typeof draft.dataset_id === "string" &&
            draft.dataset_id.startsWith("引用：")
          ? "网页无法表示：请明确选择目录数据集"
          : "不可用：请明确选择目录数据集";
  if (
    draft.task !== "" &&
    (typeof draft.task !== "string" ||
      !dataset?.tasks?.some((t) => t.name === draft.task))
  )
    issues.task =
      draft.task === undefined
        ? "未知：请明确选择任务或全部"
        : typeof draft.task !== "string" || /[*?[]/.test(draft.task)
          ? "网页无法表示：请重选确切任务或明确选择全部"
          : "不可用：请重选确切任务或明确选择全部";
  if (!["opencode", "oracle"].includes(String(draft.agent)))
    issues.agent =
      draft.agent === undefined
        ? "未知：请选择执行方案"
        : "网页无法表示：请选择执行方案";
  if (
    draft.agent !== "oracle" &&
    !profilesFor(catalog).some((p) => p.id === draft.model_profile)
  )
    issues.model_profile =
      draft.model_profile === undefined
        ? "未知：请明确选择模型方案"
        : "不可用：请明确选择模型方案";
  if (
    draft.attachment_version_id !== "" &&
    !catalog.attachments.some(
      (a) =>
        a.enabled &&
        a.versions.some(
          (v) =>
            v.id === draft.attachment_version_id &&
            v.enabled &&
            v.availability === "available",
        ),
    )
  )
    issues.attachment_version_id =
      draft.attachment_version_id === undefined
        ? "未知：请明确选择附件或无附件"
        : "不可用：请重选附件，或明确清除为无附件";
  const bounds = {
    attempts: catalog.limits.max_attempts,
    concurrency: catalog.limits.max_trials,
    wall_seconds: catalog.limits.max_wall_seconds,
    environment_build_timeout_multiplier: Infinity,
  };
  for (const [field, max] of Object.entries(bounds)) {
    const k = field as DraftField,
      raw = draft[k];
    const n =
      typeof raw === "number" || (typeof raw === "string" && raw.trim() !== "")
        ? Number(raw)
        : NaN;
    if (!Number.isFinite(n) || n < 1 || n > max || !Number.isInteger(n))
      issues[k] =
        `${raw === undefined ? "未知" : "不可用"}：必须为整数，范围 1–${max === Infinity ? "无上限" : max}；请明确修改`;
  }
  if (typeof draft.name !== "string" || draft.name.length > 128)
    issues.name = "名称须为不超过128字符的文本";
  return issues;
}
export function submissionBody(draft: Draft): SubmissionInput {
  return {
    name: text(draft.name),
    dataset_id: text(draft.dataset_id),
    dataset_source_version_id: text(draft.dataset_source_version_id) || undefined,
    task: draft.task === "" ? null : text(draft.task),
    agent: draft.agent as "oracle" | "opencode",
    model_profile: draft.agent === "oracle" ? null : text(draft.model_profile),
    attachment_version_id:
      draft.attachment_version_id === ""
        ? null
        : text(draft.attachment_version_id),
    attempts: Number(draft.attempts),
    concurrency: Number(draft.concurrency),
    wall_seconds: Number(draft.wall_seconds),
    environment_build_timeout_multiplier: Number(
      draft.environment_build_timeout_multiplier,
    ),
  };
}

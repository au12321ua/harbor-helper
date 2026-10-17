import type { Comparison } from "@/api";
export function comparisonJSON(comparison: Comparison, exportedAt: string) {
  return (
    JSON.stringify(
      { format_version: 1, exported_at: exportedAt, comparison },
      null,
      2,
    ) + "\n"
  );
}
// Text only: numeric values (including negative metrics) remain numeric.
function cell(value: unknown): string {
  let s = typeof value === "string" ? value : String(value ?? "");
  // oxlint-disable-next-line no-control-regex -- CSV formula defense includes leading control characters.
  if (
    typeof value === "string" &&
    /^[\s\u0000-\u001f\u007f-\u009f]*[=+\-@]/u.test(s)
  )
    s = "'" + s;
  return `"${s.replaceAll('"', '""')}"`;
}
function typed(map: Record<string, unknown>, key: string): [string, unknown] {
  if (!Object.hasOwn(map, key)) return ["missing", ""];
  const value = map[key];
  return [
    value === null ? "null" : typeof value,
    value === null ? "null" : value,
  ];
}
export function comparisonCSV(c: Comparison, exportedAt: string) {
  const header = [
    "format_version",
    "exported_at",
    "left_run",
    "right_run",
    "comparable",
    "reasons_json",
    "record",
    "task",
    "metric",
    "left_type",
    "left_value",
    "right_type",
    "right_value",
    "delta_type",
    "delta_value",
    "metadata_json",
  ];
  const rows: unknown[][] = [header];
  const add = (
    record: string,
    task: unknown,
    metric: unknown,
    a: [string, unknown],
    b: [string, unknown],
    d: [string, unknown],
    metadata: unknown = "",
  ) =>
    rows.push([
      1,
      exportedAt,
      c.left,
      c.right,
      c.comparable,
      JSON.stringify(c.reasons),
      record,
      task,
      metric,
      ...a,
      ...b,
      ...d,
      metadata,
    ]);
  add(
    "metadata",
    "",
    "",
    ["", ""],
    ["", ""],
    ["", ""],
    JSON.stringify({
      config_changes: c.config_changes,
      attachment_inputs: c.attachment_inputs,
      bundle_change: c.bundle_change,
      environment_observations: c.environment_observations,
    }),
  );
  for (const t of c.tasks) {
    const metrics = [
      ...new Set([
        ...Object.keys(t.left),
        ...Object.keys(t.right),
        ...Object.keys(t.delta),
      ]),
    ];
    if (!Object.keys(t.left).length && !Object.keys(t.right).length)
      add(
        "no_valid_metrics",
        t.task,
        "",
        ["missing", ""],
        ["missing", ""],
        [c.comparable ? "missing" : "incomparable", ""],
      );
    for (const m of metrics)
      add(
        "task",
        t.task,
        m,
        typed(t.left, m),
        typed(t.right, m),
        c.comparable ? typed(t.delta, m) : ["incomparable", ""],
      );
  }
  if (c.comparable && c.mean_task_delta)
    for (const m of Object.keys(c.mean_task_delta))
      add(
        "mean_task_delta",
        "",
        m,
        ["", ""],
        ["", ""],
        typed(c.mean_task_delta, m),
      );
  return (
    "\uFEFF" + rows.map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n"
  );
}
export function downloadComparison(c: Comparison, format: "json" | "csv") {
  const at = new Date().toISOString();
  const content =
    format === "json" ? comparisonJSON(c, at) : comparisonCSV(c, at);
  const blob = new Blob([content], {
    type:
      format === "json"
        ? "application/json;charset=utf-8"
        : "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const safe = (id: string) => id.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80);
  link.href = url;
  link.download = `comparison-${safe(c.left)}-${safe(c.right)}.${format}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

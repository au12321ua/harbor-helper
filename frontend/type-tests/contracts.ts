// This file is typechecked, never bundled or executed. Each expected error must
// remain an error in the actual transport used by pages.
import { api, post, upload, mutation } from "../src/api";
import type { Accepted, RunSummary } from "../src/api";

declare const labelsWithoutStarting: Omit<
  Record<RunSummary["status"] | Accepted["status"], string>,
  "starting"
>;

async function checks() {
  const runs = await api("/runs");
  // @ts-expect-error unknown server field
  void runs.rnus;
  // @ts-expect-error wrong endpoint method
  await api("/runs", { method: "PATCH", body: {} });
  // @ts-expect-error invalid login request
  await post("/auth/login", { username: "x", passwrod: "x" });
  // @ts-expect-error arbitrary response generic is not supported
  await api<{ invented: string }>("/me");
  // @ts-expect-error wrong endpoint
  await api("/invented");
  // @ts-expect-error wrong status
  const status: RunSummary["status"] = "canceling";
  const logs = await api("/runs/id/logs");
  // @ts-expect-error log response must not acquire detail fields from overlapping paths
  void logs.row;
  // @ts-expect-error empty rerun input is closed, not arbitrary JSON
  await post("/runs/id/rerun", { changed: true });
  // @ts-expect-error limit names come from the backend canonical definition
  await mutation("/admin/limits", { max_joobs: 1 }, "PATCH");
  const detail = await api("/runs/id");
  // @ts-expect-error report is nullable
  void detail.report.tasks;
  // @ts-expect-error nested fields are checked
  void detail.manifest.effective.attemptz;
  // @ts-expect-error metadata is not an arbitrary JSON string
  await upload("/attachments", { naem: "x" }, new Blob(), "stable-key");
  await upload(
    "/attachments/id/versions",
    // @ts-expect-error publish metadata cannot name attachment
    { name: "x" },
    new Blob(),
    "stable-key",
  );
  // @ts-expect-error file must be bytes
  await upload("/attachments", { name: "x" }, "not-a-file", "stable-key");
  // @ts-expect-error idempotency key cannot be omitted
  await upload("/attachments", { name: "x" }, new Blob());
  // @ts-expect-error state labels must cover every canonical value
  const labels: Record<RunSummary["status"] | Accepted["status"], string> = {
    queued: "排队中",
  };
  // @ts-expect-error omitting exactly one real state must fail too
  const singleMissing: Record<
    RunSummary["status"] | Accepted["status"],
    string
  > = labelsWithoutStarting;
  void singleMissing;
  void status;
  void labels;
}
void checks;

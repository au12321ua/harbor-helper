// This file is typechecked, never bundled or executed. Each expected error must
// remain an error in the actual transport used by pages.
import { api, post, upload, mutation } from "../src/api";
import type {
  Accepted,
  RunSummary,
  Logs,
  Report,
  RunDetail,
  AttachmentResult,
  Tombstone,
} from "../src/api";

declare const labelsWithoutStarting: Omit<
  Record<RunSummary["status"] | Accepted["status"], string>,
  "starting"
>;

declare const dynamicId: string;
declare const operationKey: string;

async function checks() {
  // Dynamic single-segment IDs and greedy backend :path keys stay usable.
  const dynamicDetail: RunDetail = await api(`/runs/${dynamicId}`);
  const dynamicLogs: Logs = await api(`/runs/${dynamicId}/logs`);
  const dynamicReport: Report | null = await api(`/runs/${dynamicId}/report`);
  const literalReport: Report | null = await api("/runs/id/report");
  const attachment: AttachmentResult | Tombstone = await api(
    `/attachment-operations/create/${operationKey}`,
  );
  const greedyAttachment: AttachmentResult | Tombstone = await api(
    "/attachment-operations/create/namespace/key/with/slashes",
  );
  const accepted: Accepted | Tombstone = await api(
    `/submission-operations/submit/${operationKey}`,
  );
  const greedyAccepted: Accepted | Tombstone = await api(
    "/submission-operations/submit/namespace/key/with/slashes",
  );
  // Deleted receipts stay distinguishable; callers must narrow before using content.
  if ("deleted" in attachment) {
    const deleted: true = attachment.deleted;
    void deleted;
    // @ts-expect-error tombstones never carry attachment content
    void attachment.attachment;
  }
  if ("deleted" in accepted) {
    // @ts-expect-error tombstones never carry the submitted body
    void accepted.request;
  }
  void [
    dynamicDetail,
    dynamicLogs,
    dynamicReport,
    literalReport,
    attachment,
    greedyAttachment,
    accepted,
    greedyAccepted,
  ];
  await mutation("/admin/settings", { team_name: "probe" }, "PATCH");
  // @ts-expect-error non-existent nested suffix must not be consumed by the ID
  await api("/runs/id/logz");
  // @ts-expect-error dynamic ID does not make a misspelled suffix valid
  await api(`/runs/${dynamicId}/logz`);
  // @ts-expect-error normal path parameters cannot consume extra segments
  await api("/runs/id/logs/extra");
  // @ts-expect-error write paths also require the exact route shape
  await post("/runs/id/extra/cancel", {});
  // @ts-expect-error empty IDs are not valid path segments
  await api("/runs//logs");
  // @ts-expect-error selecting PATCH requires the runtime PATCH argument
  await mutation<"PATCH">("/admin/settings", { team_name: "probe" });
  // @ts-expect-error a PATCH-only endpoint cannot default to POST
  await mutation("/admin/settings", { team_name: "probe" });
  // @ts-expect-error explicit method must agree with the selected method type
  await mutation<"PATCH">("/admin/settings", { team_name: "probe" }, "POST");
  // @ts-expect-error even a union method type cannot omit the runtime method
  await mutation<"POST" | "PATCH">("/admin/settings", { team_name: "probe" });

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

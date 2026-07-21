"use server";

import { createHash, randomUUID } from "node:crypto";

import { redirect } from "next/navigation";

import { validateControls } from "./controls";
import { observatoryFailureState } from "./errors";
import type { EvidenceFeedback } from "./query-source";
import { getObservatorySource } from "./server";

const FEEDBACK_LABELS: ReadonlySet<EvidenceFeedback["label"]> = new Set([
  "relevant",
  "irrelevant",
  "duplicate",
  "temporally_invalid",
]);

function str(formData: FormData, key: string): string {
  const value = formData.get(key);
  return typeof value === "string" ? value : "";
}

/**
 * Deterministic Idempotency-Key for evidence feedback. A feedback record's
 * stable identity is (run_id, item_id, label): resubmitting the same verdict
 * for the same item (e.g. a double-click) must reuse the key so the server
 * dedupes the append-only append instead of writing a duplicate row. Query and
 * rerun creation deliberately mint a fresh key per call — each is a new record.
 */
function feedbackIdempotencyKey(runId: string, itemId: string, label: string): string {
  return createHash("sha256").update(`${runId}:${itemId}:${label}`, "utf8").digest("hex");
}

/** Create a new (optionally parent-linked) query from bounded controls. */
export async function submitQueryAction(formData: FormData): Promise<void> {
  const { errors, query } = validateControls({
    question: str(formData, "question"),
    lanes: formData.getAll("lanes").map(String),
    topK: str(formData, "topK"),
    asOf: str(formData, "asOf"),
    forms: str(formData, "forms"),
    periods: str(formData, "periods"),
  });
  const parentQueryId = str(formData, "parentQueryId");
  if (!query) redirect(`/observatory?error=${encodeURIComponent(errors.join(" "))}`);

  const request = parentQueryId ? { ...query, parent_query_id: parentQueryId } : query;
  let runId: string;
  try {
    const accepted = await getObservatorySource().createQuery(request, randomUUID());
    runId = accepted.run_id;
  } catch (error) {
    redirect(`/observatory?error=${observatoryFailureState(error) ?? "unavailable"}`);
  }
  redirect(`/observatory/runs/${runId}`);
}

/** Unchanged, parent-linked rerun of an existing query. */
export async function rerunAction(formData: FormData): Promise<void> {
  const queryId = str(formData, "queryId");
  let runId: string;
  try {
    const accepted = await getObservatorySource().createRerun(queryId, randomUUID());
    runId = accepted.run_id;
  } catch (error) {
    redirect(
      `/observatory/runs/${str(formData, "runId")}?error=${observatoryFailureState(error) ?? "unavailable"}`,
    );
  }
  redirect(`/observatory/runs/${runId}`);
}

/** Append-only evidence feedback for one candidate of a run. */
export async function sendFeedbackAction(formData: FormData): Promise<void> {
  const runId = str(formData, "runId");
  const itemId = str(formData, "itemId");
  const label = str(formData, "label") as EvidenceFeedback["label"];
  const reason = str(formData, "reason").trim();
  if (!FEEDBACK_LABELS.has(label)) {
    redirect(`/observatory/runs/${runId}?error=invalid_scope`);
  }
  const feedback: EvidenceFeedback = { item_id: itemId, label, ...(reason ? { reason } : {}) };
  try {
    const key = feedbackIdempotencyKey(runId, itemId, label);
    await getObservatorySource().submitFeedback(runId, feedback, key);
  } catch (error) {
    redirect(`/observatory/runs/${runId}?error=${observatoryFailureState(error) ?? "unavailable"}`);
  }
  redirect(`/observatory/runs/${runId}?feedback=recorded`);
}

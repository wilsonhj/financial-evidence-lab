import type { components, operations } from "@fel/contracts";
import candidateSchema from "@fel/contracts/schemas/extraction-candidate-fields.schema.json";
import payloadSchema from "@fel/contracts/schemas/extraction-payload.schema.json";
import conflictSchema from "@fel/contracts/schemas/extraction-conflict.schema.json";
import contextSchema from "@fel/contracts/schemas/extraction-validation-context.schema.json";
import eventPageSchema from "@fel/contracts/schemas/extraction-event-page.schema.json";
import eventSchema from "@fel/contracts/schemas/extraction-event.schema.json";
import reviewSchema from "@fel/contracts/schemas/extraction-review-command.schema.json";
import resultSchema from "@fel/contracts/schemas/extraction-review-result.schema.json";
import { createAjv } from "../data/ajv-setup";

export type Schemas = components["schemas"];
export type Run = Schemas["ExtractionRun"];
export type Proposal = Schemas["ExtractionProposal"];
export type Approved = Schemas["ApprovedExtraction"];
export type Conflict = Schemas["ExtractionConflict"];
export type Event = Schemas["ExtractionEvent"];
export type Permissions = Schemas["ExtractionPermissions"];
export type Review = Schemas["ReviewCommand"];
export type Correction = Schemas["CorrectionCommand"];
export type CreateRun = Schemas["ExtractionRunCreate"];
export type Rerun = operations["rerunExtraction"]["requestBody"]["content"]["application/json"];
export type Guard<T> = (value: unknown) => value is T;

const ajv = createAjv();
ajv.addSchema(payloadSchema);
ajv.addSchema({
  $id: "https://contracts.fel.dev/schemas/extraction-review-command/extraction-payload.schema.json",
  $ref: payloadSchema.$id,
});
const schema = <T>(value: object): Guard<T> => ajv.compile<T>(value);
const payloadValidator = ajv.getSchema<Schemas["ExtractionPayload"]>(payloadSchema.$id)!;
const payload: Guard<Schemas["ExtractionPayload"]> = (v): v is Schemas["ExtractionPayload"] =>
  payloadValidator(v) === true;
const candidate = schema<Schemas["ExtractionCandidateFields"]>(candidateSchema);
const context = schema<Schemas["ExtractionValidationContext"]>(contextSchema);
const eventSchemaGuard = schema<Event>(eventSchema);
ajv.addSchema({
  $id: "https://contracts.fel.dev/schemas/extraction-event-page/extraction-event.schema.json",
  $ref: eventSchema.$id,
});
const eventPageGuard = schema<Schemas["ExtractionEventPage"]>(eventPageSchema);
export const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
export const uuid = (v: unknown): v is string =>
  typeof v === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(v);
const str = (v: unknown): v is string => typeof v === "string";
const integer = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) >= 0;
const positive = (v: unknown): v is number => integer(v) && v > 0;
const date = schema<string>({ type: "string", format: "date-time" });
const one =
  (...values: string[]) =>
  (v: unknown) =>
    str(v) && values.includes(v);
const nullable = (guard: (v: unknown) => boolean) => (v: unknown) => v === null || guard(v);
const array =
  (guard: (v: unknown) => boolean, max = 200, min = 0) =>
  (v: unknown): v is unknown[] =>
    Array.isArray(v) && v.length >= min && v.length <= max && v.every(guard);
const record = (guard: (v: unknown) => boolean) => (v: unknown) =>
  object(v) && Object.values(v).every(guard);
type Fields = Record<string, (v: unknown) => boolean>;
function closed(v: unknown, required: Fields, optional: Fields = {}): v is Record<string, unknown> {
  return (
    object(v) &&
    Object.entries(required).every(([k, check]) => Object.hasOwn(v, k) && check(v[k])) &&
    Object.keys(v).every(
      (k) => Object.hasOwn(required, k) || (Object.hasOwn(optional, k) && optional[k]!(v[k])),
    )
  );
}
const kind = one("kpi", "guidance", "revenue_driver");
const status = one("queued", "running", "waiting_review", "succeeded", "failed", "cancelled");
const state = one("proposed", "needs_review", "accepted", "rejected", "superseded");
const modes = (v: unknown) => array(kind, 3, 1)(v) && new Set(v).size === v.length;
const confidence = (v: unknown) => str(v) && /^(0(\.\d{1,3})?|1(\.0{1,3})?)$/.test(v);
export const etag = (v: unknown): v is string =>
  str(v) && v.length <= 128 && /^"[^"\r\n]+"$/.test(v);
export const cursor = (v: unknown): v is string =>
  str(v) &&
  v.length > 0 &&
  v.length <= 2048 &&
  ![...v].some((c) => c.charCodeAt(0) <= 32 || c.charCodeAt(0) === 127);
const edge = (v: unknown): v is Schemas["EvidenceEdge"] =>
  closed(v, {
    source_span_id: uuid,
    document_version_id: uuid,
    role: one("supports", "definition", "conflicts", "derivation_input"),
    citation_status: one("verified", "partial", "contradictory", "invalid"),
  });
const limits = (v: unknown) =>
  closed(
    v,
    {},
    {
      max_calls: (v) => positive(v) && v <= 10,
      max_input_tokens: (v) => positive(v) && v <= 100000,
      max_output_tokens: (v) => positive(v) && v <= 20000,
      max_wall_seconds: (v) => positive(v) && v <= 600,
      max_cost_usd: (v) => str(v) && /^(0(\.\d{1,6})?|1(\.\d{1,6})?|2(\.0{1,6})?)$/.test(v),
    },
  );
const error = (v: unknown): v is Schemas["Error"] =>
  closed(v, {
    error: (v) => closed(v, { code: str, message: str, request_id: str }, { details: object }),
  });
const run = (v: unknown): v is Run =>
  closed(
    v,
    {
      id: uuid,
      workspace_id: uuid,
      entity_id: uuid,
      status,
      modes,
      as_of: date,
      ontology_version: str,
      workflow_version: str,
      provider: str,
      model: str,
      limits,
      usage: (v) =>
        closed(v, { calls: integer, input_tokens: integer, output_tokens: integer, cost_usd: str }),
      version: positive,
      created_at: date,
      cancel_requested_at: nullable(date),
    },
    { parent_run_id: nullable(uuid), corpus_version_id: uuid, error: nullable(error) },
  );
const proposal = (v: unknown): v is Proposal =>
  closed(v, {
    id: uuid,
    run_id: uuid,
    kind,
    metric_id: str,
    payload: (v) => payload(v) || candidate(v),
    evidence: array(edge),
    record_confidence: nullable(confidence),
    field_confidences: record(str),
    validations: array(
      (v) => closed(v, { code: str, status: one("pass", "warning", "fail") }, { detail: object }),
      1000,
    ),
    state,
    review_priority: one("normal", "high"),
    version: positive,
    conflict_ids: (v) => array(uuid, 100)(v) && new Set(v).size === v.length,
  });
const approved = (v: unknown): v is Approved =>
  closed(
    v,
    {
      record_id: uuid,
      version_id: uuid,
      version: positive,
      kind,
      metric_id: str,
      payload,
      evidence: array(edge, 200, 1),
      evidence_manifest_hash: (v) => str(v) && /^sha256:[0-9a-f]{64}$/.test(v),
      ontology_version: str,
      approved_by: uuid,
      created_at: date,
      approval_reason: str,
      normalizer_version: str,
      validator_version: str,
      validation_context: nullable(context),
    },
    { parent_version_id: nullable(uuid) },
  );
const step = (v: unknown): v is Schemas["ExtractionStepSummary"] =>
  closed(
    v,
    {
      id: uuid,
      step_name: str,
      attempt: positive,
      status: one("pending", "running", "succeeded", "failed", "skipped", "cancelled"),
      input_hash: str,
      output_hash: nullable(str),
      started_at: nullable(date),
      finished_at: nullable(date),
    },
    { input_tokens: integer, output_tokens: integer, cost_usd: str, error: nullable(error) },
  );
const event = (v: unknown): v is Event => eventSchemaGuard(v) && positive(v.id);
function page<T>(guard: Guard<T>): Guard<{
  items: T[];
  next_cursor: string | null;
  previous_cursor: string | null;
  limit: number;
}> {
  return (
    v: unknown,
  ): v is {
    items: T[];
    next_cursor: string | null;
    previous_cursor: string | null;
    limit: number;
  } =>
    closed(v, {
      items: array(guard),
      next_cursor: nullable(cursor),
      previous_cursor: nullable(cursor),
      limit: (v) => positive(v) && v <= 200,
    }) &&
    Array.isArray(v.items) &&
    v.items.length <= Number(v.limit) &&
    (v.items.length > 0 || (v.next_cursor === null && v.previous_cursor === null));
}
const reason = (v: unknown) => str(v) && v.trim().length > 0 && v.length <= 2000;
const ids = (v: unknown) => array(uuid, 200, 1)(v) && new Set(v).size === v.length;
const conflict = schema<Conflict>(conflictSchema);
export const guards = {
  events: (v: unknown): v is Schemas["ExtractionEventPage"] =>
    eventPageGuard(v) &&
    v.items.every((e) => event(e) && e.run_id === v.run_id) &&
    v.items.length <= v.limit &&
    (v.items.length > 0 || (v.next_cursor === null && v.previous_cursor === null)),
  candidate,
  payload,
  edge,
  error,
  run,
  proposal,
  approved,
  conflict,
  event,
  step,
  runs: page(run),
  proposals: page(proposal),
  versions: page(approved),
  conflicts: page(conflict),
  steps: page(step),
  permissions: (v: unknown): v is Permissions =>
    closed(v, {
      workspace_id: uuid,
      allowed_actions: (v) =>
        array(
          one("create", "cancel", "rerun", "accept", "edit", "reject", "merge", "correct"),
          8,
        )(v) && new Set(v).size === v.length,
    }),
  review: schema<Review>(reviewSchema),
  result: schema<Schemas["ReviewResult"]>(resultSchema),
  correction: (v: unknown): v is Correction =>
    closed(v, { reason, payload, evidence: array(edge, 200, 1) }),
  create: (v: unknown): v is CreateRun =>
    closed(
      v,
      { entity_id: uuid, as_of: date, modes, source_span_ids: ids },
      {
        claim_ids: (v) => array(uuid)(v) && new Set(v).size === v.length,
        corpus_version_id: nullable(uuid),
        limits,
      },
    ),
  rerun: (v: unknown): v is Rerun => closed(v, { reason }),
};

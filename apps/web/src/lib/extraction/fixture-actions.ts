import "node:process";
import type { Approved, Event, Run, Schemas } from "./contracts";
import { guards } from "./contracts";
import { fixtureError, fixtureId, type FixtureState } from "./fixture";

// UI interaction simulation only; real validation/locking is proved against the API.
const receipts = new WeakMap<
  FixtureState,
  Map<string, { fingerprint: string; response: Response }>
>();
const tag = (run: Run) => `"fixture-run-${run.version}-${run.status}"`;
function append(state: FixtureState, runId: string, type: Event["type"]) {
  state.events.push({
    schema_version: "extraction-event/v1",
    id: Math.max(0, ...state.events.map((e) => e.id)) + 1,
    run_id: runId,
    type,
    occurred_at: new Date().toISOString(),
    payload: {},
  });
}
function approved(
  input: Schemas["ExtractionPayload"],
  evidence: Schemas["EvidenceEdge"][],
  reason: string,
  run: Run,
): Approved {
  return {
    record_id: crypto.randomUUID(),
    version_id: crypto.randomUUID(),
    version: 1,
    parent_version_id: null,
    kind: input.kind,
    metric_id: input.metric_id,
    payload: structuredClone(input),
    evidence: structuredClone(evidence),
    evidence_manifest_hash: `sha256:${"b".repeat(64)}`,
    ontology_version: run.ontology_version,
    approved_by: fixtureId(9),
    created_at: new Date().toISOString(),
    approval_reason: reason,
    normalizer_version: "normalize/v2",
    validator_version: "validate/v3",
    validation_context: {
      schema_version: "extraction-validation-context/v1",
      workflow_version: run.workflow_version,
      normalizer_version: "normalize/v2",
      validator_version: "validate/v3",
      unit_policy_version: "unit-comparison/v1",
      range_policy_version: "guidance-range-order/v1",
      source_runs: [
        {
          run_id: run.id,
          as_of: run.as_of,
          corpus_version_id: run.corpus_version_id!,
          ontology_version: run.ontology_version,
          workflow_version: run.workflow_version,
          policy_id: fixtureId(11),
        },
      ],
    },
  };
}
export async function fixtureAction(
  state: FixtureState,
  path: string,
  init: RequestInit,
): Promise<Response> {
  const headers = new Headers(init.headers),
    key = headers.get("idempotency-key");
  if (!key) return fixtureError(422, "VALIDATION_ERROR");
  let input: unknown;
  try {
    input = init.body ? JSON.parse(String(init.body)) : undefined;
  } catch {
    return fixtureError(422, "VALIDATION_ERROR");
  }
  // The endpoint alone decides the operation. Letting a failed body guard fall
  // through would check the wrong capability and enter the wrong branch.
  let action: "correct" | "rerun" | "cancel" | "create" | Schemas["ReviewCommand"]["action"];
  if (path.endsWith("/review")) {
    if (!guards.review(input)) return fixtureError(422, "VALIDATION_ERROR");
    action = input.action;
  } else if (path.endsWith("/corrections")) action = "correct";
  else if (path.endsWith("/rerun")) action = "rerun";
  else if (init.method === "DELETE") action = "cancel";
  else action = "create";
  if (!state.permissions.allowed_actions.includes(action)) return fixtureError(403, "FORBIDDEN");
  const ledger = receipts.get(state) ?? new Map();
  receipts.set(state, ledger);
  const fingerprint = JSON.stringify([path, init.method, init.body, headers.get("if-match")]);
  const previous = ledger.get(key);
  if (previous)
    return previous.fingerprint === fingerprint
      ? previous.response.clone()
      : fixtureError(409, "IDEMPOTENCY_KEY_REUSED");
  const draft = structuredClone(state);
  const [, , resource, id, operation] = path.split("/");
  let response: Response;
  if (action === "cancel") {
    const run = draft.runs.find((r) => r.id === id);
    if (!run) return fixtureError(404, "NOT_FOUND");
    if (headers.get("if-match") !== tag(run)) return fixtureError(412, "PRECONDITION_FAILED");
    if (["succeeded", "failed", "cancelled"].includes(run.status))
      return fixtureError(409, "CONFLICT");
    append(draft, run.id, "run_cancelled");
    run.status = "cancelled";
    run.cancel_requested_at = new Date().toISOString();
    response = Response.json(run, { headers: { etag: tag(run) } });
  } else if (action === "rerun" || action === "create") {
    const parent = action === "rerun" ? draft.runs.find((r) => r.id === id) : draft.runs[0];
    if (!parent) return fixtureError(404, "NOT_FOUND");
    if (action === "rerun" ? !guards.rerun(input) : !guards.create(input))
      return fixtureError(422, "VALIDATION_ERROR");
    const child: Run = {
      ...parent,
      id: crypto.randomUUID(),
      parent_run_id: action === "rerun" ? parent.id : null,
      status: "waiting_review",
      cancel_requested_at: null,
      created_at: new Date().toISOString(),
      ...(guards.create(input)
        ? {
            entity_id: input.entity_id,
            as_of: input.as_of,
            modes: input.modes,
            corpus_version_id: input.corpus_version_id ?? parent.corpus_version_id,
            ...(input.limits ? { limits: input.limits } : {}),
          }
        : {}),
    };
    draft.runs.push(child);
    const original = draft.proposals.find(
      (p) => p.run_id === parent.id && guards.payload(p.payload),
    );
    if (original)
      draft.proposals.push({
        ...structuredClone(original),
        id: crypto.randomUUID(),
        run_id: child.id,
        conflict_ids: [],
        state: "needs_review",
        version: 1,
      });
    append(draft, child.id, "run_started");
    append(draft, child.id, "review_waiting");
    response = Response.json(child, {
      status: 202,
      headers: { etag: tag(child), location: `/v1/extraction-runs/${child.id}` },
    });
  } else if (resource === "approved-extractions" && operation === "corrections") {
    if (!guards.correction(input)) return fixtureError(422, "VALIDATION_ERROR");
    const prior = draft.versions
      .filter((v) => v.record_id === id)
      .sort((a, b) => b.version - a.version)[0];
    if (!prior) return fixtureError(404, "NOT_FOUND");
    if (headers.get("if-match") !== `"${prior.version}"`)
      return fixtureError(412, "PRECONDITION_FAILED");
    // A correction has no source run of its own. Pinning an arbitrary run would
    // invent provenance, so the prior version's own context carries forward.
    const current = {
      ...approved(input.payload, input.evidence, input.reason, draft.runs[0]!),
      record_id: prior.record_id,
      version: prior.version + 1,
      parent_version_id: prior.version_id,
      ontology_version: prior.ontology_version,
      validation_context: prior.validation_context,
    };
    draft.versions.push(current);
    response = Response.json(current, { status: 201, headers: { etag: `"${current.version}"` } });
  } else if (resource === "extractions" && id === "review") {
    if (!guards.review(input)) return fixtureError(422, "VALIDATION_ERROR");
    const selected = input.extraction_ids.map((id) => draft.proposals.find((p) => p.id === id));
    if (selected.some((p) => !p)) return fixtureError(404, "NOT_FOUND");
    if (selected.some((p) => p!.version !== input.expected_versions[p!.id]))
      return fixtureError(412, "PRECONDITION_FAILED");
    if (selected.some((p) => !["proposed", "needs_review"].includes(p!.state)))
      return fixtureError(409, "CONFLICT");
    for (const resolution of input.conflict_resolution ?? []) {
      const group = draft.conflicts.find((c) => c.id === resolution.conflict_id);
      if (
        !group ||
        group.etag !== resolution.expected_etag ||
        JSON.stringify(group.member_versions) !== JSON.stringify(resolution.member_versions)
      )
        return fixtureError(412, "PRECONDITION_FAILED");
    }
    const result: Schemas["ReviewResult"] = {
      review_id: crypto.randomUUID(),
      action: input.action,
      proposal_states: {},
      proposal_versions: {},
      approved_record_ids: [],
      approved_versions: [],
      resolved_conflicts: [],
    };
    for (const candidate of selected) {
      const p = candidate!;
      const replacement =
        input.action === "edit" ? input.patch.find((e) => e.extraction_id === p.id) : undefined;
      const payload = replacement?.payload ?? p.payload,
        evidence = replacement?.evidence ?? p.evidence;
      if (
        input.action !== "reject" &&
        (!guards.payload(payload) ||
          !evidence.length ||
          (input.action !== "edit" && p.validations.some((v) => v.status === "fail")))
      )
        return fixtureError(422, "VALIDATION_ERROR");
      if (
        input.action !== "reject" &&
        (input.action !== "merge" || input.patch.payload_source_id === p.id)
      ) {
        if (!guards.payload(payload)) return fixtureError(422, "VALIDATION_ERROR");
        const record = approved(
          payload,
          evidence,
          input.reason,
          draft.runs.find((r) => r.id === p.run_id)!,
        );
        draft.versions.push(record);
        result.approved_record_ids.push(record.record_id);
        result.approved_versions.push({
          record_id: record.record_id,
          version_id: record.version_id,
          version: record.version,
          etag: '"1"',
        });
      }
      p.state =
        input.action === "reject"
          ? "rejected"
          : input.action === "merge"
            ? "superseded"
            : "accepted";
      p.version += 1;
      result.proposal_states[p.id] = p.state;
      result.proposal_versions[p.id] = p.version;
    }
    for (const resolution of input.conflict_resolution ?? []) {
      const group = draft.conflicts.find((c) => c.id === resolution.conflict_id)!;
      group.status = "resolved";
      group.etag = `"fixture-group-${crypto.randomUUID()}"`;
      group.resolution = {
        review_id: result.review_id,
        selected_winner_ids: resolution.selected_winner_ids,
        approved_record_ids: result.approved_record_ids,
        reason: resolution.reason,
        actor_user_id: fixtureId(9),
        resolved_at: new Date().toISOString(),
      };
      for (const p of draft.proposals)
        if (Object.hasOwn(group.member_versions, p.id)) group.member_versions[p.id] = p.version;
      result.resolved_conflicts.push({ conflict_id: group.id, etag: group.etag });
    }
    for (const runId of new Set(selected.map((p) => p!.run_id))) {
      append(draft, runId, "review_completed");
      if (
        draft.proposals
          .filter((p) => p.run_id === runId)
          .every((p) => ["accepted", "rejected", "superseded"].includes(p.state))
      ) {
        append(draft, runId, "run_succeeded");
        draft.runs.find((r) => r.id === runId)!.status = "succeeded";
      }
    }
    response = Response.json(result);
  } else return fixtureError(404, "NOT_FOUND");
  Object.assign(state, draft);
  ledger.set(key, { fingerprint, response: response.clone() });
  return response;
}

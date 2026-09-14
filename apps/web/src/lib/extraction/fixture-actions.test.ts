import { describe, expect, it } from "vitest";
import { fixtureFetch, initialFixture, FIXTURE_WORKSPACE, FIXTURE_RECORD } from "./fixture";
import { buildReview } from "./review-state";
import { guards } from "./contracts";
import validationContext from "@fel/contracts/fixtures/extraction-validation-context.json";
const call = (fetcher: typeof fetch, path: string, body?: string, key = "test-key", tag?: string) =>
  fetcher(`http://fixture.invalid/v1/${path}`, {
    method: "POST",
    headers: { "idempotency-key": key, ...(tag ? { "if-match": tag } : {}) },
    body,
  });
describe("synthetic review interaction fixture", () => {
  it("rejects a create-shaped review request without creating a run", async () => {
    const state = initialFixture(),
      before = structuredClone(state),
      run = state.runs[0]!;
    const response = await call(
      fixtureFetch(state),
      "extractions/review",
      JSON.stringify({
        entity_id: run.entity_id,
        as_of: run.as_of,
        modes: run.modes,
        source_span_ids: [state.versions[0]!.evidence[0]!.source_span_id],
      }),
    );
    expect(response.status).toBe(422);
    expect(state).toEqual(before);
  });
  it("preserves explicitly requested run limits and defaults only when omitted", async () => {
    const state = initialFixture(),
      fetcher = fixtureFetch(state),
      run = structuredClone(state.runs[0]!);
    const request = {
      entity_id: run.entity_id,
      as_of: run.as_of,
      modes: run.modes,
      source_span_ids: [state.versions[0]!.evidence[0]!.source_span_id],
    };
    const limits = { max_calls: 2, max_cost_usd: "0.25" };
    const response = await call(
      fetcher,
      `workspaces/${FIXTURE_WORKSPACE}/extraction-runs`,
      JSON.stringify({ ...request, limits }),
    );
    expect(response.status).toBe(202);
    const child = await response.json();
    expect(guards.run(child)).toBe(true);
    expect(child.limits).toEqual(limits);
    expect(response.headers.get("location")).toBe(`/v1/extraction-runs/${child.id}`);
    const defaults = await call(
      fetcher,
      `workspaces/${FIXTURE_WORKSPACE}/extraction-runs`,
      JSON.stringify(request),
      "default-limits",
    );
    expect(defaults.status).toBe(202);
    expect((await defaults.json()).limits).toEqual(run.limits);
    expect(state.runs[0]).toEqual(run);
  });
  it.each(["pinned", "historical null"])(
    "preserves %s correction provenance independently of the first listed run",
    async (history) => {
      const state = initialFixture();
      if (history === "pinned") {
        const pinned = { ...state.versions[0], validation_context: validationContext };
        if (!guards.approved(pinned)) throw new Error("Invalid validation context fixture");
        state.versions[0] = pinned;
      }
      const prior = structuredClone(state.versions[0]!);
      state.runs[0]!.ontology_version = "unrelated-ontology/v99";
      state.runs[0]!.workflow_version = "unrelated-workflow/v99";
      const fetcher = fixtureFetch(state);
      const body = JSON.stringify({
        reason: "Preserve original source provenance",
        payload: prior.payload,
        evidence: prior.evidence,
      });
      const response = await call(
        fetcher,
        `approved-extractions/${FIXTURE_RECORD}/corrections`,
        body,
        "provenance",
        '"1"',
      );
      expect(response.status).toBe(201);
      const current = await response.json();
      expect(guards.approved(current)).toBe(true);
      expect(current.ontology_version).toBe(prior.ontology_version);
      expect(current.validation_context).toEqual(prior.validation_context);
      expect(current.parent_version_id).toBe(prior.version_id);
      expect(current.version_id).not.toBe(prior.version_id);
      expect(state.versions[0]).toEqual(prior);
      expect(
        await (
          await call(
            fetcher,
            `approved-extractions/${FIXTURE_RECORD}/corrections`,
            body,
            "provenance",
            '"1"',
          )
        ).json(),
      ).toEqual(current);
      expect(state.versions).toHaveLength(2);
    },
  );
  it("reviews selected proposals atomically, preserves original payloads and exactly replays", async () => {
    const state = initialFixture(),
      fetcher = fixtureFetch(state),
      original = structuredClone(state.proposals);
    const selected = state.proposals.slice(0, 2);
    const body = buildReview(
      selected,
      "reject",
      "Synthetic reviewed evidence",
      "",
      state.conflicts,
      [],
    );
    const first = await call(fetcher, "extractions/review", body);
    expect(first.status).toBe(200);
    const result = await first.json();
    expect(guards.result(result)).toBe(true);
    expect(await (await call(fetcher, "extractions/review", body)).json()).toEqual(result);
    expect(state.proposals[2]).toEqual(original[2]);
    expect(state.proposals[0]?.payload).toEqual(original[0]?.payload);
    expect((await call(fetcher, "extractions/review", body, "fresh-key")).status).toBe(412);
  });
  it("keeps immutable correction history and rejects stale head before mutation", async () => {
    const state = initialFixture(),
      fetcher = fixtureFetch(state),
      before = structuredClone(state.versions);
    const current = state.versions[0]!;
    const body = JSON.stringify({
      reason: "Synthetic correction",
      payload: current.payload,
      evidence: current.evidence,
    });
    const first = await call(
      fetcher,
      `approved-extractions/${FIXTURE_RECORD}/corrections`,
      body,
      "correct",
      '"1"',
    );
    expect(first.status).toBe(201);
    expect(first.headers.get("location")).toBe(
      `/v1/approved-extractions/${FIXTURE_RECORD}/versions/${state.versions[1]!.version_id}`,
    );
    expect(guards.approved(await first.json())).toBe(true);
    expect(state.versions[0]).toEqual(before[0]);
    expect(
      (
        await call(
          fetcher,
          `approved-extractions/${FIXTURE_RECORD}/corrections`,
          body,
          "stale",
          '"1"',
        )
      ).status,
    ).toBe(412);
    expect(state.versions).toHaveLength(2);
  });
  it("creates a parent-linked child without changing parent proposal history", async () => {
    const state = initialFixture(),
      fetcher = fixtureFetch(state),
      before = structuredClone(state.proposals);
    const parent = state.runs[0]!;
    const response = await call(
      fetcher,
      `extraction-runs/${parent.id}/rerun`,
      JSON.stringify({ reason: "Synthetic rerun" }),
    );
    const child = await response.json();
    expect(response.status).toBe(202);
    expect(guards.run(child)).toBe(true);
    expect(child.parent_run_id).toBe(parent.id);
    expect(state.proposals.slice(0, before.length)).toEqual(before);
    expect(
      (await fetcher(`http://fixture.invalid/v1/workspaces/${FIXTURE_WORKSPACE}/extraction-runs`))
        .status,
    ).toBe(200);
  });
});

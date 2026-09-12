import { describe, expect, it } from "vitest";
import { fixtureFetch, initialFixture, FIXTURE_WORKSPACE, FIXTURE_RECORD } from "./fixture";
import { buildReview } from "./review-state";
import { guards } from "./contracts";
const call = (fetcher: typeof fetch, path: string, body?: string, key = "test-key", tag?: string) =>
  fetcher(`http://fixture.invalid/v1/${path}`, {
    method: "POST",
    headers: { "idempotency-key": key, ...(tag ? { "if-match": tag } : {}) },
    body,
  });
describe("synthetic review interaction fixture", () => {
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

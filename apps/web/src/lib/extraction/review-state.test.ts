import { describe, expect, it } from "vitest";
import command from "@fel/contracts/fixtures/extraction-review-command.json";
import { buildReview, prepareRequest } from "./review-state";
import { initialFixture } from "./fixture";
describe("intentional extraction review", () => {
  it("names only selected IDs/versions and preserves explicit full replacement JSON bytes", () => {
    const p = initialFixture().proposals[0]!;
    const edit = JSON.stringify([
      { extraction_id: p.id, payload: p.payload, evidence: p.evidence },
    ]).replace('"qualifiers":{}', '"qualifiers":{"exact":9007199254740993}');
    const body = buildReview([p], "edit", "Source rechecked", edit, initialFixture().conflicts, [
      p.id,
    ]);
    expect(body).toContain("9007199254740993");
    expect(JSON.parse(body).extraction_ids).toEqual([p.id]);
    expect(JSON.parse(body).expected_versions).toEqual({ [p.id]: p.version });
  });
  it("does not automatically convert candidate display fields into edit inputs", () => {
    const p = initialFixture().proposals[2]!;
    expect(() =>
      buildReview(
        [p],
        "edit",
        "Explicit correction",
        JSON.stringify([{ extraction_id: p.id, payload: p.payload, evidence: p.evidence }]),
        [],
        [],
      ),
    ).toThrow();
  });
  it("requires explicit selected merge source and winner membership", () => {
    const state = initialFixture();
    expect(() =>
      buildReview(state.proposals.slice(0, 2), "merge", "Merge", "{}", state.conflicts, []),
    ).toThrow();
    const body = buildReview(
      state.proposals.slice(0, 2),
      "merge",
      "Same definition",
      JSON.stringify({ payload_source_id: state.proposals[0]!.id }),
      state.conflicts,
      [state.proposals[0]!.id],
    );
    expect(JSON.parse(body).conflict_resolution[0].member_versions).toEqual(
      state.conflicts[0]!.member_versions,
    );
  });
  it("reuses a key only for identical path/method/preconditions/body", () => {
    const first = prepareRequest("review", "POST", JSON.stringify(command), null);
    expect(prepareRequest("review", "POST", first.body, null, first)).toBe(first);
    expect(prepareRequest("review", "POST", first.body + " ", null, first).key).not.toBe(first.key);
    expect(prepareRequest("review", "POST", first.body, '"2"', first).key).not.toBe(first.key);
  });
});

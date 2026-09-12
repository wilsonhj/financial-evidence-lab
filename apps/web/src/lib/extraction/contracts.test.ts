import { describe, expect, it } from "vitest";
import candidate from "@fel/contracts/fixtures/extraction-candidate-fields.json";
import proposal from "@fel/contracts/fixtures/extraction-proposal.json";
import payload from "@fel/contracts/fixtures/extraction-payload.json";
import conflict from "@fel/contracts/fixtures/extraction-conflict.json";
import event from "@fel/contracts/fixtures/extraction-event.json";
import { guards } from "./contracts";

describe("extraction response boundary", () => {
  it("accepts canonical candidate, strict payload and complete conflict without schema metadata", () => {
    expect(guards.proposal(proposal)).toBe(true);
    expect(guards.proposal({ ...proposal, payload })).toBe(true);
    expect(guards.conflict(conflict)).toBe(true);
    expect(guards.event(event)).toBe(true);
  });
  it.each([
    null,
    [],
    "payload",
    10,
    { ...candidate, fields: { value: 4 } },
    { ...candidate, fields: { secret: "hidden" } },
    { ...candidate, fields: { value: "x".repeat(65537) } },
    { ...candidate, $defs: {} },
  ])("rejects malformed proposal payload %j", (value) => {
    expect(guards.proposal({ ...proposal, payload: value })).toBe(false);
  });
  it("allows zero evidence and nullable uncalibrated confidence only on reads", () => {
    expect(guards.proposal({ ...proposal, evidence: [], record_confidence: null })).toBe(true);
    expect(guards.correction({ reason: "Fix", payload: candidate, evidence: [] })).toBe(false);
  });
  it("rejects unknown envelope fields, bad IDs/versions and unsafe event IDs", () => {
    expect(guards.proposal({ ...proposal, internal: "private" })).toBe(false);
    expect(guards.proposal({ ...proposal, id: "bad" })).toBe(false);
    expect(guards.proposal({ ...proposal, version: 0 })).toBe(false);
    expect(guards.event({ ...event, id: 9007199254740992 })).toBe(false);
  });
  it("enforces page lengths and opaque cursor bounds", () => {
    const page = { items: [proposal], limit: 1, next_cursor: null, previous_cursor: null };
    expect(guards.proposals(page)).toBe(true);
    expect(guards.proposals({ ...page, items: [proposal, proposal] })).toBe(false);
    expect(guards.proposals({ ...page, next_cursor: "x".repeat(2049) })).toBe(false);
    expect(guards.proposals({ ...page, items: [], next_cursor: "cursor" })).toBe(false);
  });
});

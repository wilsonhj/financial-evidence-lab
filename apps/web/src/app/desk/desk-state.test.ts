import { describe, expect, it } from "vitest";

import {
  buildAppliedFacts,
  buildReviewDecision,
  canApplyApprovedFacts,
  canSaveResolution,
  isValidDeskTheme,
  resolveDeskTheme,
  resolveVisibleClaimId,
  writeStoredTheme,
  type GuidanceApproval,
} from "./desk-state";

const approvals: GuidanceApproval[] = [
  { claimId: "C-109-revenue", approved: true },
  { claimId: "C-109-gross-margin", approved: true },
];

describe("desk theme selection", () => {
  it("only accepts the three supported persisted appearances", () => {
    expect(isValidDeskTheme("system")).toBe(true);
    expect(isValidDeskTheme("light")).toBe(true);
    expect(isValidDeskTheme("oled")).toBe(true);
    expect(isValidDeskTheme("dark")).toBe(false);
    expect(resolveDeskTheme("oled")).toBe("oled");
    expect(resolveDeskTheme("dark")).toBe("system");
  });

  it("treats localStorage as a best-effort mirror only", () => {
    const blocked = {
      setItem(): void {
        throw new Error("The operation is insecure.");
      },
    };
    expect(() => writeStoredTheme("light", blocked)).not.toThrow();
  });
});

describe("approved-facts gate", () => {
  it("requires an explicit evidence source and substantive rationale", () => {
    expect(canSaveResolution(null, "Filed disclosure governs the model.")).toBe(false);
    expect(canSaveResolution("sec-10q-nrr", "Filed source")).toBe(false);
    expect(canSaveResolution("sec-10q-nrr", "Filed disclosure governs the model.")).toBe(true);
  });

  it("builds an evidence-id-backed artifact before facts can be applied", () => {
    const decision = buildReviewDecision("sec-10q-nrr", "Filed disclosure governs the model.");
    expect(decision).toEqual({
      conflictId: "C-104",
      sourceId: "sec-10q-nrr",
      rationale: "Filed disclosure governs the model.",
    });
    expect(canApplyApprovedFacts(null, approvals)).toBe(false);
    expect(
      canApplyApprovedFacts(decision, [{ ...approvals[0]!, approved: false }, approvals[1]!]),
    ).toBe(false);
    expect(canApplyApprovedFacts(decision, [approvals[0]!, approvals[0]!])).toBe(false);
    expect(buildAppliedFacts(decision, approvals)).toEqual({
      modelVersion: "v19",
      decision,
      approvalIds: ["C-109-revenue", "C-109-gross-margin"],
    });
  });
});

describe("claim filtering", () => {
  it("keeps the current claim only when it is still visible", () => {
    expect(resolveVisibleClaimId("nrr", ["guidance"])).toBeNull();
    expect(resolveVisibleClaimId("guidance", ["guidance"])).toBe("guidance");
    expect(resolveVisibleClaimId("nrr", [])).toBeNull();
  });
});

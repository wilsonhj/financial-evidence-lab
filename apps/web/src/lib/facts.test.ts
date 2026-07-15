import { describe, expect, it } from "vitest";

import type { FinancialFactRecord, NormalizedFinancialFact } from "./contracts";
import {
  duplicateGroupIndex,
  factIdentityKey,
  formatScaledValue,
  groupDuplicateFacts,
  scaledDecimal,
} from "./facts";

const ENTITY = "11111111-1111-4111-8111-111111111111";
const SPAN = "cccccccc-0000-4000-8000-00000000ffff";

function fact(overrides: Partial<NormalizedFinancialFact> = {}): NormalizedFinancialFact {
  return {
    entity_id: ENTITY,
    concept: "us-gaap:Revenues",
    value: "100",
    unit: "USD",
    scale: 0,
    period: { type: "duration", start: "2026-01-01", end: "2026-03-31" },
    dimensions: {},
    source_span_id: SPAN,
    reported_or_derived: "reported",
    ...overrides,
  };
}

function record(id: string, overrides: Partial<NormalizedFinancialFact> = {}): FinancialFactRecord {
  return {
    id,
    document_version_id: "aaaaaaaa-0000-4000-8000-000000001001",
    fact: fact(overrides),
  };
}

describe("scaledDecimal", () => {
  it("applies positive powers of ten without floats", () => {
    expect(scaledDecimal("1250", 6)).toBe("1250000000");
    expect(scaledDecimal("86.4", 6)).toBe("86400000");
    expect(scaledDecimal("1250000000", 0)).toBe("1250000000");
  });

  it("applies negative scales", () => {
    expect(scaledDecimal("52", -2)).toBe("0.52");
    expect(scaledDecimal("1234", -1)).toBe("123.4");
  });

  it("canonicalizes zeros and signs", () => {
    expect(scaledDecimal("0.520", 0)).toBe("0.52");
    expect(scaledDecimal("-86.4", 6)).toBe("-86400000");
    expect(scaledDecimal("0", 6)).toBe("0");
    expect(scaledDecimal("-0", 3)).toBe("0");
  });

  it("stays exact beyond float precision", () => {
    expect(scaledDecimal("9007199254740993", 2)).toBe("900719925474099300");
  });

  it("rejects non-decimal strings", () => {
    expect(() => scaledDecimal("1e9", 0)).toThrow(/decimal/i);
    expect(() => scaledDecimal("", 0)).toThrow(/decimal/i);
  });
});

describe("formatScaledValue", () => {
  it("groups digits for display", () => {
    expect(formatScaledValue(fact({ value: "1250", scale: 6 }))).toBe("1,250,000,000");
    expect(formatScaledValue(fact({ value: "-86.45", scale: 3 }))).toBe("-86,450");
    expect(formatScaledValue(fact({ value: "0.52", scale: 0 }))).toBe("0.52");
  });
});

describe("factIdentityKey", () => {
  it("ignores value and scale but keys on dimensions and period", () => {
    expect(factIdentityKey(fact({ value: "1250", scale: 6 }))).toBe(
      factIdentityKey(fact({ value: "1243000000", scale: 0 })),
    );
    expect(factIdentityKey(fact({ dimensions: { segment: "Instruments" } }))).not.toBe(
      factIdentityKey(fact()),
    );
    expect(factIdentityKey(fact({ period: { type: "instant", instant: "2026-03-31" } }))).not.toBe(
      factIdentityKey(fact()),
    );
  });

  it("treats dimension ordering as irrelevant", () => {
    expect(factIdentityKey(fact({ dimensions: { a: "1", b: "2" } }))).toBe(
      factIdentityKey(fact({ dimensions: { b: "2", a: "1" } })),
    );
  });
});

describe("groupDuplicateFacts", () => {
  it("flags duplicates whose canonical values disagree", () => {
    const groups = groupDuplicateFacts([
      record("f1", { value: "1250", scale: 6 }),
      record("f2", { value: "1243000000", scale: 0 }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.status).toBe("conflicting");
    expect(groups[0]!.canonicalValues.sort()).toEqual(["1243000000", "1250000000"]);
  });

  it("treats scale-only representation differences as consistent", () => {
    const groups = groupDuplicateFacts([
      record("f1", { value: "1250", scale: 6 }),
      record("f2", { value: "1250000000", scale: 0 }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.status).toBe("consistent");
    expect(groups[0]!.canonicalValues).toEqual(["1250000000"]);
  });

  it("does not group facts with different dimensions or concepts", () => {
    const groups = groupDuplicateFacts([
      record("f1"),
      record("f2", { dimensions: { segment: "Instruments" } }),
      record("f3", { concept: "us-gaap:NetIncomeLoss" }),
    ]);
    expect(groups).toEqual([]);
  });

  it("indexes group membership by fact record id", () => {
    const groups = groupDuplicateFacts([
      record("f1", { value: "1250", scale: 6 }),
      record("f2", { value: "1243000000", scale: 0 }),
      record("f3", { concept: "us-gaap:NetIncomeLoss" }),
    ]);
    const index = duplicateGroupIndex(groups);
    expect(index.get("f1")?.status).toBe("conflicting");
    expect(index.get("f2")?.status).toBe("conflicting");
    expect(index.has("f3")).toBe(false);
  });
});

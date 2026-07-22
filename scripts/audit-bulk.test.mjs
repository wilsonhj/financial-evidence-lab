import { describe, expect, it } from "vitest";

import { evaluate } from "./audit-bulk.mjs";

// A bulk-endpoint-shaped advisory for `pkg` carrying GHSA id `id`.
const advisory = (pkg, id) => ({
  [pkg]: [
    {
      id: 1,
      url: `https://github.com/advisories/${id}`,
      severity: "high",
      title: `flaw in ${pkg}`,
    },
  ],
});

const NOW = new Date("2026-07-22T00:00:00Z");
const FUTURE = "2026-10-20";
const PAST = "2026-01-01";

const entry = (over = {}) => ({
  id: "GHSA-v2hh-gcrm-f6hx",
  package: "fast-uri",
  reason: "transitive, no non-breaking fix",
  reviewBy: FUTURE,
  ...over,
});

describe("audit-bulk evaluate", () => {
  it("suppresses an advisory matched by an active allowlist entry", () => {
    const r = evaluate(advisory("fast-uri", "GHSA-v2hh-gcrm-f6hx"), [entry()], NOW);
    expect(r.ok).toBe(true);
    expect(r.blocking).toHaveLength(0);
    expect(r.allowlisted).toEqual([
      {
        name: "fast-uri",
        id: "GHSA-v2hh-gcrm-f6hx",
        reviewBy: FUTURE,
        reason: "transitive, no non-breaking fix",
      },
    ]);
  });

  it("fails closed when an allowlist entry is expired", () => {
    const r = evaluate(
      advisory("fast-uri", "GHSA-v2hh-gcrm-f6hx"),
      [entry({ reviewBy: PAST })],
      NOW,
    );
    expect(r.ok).toBe(false);
    expect(r.expired).toEqual([{ id: "GHSA-v2hh-gcrm-f6hx", package: "fast-uri", reviewBy: PAST }]);
    // An expired entry does not suppress; the advisory is not counted as allowlisted.
    expect(r.allowlisted).toHaveLength(0);
  });

  it("fails when an advisory has no allowlist entry", () => {
    const r = evaluate(advisory("left-pad", "GHSA-aaaa-bbbb-cccc"), [entry()], NOW);
    expect(r.ok).toBe(false);
    expect(r.blocking.map((b) => b.name)).toEqual(["left-pad"]);
  });

  it("fails closed on a malformed allowlist entry (missing reason)", () => {
    const broken = entry();
    delete broken.reason;
    const r = evaluate({}, [broken], NOW);
    expect(r.ok).toBe(false);
    expect(r.malformed).toHaveLength(1);
    expect(r.malformed[0].missing).toContain("reason");
  });

  it("fails closed on a malformed reviewBy date", () => {
    const r = evaluate({}, [entry({ reviewBy: "not-a-date" })], NOW);
    expect(r.ok).toBe(false);
    expect(r.malformed).toHaveLength(1);
  });

  it("does not suppress when the id matches but the package does not", () => {
    const r = evaluate(advisory("other-pkg", "GHSA-v2hh-gcrm-f6hx"), [entry()], NOW);
    expect(r.ok).toBe(false);
    expect(r.blocking.map((b) => b.name)).toEqual(["other-pkg"]);
  });

  it("passes cleanly with no advisories and an empty allowlist", () => {
    const r = evaluate({}, [], NOW);
    expect(r.ok).toBe(true);
    expect(r.blocking).toHaveLength(0);
    expect(r.allowlisted).toHaveLength(0);
  });
});

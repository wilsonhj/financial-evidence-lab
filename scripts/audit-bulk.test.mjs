import { describe, expect, it } from "vitest";

import { evaluate, fetchBulkAdvisories } from "./audit-bulk.mjs";

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

  // A malformed advisory response (null/array/primitive) must fail closed, not
  // read as "zero advisories" — otherwise a 200-with-null body silently passes.
  it.each([
    ["null", null],
    ["undefined", undefined],
    ["an array", []],
    ["a string", "oops"],
  ])("fails closed when the advisory response is %s", (_label, body) => {
    const r = evaluate(body, [], NOW);
    expect(r.ok).toBe(false);
    expect(r.configError).toBe("malformed advisory response body");
  });

  // A non-array allowlist is broken config: fail closed cleanly (exit 2 via
  // configError), never crash on a non-iterable.
  it.each([
    ["an object", {}],
    ["a number", 42],
    ["a string", "oops"],
  ])("fails closed (no throw) when the allowlist is %s", (_label, badAllowlist) => {
    const r = evaluate({}, badAllowlist, NOW);
    expect(r.ok).toBe(false);
    expect(r.configError).toBe("audit-allowlist.json is not an array");
  });

  // Per-advisory matching: allowlisting one GHSA on a package must not suppress
  // a *different* advisory on the same package (guards against a future refactor
  // to per-package matching that would over-suppress).
  it("suppresses only the allowlisted advisory when a package has two", () => {
    const advisories = {
      "fast-uri": [
        { url: "https://github.com/advisories/GHSA-v2hh-gcrm-f6hx", severity: "high", title: "a" },
        { url: "https://github.com/advisories/GHSA-zzzz-zzzz-zzzz", severity: "high", title: "b" },
      ],
    };
    const r = evaluate(advisories, [entry()], NOW);
    expect(r.ok).toBe(false);
    expect(r.allowlisted.map((a) => a.id)).toEqual(["GHSA-v2hh-gcrm-f6hx"]);
    expect(r.blocking.map((b) => b.id)).toEqual(["GHSA-zzzz-zzzz-zzzz"]);
  });
});

// The bulk POST is fail-closed (a 503 must not pass as "zero advisories") but a
// single registry blip must not fail the JS CI job either. fetchBulkAdvisories
// retries transient statuses, then still throws if they persist.
const jsonResponse = (status, body = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

describe("fetchBulkAdvisories", () => {
  it("retries a 503 and returns the subsequent 200 body", async () => {
    const calls = [];
    const fetchImpl = async () => {
      calls.push(calls.length + 1);
      if (calls.length === 1) return jsonResponse(503);
      return jsonResponse(200, { "left-pad": [] });
    };

    const body = await fetchBulkAdvisories(
      { "left-pad": ["1.0.0"] },
      { fetchImpl, sleep: async () => {}, log: () => {} },
    );

    expect(body).toEqual({ "left-pad": [] });
    expect(calls).toHaveLength(2);
  });

  it("does not retry a 410 (retired endpoint is not transient)", async () => {
    const calls = [];
    const fetchImpl = async () => {
      calls.push(calls.length + 1);
      return jsonResponse(410);
    };

    await expect(
      fetchBulkAdvisories(
        { "left-pad": ["1.0.0"] },
        { fetchImpl, sleep: async () => {}, log: () => {} },
      ),
    ).rejects.toMatchObject({ status: 410, message: "bulk advisory endpoint responded 410" });
    expect(calls).toHaveLength(1);
  });

  it("retries a thrown fetch error and returns the subsequent 200 body", async () => {
    const calls = [];
    const fetchImpl = async () => {
      calls.push(calls.length + 1);
      if (calls.length === 1) throw new TypeError("fetch failed");
      return jsonResponse(200, { "left-pad": [] });
    };

    const body = await fetchBulkAdvisories(
      { "left-pad": ["1.0.0"] },
      { fetchImpl, sleep: async () => {}, log: () => {} },
    );

    expect(body).toEqual({ "left-pad": [] });
    expect(calls).toHaveLength(2);
  });

  it("fails closed after three 503 responses", async () => {
    const calls = [];
    const fetchImpl = async () => {
      calls.push(calls.length + 1);
      return jsonResponse(503);
    };

    await expect(
      fetchBulkAdvisories(
        { "left-pad": ["1.0.0"] },
        { fetchImpl, sleep: async () => {}, log: () => {} },
      ),
    ).rejects.toMatchObject({ status: 503, message: "bulk advisory endpoint responded 503" });
    expect(calls).toHaveLength(3);
  });
});

import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

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
// retries transient statuses and unreadable responses, then still throws if
// they persist; the final describe covers the other half of that claim — that
// main() turns the throw into a failed gate rather than a clean pass.
const jsonResponse = (status, body = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

describe("fetchBulkAdvisories", () => {
  it("retries a 503, asks the right endpoint the right question, and returns the 200 body", async () => {
    const calls = [];
    // The args are captured, not ignored. Without asserting them the suite
    // cannot see the one mutation that fails OPEN: replace the POST body with
    // "{}" and the gate stops asking about any package, so a critical advisory
    // becomes "No blocking vulnerabilities found" and exit 0 — with every test
    // still green. A stub that drops its arguments verifies how the code reacts
    // to answers while never checking what it asked.
    const fetchImpl = async (url, init) => {
      calls.push({ url, init });
      if (calls.length === 1) return jsonResponse(503);
      return jsonResponse(200, { "left-pad": [] });
    };

    const body = await fetchBulkAdvisories(
      { "left-pad": ["1.0.0"] },
      { fetchImpl, sleep: async () => {}, log: () => {} },
    );

    expect(body).toEqual({ "left-pad": [] });
    expect(calls).toHaveLength(2);
    for (const call of calls) {
      expect(call.url).toBe("https://registry.npmjs.org/-/npm/v1/security/advisories/bulk");
      expect(call.init.method).toBe("POST");
      expect(JSON.parse(call.init.body)).toEqual({ "left-pad": ["1.0.0"] });
      // Each attempt carries its own deadline; a shared one would expire
      // mid-sequence and abort the later attempts instantly.
      expect(call.init.signal).toBeInstanceOf(globalThis.AbortSignal);
    }
    expect(calls[0].init.signal).not.toBe(calls[1].init.signal);
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
  it("retries a body that arrives unreadable, then returns the good one", async () => {
    // A socket dropped mid-body surfaces as a rejected json() on an ok
    // response; one dropped before the headers surfaces at the fetch. Both are
    // the registry blip this retry exists to absorb, so both must retry.
    const calls = [];
    const fetchImpl = async () => {
      calls.push(calls.length + 1);
      const attempt = calls.length;
      return {
        ok: true,
        status: 200,
        json: async () => {
          if (attempt === 1) throw new SyntaxError("Unexpected end of JSON input");
          return { "left-pad": [] };
        },
      };
    };

    const body = await fetchBulkAdvisories(
      { "left-pad": ["1.0.0"] },
      { fetchImpl, sleep: async () => {}, log: () => {} },
    );

    expect(body).toEqual({ "left-pad": [] });
    expect(calls).toHaveLength(2);
  });

  it("fails closed on a persistently unreadable body, and does not call it a failed request", async () => {
    const calls = [];
    const fetchImpl = async () => {
      calls.push(calls.length + 1);
      return {
        ok: true,
        status: 200,
        json: async () => {
          throw new SyntaxError("Unexpected token < in JSON at position 0");
        },
      };
    };

    // The request returned 200. Reporting it as a failed request would send an
    // operator to look at connectivity rather than at the response body.
    await expect(
      fetchBulkAdvisories(
        { "left-pad": ["1.0.0"] },
        { fetchImpl, sleep: async () => {}, log: () => {} },
      ),
    ).rejects.toThrow(/returned 200 with an unreadable body/);
    expect(calls).toHaveLength(3);
  });

  it("surfaces err.cause, where node's fetch puts the reason that identifies the failure", async () => {
    const logged = [];
    const fetchImpl = async () => {
      const err = new TypeError("fetch failed");
      err.cause = new Error("getaddrinfo ENOTFOUND registry.npmjs.org");
      throw err;
    };

    await expect(
      fetchBulkAdvisories(
        { "left-pad": ["1.0.0"] },
        { fetchImpl, sleep: async () => {}, log: (m) => logged.push(m) },
      ),
    ).rejects.toThrow("fetch failed");
    // Without the cause, DNS, TLS and a refused proxy all read "fetch failed".
    expect(logged[0]).toContain("getaddrinfo ENOTFOUND registry.npmjs.org");
  });
});

// The tests above prove fetchBulkAdvisories THROWS. That only matters if the
// throw becomes a failed gate: evaluate({}, [], now) returns ok:true, so an
// empty map is a legitimate clean pass, and the only thing standing between a
// persistent 503 and a green build is main()'s catch. These run the real script
// end to end with a stubbed global fetch and assert the process exit code.
describe("main() fail-closed exit code", () => {
  const runWithStubbedFetch = (stub) => {
    const dir = mkdtempSync(join(tmpdir(), "audit-bulk-"));
    const script = fileURLToPath(new URL("./audit-bulk.mjs", import.meta.url));
    const harness = join(dir, "harness.mjs");
    writeFileSync(
      harness,
      `globalThis.fetch = ${stub};\n` +
        `process.argv[1] = ${JSON.stringify(script)};\n` +
        `await import(${JSON.stringify(script)});\n`,
    );
    try {
      execFileSync(process.execPath, [harness], {
        cwd: fileURLToPath(new URL("..", import.meta.url)),
        stdio: "pipe",
      });
      return 0;
    } catch (err) {
      return err.status;
    }
  };

  it("exits 2 when every advisory request is a transient 503", () => {
    expect(
      runWithStubbedFetch("async () => ({ ok: false, status: 503, json: async () => ({}) })"),
    ).toBe(2);
  }, 30000);

  it("exits 2 on a retired endpoint (410) rather than retrying it green", () => {
    expect(
      runWithStubbedFetch("async () => ({ ok: false, status: 410, json: async () => ({}) })"),
    ).toBe(2);
  }, 30000);
});

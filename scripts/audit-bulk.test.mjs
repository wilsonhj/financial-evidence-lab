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
// retries transient statuses, then still throws if they persist.
const jsonResponse = (status, body = {}, headers = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: { get: (name) => headers[name.toLowerCase()] ?? null },
  json: async () => body,
});

describe("fetchBulkAdvisories", () => {
  it("retries a 503 with the exact request and a distinct signal per attempt", async () => {
    const calls = [];
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

  it("includes err.cause diagnostics when a network failure is retried", async () => {
    const logged = [];
    const fetchImpl = async () => {
      const err = new TypeError("fetch failed");
      err.cause = new Error("getaddrinfo ENOTFOUND registry.npmjs.org");
      throw err;
    };

    await expect(
      fetchBulkAdvisories(
        { "left-pad": ["1.0.0"] },
        { fetchImpl, sleep: async () => {}, log: (message) => logged.push(message) },
      ),
    ).rejects.toThrow("fetch failed");
    expect(logged[0]).toContain("getaddrinfo ENOTFOUND registry.npmjs.org");
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

  it.each([
    ["delta-seconds", "7", () => 0, 10_000, 7000],
    ["HTTP-date", "Wed, 22 Jul 2026 00:00:09 GMT", NOW, 10_000, 9000],
    ["malformed", "eventually", () => 0, 10_000, 1000],
    ["configured cap", "120", () => 0, 2500, 2500],
  ])("uses Retry-After %s", async (_label, retryAfter, now, maximum, expected) => {
    const delays = [];
    let calls = 0;
    const fetchImpl = async () => {
      calls += 1;
      return calls === 1
        ? jsonResponse(429, {}, { "retry-after": retryAfter })
        : jsonResponse(200, { recovered: [] });
    };

    await expect(
      fetchBulkAdvisories(
        { recovered: ["1.0.0"] },
        {
          fetchImpl,
          now,
          maxRetryDelayMs: maximum,
          sleep: async (ms) => delays.push(ms),
          log: () => {},
        },
      ),
    ).resolves.toEqual({ recovered: [] });
    expect(delays).toEqual([expected]);
  });

  it("does not retry another permanent 4xx response", async () => {
    let calls = 0;
    const fetchImpl = async () => {
      calls += 1;
      return jsonResponse(404);
    };

    await expect(
      fetchBulkAdvisories({ pkg: ["1.0.0"] }, { fetchImpl, sleep: async () => {}, log: () => {} }),
    ).rejects.toMatchObject({ status: 404 });
    expect(calls).toBe(1);
  });

  it.each([502, 504])("retries a %i response", async (status) => {
    let calls = 0;
    const fetchImpl = async () =>
      ++calls === 1 ? jsonResponse(status) : jsonResponse(200, { recovered: [] });

    await expect(
      fetchBulkAdvisories(
        { recovered: ["1.0.0"] },
        { fetchImpl, sleep: async () => {}, log: () => {} },
      ),
    ).resolves.toEqual({ recovered: [] });
    expect(calls).toBe(2);
  });

  it("retries an attempt timeout, clears its timers, and can recover", async () => {
    let calls = 0;
    let timers = 0;
    const cleared = [];
    const timerDelays = [];
    const setTimeoutImpl = (callback, ms) => {
      const id = ++timers;
      timerDelays.push(ms);
      if (id === 1) callback();
      return id;
    };
    const fetchImpl = async (_url, { signal }) => {
      calls += 1;
      if (signal.aborted) throw signal.reason;
      return jsonResponse(200, { recovered: [] });
    };

    await expect(
      fetchBulkAdvisories(
        { recovered: ["1.0.0"] },
        {
          fetchImpl,
          sleep: async () => {},
          log: () => {},
          requestTimeoutMs: 1_000_000,
          setTimeoutImpl,
          clearTimeoutImpl: (id) => cleared.push(id),
        },
      ),
    ).resolves.toEqual({ recovered: [] });
    expect(calls).toBe(2);
    expect(cleared).toEqual([1, 2]);
    expect(timerDelays).toEqual([30_000, 30_000]);
  });

  it("fails closed when every attempt times out", async () => {
    let calls = 0;
    const fetchImpl = async () => {
      calls += 1;
      return new Promise(() => {});
    };

    await expect(
      fetchBulkAdvisories(
        { pkg: ["1.0.0"] },
        {
          fetchImpl,
          sleep: async () => {},
          log: () => {},
          requestTimeoutMs: 25,
          setTimeoutImpl: (callback) => {
            callback();
            return calls;
          },
          clearTimeoutImpl: () => {},
        },
      ),
    ).rejects.toMatchObject({ name: "TimeoutError" });
    expect(calls).toBe(3);
  });

  it("keeps the attempt timeout active through a stalled response body and retries", async () => {
    const timeoutCallbacks = [];
    const cleared = [];
    let calls = 0;
    const fetchImpl = async () => {
      calls += 1;
      if (calls === 1) {
        return {
          ...jsonResponse(200),
          json: () => {
            timeoutCallbacks[0]();
            return new Promise(() => {});
          },
        };
      }
      return jsonResponse(200, { recovered: [] });
    };

    await expect(
      fetchBulkAdvisories(
        { recovered: ["1.0.0"] },
        {
          fetchImpl,
          sleep: async () => {
            expect(cleared).toEqual([1]);
          },
          log: () => {},
          setTimeoutImpl: (callback) => {
            timeoutCallbacks.push(callback);
            return timeoutCallbacks.length;
          },
          clearTimeoutImpl: (id) => cleared.push(id),
        },
      ),
    ).resolves.toEqual({ recovered: [] });
    expect(calls).toBe(2);
    expect(cleared).toEqual([1, 2]);
  });

  it("retries a body read failure and returns a subsequent readable body", async () => {
    let calls = 0;
    const fetchImpl = async () => {
      const attempt = ++calls;
      return {
        ...jsonResponse(200, { "left-pad": [] }),
        json: async () => {
          if (attempt === 1) throw new SyntaxError("Unexpected end of JSON input");
          return { "left-pad": [] };
        },
      };
    };

    await expect(
      fetchBulkAdvisories(
        { "left-pad": ["1.0.0"] },
        { fetchImpl, sleep: async () => {}, log: () => {} },
      ),
    ).resolves.toEqual({ "left-pad": [] });
    expect(calls).toBe(2);
  });

  it("fails closed with body diagnostics after three unreadable 200 responses", async () => {
    let calls = 0;
    const parseError = new SyntaxError("Unexpected token < in JSON");
    const fetchImpl = async () => {
      calls += 1;
      return {
        ...jsonResponse(200),
        json: async () => {
          throw parseError;
        },
      };
    };

    await expect(
      fetchBulkAdvisories(
        { "left-pad": ["1.0.0"] },
        { fetchImpl, sleep: async () => {}, log: () => {} },
      ),
    ).rejects.toMatchObject({
      message: expect.stringContaining("returned 200 with an unreadable body"),
      cause: parseError,
    });
    expect(calls).toBe(3);
  });

  it("preserves a caller abort and does not retry it", async () => {
    const caller = new globalThis.AbortController();
    const reason = new Error("stop requested");
    let calls = 0;
    const fetchImpl = async (_url, { signal }) => {
      calls += 1;
      caller.abort(reason);
      throw signal.reason;
    };

    await expect(
      fetchBulkAdvisories(
        { pkg: ["1.0.0"] },
        {
          fetchImpl,
          signal: caller.signal,
          sleep: async () => {},
          log: () => {},
          setTimeoutImpl: () => 1,
          clearTimeoutImpl: () => {},
        },
      ),
    ).rejects.toBe(reason);
    expect(calls).toBe(1);
  });

  it("interrupts response body parsing with the original caller abort", async () => {
    const caller = new globalThis.AbortController();
    const reason = new Error("stop reading");
    let calls = 0;
    const fetchImpl = async () => {
      calls += 1;
      return {
        ...jsonResponse(200),
        json: () => {
          caller.abort(reason);
          return new Promise(() => {});
        },
      };
    };

    await expect(
      fetchBulkAdvisories(
        { pkg: ["1.0.0"] },
        {
          fetchImpl,
          signal: caller.signal,
          sleep: async () => {},
          log: () => {},
          setTimeoutImpl: () => 1,
          clearTimeoutImpl: () => {},
        },
      ),
    ).rejects.toBe(reason);
    expect(calls).toBe(1);
  });

  it.each([
    ["HTTP-status", async () => jsonResponse(503)],
    ["thrown-error", async () => Promise.reject(new TypeError("offline"))],
  ])(
    "interrupts %s backoff with the original caller abort after request cleanup",
    async (_label, fetchImpl) => {
      const caller = new globalThis.AbortController();
      const reason = new Error("cancel backoff");
      const cleared = [];
      const activeListeners = new Set();
      const addEventListener = caller.signal.addEventListener.bind(caller.signal);
      const removeEventListener = caller.signal.removeEventListener.bind(caller.signal);
      caller.signal.addEventListener = (type, listener, options) => {
        if (type === "abort") activeListeners.add(listener);
        return addEventListener(type, listener, options);
      };
      caller.signal.removeEventListener = (type, listener, options) => {
        if (type === "abort") activeListeners.delete(listener);
        return removeEventListener(type, listener, options);
      };

      await expect(
        fetchBulkAdvisories(
          { pkg: ["1.0.0"] },
          {
            fetchImpl,
            signal: caller.signal,
            sleep: () => {
              expect(cleared).toEqual([1]);
              expect(activeListeners.size).toBe(1);
              caller.abort(reason);
              return new Promise(() => {});
            },
            log: () => {},
            setTimeoutImpl: () => 1,
            clearTimeoutImpl: (id) => cleared.push(id),
          },
        ),
      ).rejects.toBe(reason);
      expect(cleared).toEqual([1]);
      expect(activeListeners.size).toBe(0);
    },
  );

  it("bounds attempts and exponential backoff delays", async () => {
    const delays = [];
    let calls = 0;
    const fetchImpl = async () => {
      calls += 1;
      throw new TypeError("offline");
    };

    await expect(
      fetchBulkAdvisories(
        { pkg: ["1.0.0"] },
        {
          fetchImpl,
          attempts: 100,
          maxRetryDelayMs: 1500,
          sleep: async (ms) => delays.push(ms),
          log: () => {},
        },
      ),
    ).rejects.toThrow("offline");
    expect(calls).toBe(3);
    expect(delays).toEqual([1000, 1500]);
  });
});

// Exercise main's catch: an endpoint failure must be exit 2 rather than being
// mistaken for the legitimate clean response represented by an empty map.
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

  it("exits 2 after exhausting transient 503 responses", () => {
    expect(
      runWithStubbedFetch("async () => ({ ok: false, status: 503, json: async () => ({}) })"),
    ).toBe(2);
  }, 30_000);

  it("exits 2 immediately for the retired 410 endpoint", () => {
    expect(
      runWithStubbedFetch("async () => ({ ok: false, status: 410, json: async () => ({}) })"),
    ).toBe(2);
  }, 30_000);
});

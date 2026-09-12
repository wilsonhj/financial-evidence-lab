import { describe, expect, it, vi } from "vitest";
import result from "@fel/contracts/fixtures/extraction-review-result.json";
import command from "@fel/contracts/fixtures/extraction-review-command.json";
import proposal from "@fel/contracts/fixtures/extraction-proposal.json";
import { loadConfig, requestExtraction } from "./transport";
const workspace = "00000000-0000-4000-8000-000000000001";
const config = {
  mode: "http" as const,
  baseUrl: "https://api.example",
  token: "test-only-secret",
  workspaceId: workspace,
};
const page = { items: [proposal], limit: 50, next_cursor: null, previous_cursor: null };

describe("extraction server transport", () => {
  it("requires explicit source selection and reuses strict workspace configuration", () => {
    expect(() => loadConfig({})).toThrow();
    expect(loadConfig({ FEL_EVIDENCE_SOURCE: "fixture" })).toEqual({ mode: "fixture" });
    expect(() => loadConfig({ FEL_EVIDENCE_SOURCE: "http" })).toThrow();
  });
  it("uses a fixed trusted route, configured bearer, no-store and manual redirects", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(page));
    const response = await requestExtraction(
      config,
      "proposals",
      new Request("https://web.example/api/extraction/proposals?limit=50"),
      fetcher,
    );
    expect(await response.json()).toEqual(page);
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      `https://api.example/v1/workspaces/${workspace}/extractions?limit=50`,
    );
    const options = fetcher.mock.calls[0]?.[1];
    expect(options.redirect).toBe("manual");
    expect(options.cache).toBe("no-store");
    expect(new Headers(options.headers).get("authorization")).toBe("Bearer test-only-secret");
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
  it.each(["https://evil.example", "../runs", "runs/not-a-uuid", "proposals?other=1"])(
    "rejects arbitrary route %s before credentials leave",
    async (path) => {
      const fetcher = vi.fn();
      expect(
        (
          await requestExtraction(
            config,
            path,
            new Request("https://web.example/api/extraction/test"),
            fetcher,
          )
        ).status,
      ).toBe(422);
      expect(fetcher).not.toHaveBeenCalled();
    },
  );
  it.each(["?limit=201", "?cursor=", "?url=https://evil.example", "?limit=1&limit=2"])(
    "rejects invalid query %s",
    async (query) => {
      const fetcher = vi.fn();
      expect(
        (
          await requestExtraction(
            config,
            "proposals",
            new Request(`https://web.example/api/extraction/proposals${query}`),
            fetcher,
          )
        ).status,
      ).toBe(422);
      expect(fetcher).not.toHaveBeenCalled();
    },
  );
  it("rejects upstream redirects without a second fetch or leaking location", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(null, { status: 302, headers: { location: "https://evil.example" } }),
      );
    const response = await requestExtraction(
      config,
      "proposals",
      new Request("https://web.example/api/extraction/proposals"),
      fetcher,
    );
    expect(response.status).toBe(502);
    expect(response.headers.has("location")).toBe(false);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("fails malformed success closed, without fallback or reflected values", async () => {
    const response = await requestExtraction(
      config,
      "proposals",
      new Request("https://web.example/api/extraction/proposals"),
      vi.fn().mockResolvedValue(Response.json({ private: "source text" })),
    );
    expect(response.status).toBe(502);
    expect(await response.text()).not.toContain("source text");
  });
  it("rejects foreign-origin mutations and never forwards browser credentials", async () => {
    const fetcher = vi.fn();
    const request = new Request("https://web.example/api/extraction/review", {
      method: "POST",
      headers: {
        origin: "https://evil.example",
        authorization: "attacker",
        "content-type": "application/json",
      },
      body: "{}",
    });
    expect((await requestExtraction(config, "review", request, fetcher)).status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });
});

const action = (body = JSON.stringify(command), headers: Record<string, string> = {}) =>
  new Request("https://web.example/api/extraction/review", {
    method: "POST",
    headers: {
      origin: "https://web.example",
      "content-type": "application/json",
      "idempotency-key": "same-key",
      authorization: "browser-must-not-forward",
      ...headers,
    },
    body,
  });
describe("extraction action and stream integrity", () => {
  it("retains exact body and key for retries and excludes browser authorization", async () => {
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(Response.json(result)));
    const body = JSON.stringify(command, null, 2);
    for (let i = 0; i < 2; i++)
      expect((await requestExtraction(config, "review", action(body), fetcher)).status).toBe(200);
    for (const [, options] of fetcher.mock.calls) {
      expect(options.body).toBe(body);
      expect(new Headers(options.headers).get("idempotency-key")).toBe("same-key");
      expect(new Headers(options.headers).get("authorization")).toBe("Bearer test-only-secret");
    }
  });
  it.each([409, 412, 413, 422])(
    "preserves status %i while suppressing untrusted error details",
    async (status) => {
      const upstream = Response.json(
        {
          error: {
            code: "PRECONDITION_FAILED",
            message: "private prompt",
            request_id: "safe-request",
            details: { secret: "private", resource: workspace },
          },
        },
        { status },
      );
      const response = await requestExtraction(
        config,
        "review",
        action(),
        vi.fn().mockResolvedValue(upstream),
      );
      expect(response.status).toBe(status);
      expect(await response.json()).toEqual({
        error: {
          code: "PRECONDITION_FAILED",
          message: "Extraction request could not be completed",
          request_id: "safe-request",
          details: { resource: workspace },
        },
      });
    },
  );
  it.each(["{", JSON.stringify({ ...command, internal: true })])(
    "rejects malformed commands before fetch",
    async (body) => {
      const fetcher = vi.fn();
      expect((await requestExtraction(config, "review", action(body), fetcher)).status).toBe(422);
      expect(fetcher).not.toHaveBeenCalled();
    },
  );
  it("limits request bytes before parsing", async () => {
    const fetcher = vi.fn();
    expect(
      (await requestExtraction(config, "review", action(" ".repeat(1048577)), fetcher)).status,
    ).toBe(413);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("forwards streaming chunks immediately and propagates cancellation", async () => {
    const cancelled = vi.fn();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(": heartbeat\n\n"));
      },
      cancel: cancelled,
    });
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(stream, { headers: { "content-type": "text/event-stream" } }),
      );
    const abort = new AbortController();
    const request = new Request(`https://web.example/api/extraction/runs/${workspace}/events`, {
      signal: abort.signal,
      headers: { "last-event-id": "2" },
    });
    const response = await requestExtraction(config, `runs/${workspace}/events`, request, fetcher);
    const reader = response.body!.getReader();
    expect(new TextDecoder().decode((await reader.read()).value)).toBe(": heartbeat\n\n");
    expect(fetcher.mock.calls[0]?.[1].signal).toBe(request.signal);
    expect(new Headers(fetcher.mock.calls[0]?.[1].headers).get("last-event-id")).toBe("2");
    await reader.cancel();
    expect(cancelled).toHaveBeenCalledOnce();
  });
  it("rejects unsafe resume before fetching", async () => {
    const fetcher = vi.fn();
    const request = new Request("https://web.example/api/extraction/events", {
      headers: { "last-event-id": "9007199254740992" },
    });
    expect(
      (await requestExtraction(config, `runs/${workspace}/events`, request, fetcher)).status,
    ).toBe(422);
    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe("Next request host origin boundary", () => {
  it("uses the incoming Host when Next internally normalizes the request URL", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(result));
    const request = new Request("http://localhost:3210/api/extraction/review", {
      method: "POST",
      headers: {
        host: "127.0.0.1:3210",
        origin: "http://127.0.0.1:3210",
        "sec-fetch-site": "same-origin",
        "content-type": "application/json",
        "idempotency-key": "browser-test",
      },
      body: JSON.stringify(command),
    });
    expect((await requestExtraction(config, "review", request, fetcher)).status).toBe(200);
  });
  it("admits a browser https Origin when TLS terminates before the Next socket", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(result));
    const request = new Request("http://web.example/api/extraction/review", {
      method: "POST",
      headers: {
        host: "web.example",
        origin: "https://web.example",
        "sec-fetch-site": "same-origin",
        "content-type": "application/json",
        "idempotency-key": "browser-test",
      },
      body: JSON.stringify(command),
    });
    expect((await requestExtraction(config, "review", request, fetcher)).status).toBe(200);
  });
  it.each(["null", "https://web.example.evil", "javascript:alert(1)", ""])(
    "rejects opaque or foreign origin %s",
    async (origin) => {
      const fetcher = vi.fn();
      const request = new Request("http://web.example/api/extraction/review", {
        method: "POST",
        headers: {
          host: "web.example",
          ...(origin ? { origin } : {}),
          "content-type": "application/json",
          "idempotency-key": "browser-test",
        },
        body: JSON.stringify(command),
      });
      expect((await requestExtraction(config, "review", request, fetcher)).status).toBe(403);
      expect(fetcher).not.toHaveBeenCalled();
    },
  );
  it("does not trust an attacker-supplied forwarded host for origin admission", async () => {
    const fetcher = vi.fn();
    const request = new Request("https://web.example/api/extraction/review", {
      method: "POST",
      headers: {
        host: "web.example",
        "x-forwarded-host": "evil.example",
        origin: "https://evil.example",
        "content-type": "application/json",
        "idempotency-key": "browser-test",
      },
      body: JSON.stringify(command),
    });
    expect((await requestExtraction(config, "review", request, fetcher)).status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });
});

it("admits an empty DELETE stream from the framework but rejects actual bytes", async () => {
  const run = {
    id: workspace,
    workspace_id: workspace,
    entity_id: workspace,
    status: "cancelled",
    modes: ["kpi"],
    as_of: "2026-07-01T00:00:00Z",
    ontology_version: "v1",
    workflow_version: "v3",
    provider: "mock",
    model: "mock",
    limits: {},
    usage: { calls: 0, input_tokens: 0, output_tokens: 0, cost_usd: "0" },
    version: 1,
    created_at: "2026-07-01T00:00:00Z",
    cancel_requested_at: "2026-07-01T00:00:00Z",
  };
  const fetcher = vi
    .fn()
    .mockResolvedValue(Response.json(run, { headers: { etag: '"cancelled"' } }));
  const request = (body: string) =>
    new Request(`https://web.example/api/extraction/runs/${workspace}`, {
      method: "DELETE",
      headers: {
        origin: "https://web.example",
        "idempotency-key": "cancel",
        "if-match": '"running"',
      },
      body,
    });
  expect((await requestExtraction(config, `runs/${workspace}`, request(""), fetcher)).status).toBe(
    200,
  );
  expect(
    (await requestExtraction(config, `runs/${workspace}`, request("{}"), fetcher)).status,
  ).toBe(422);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("returns a typed size failure before materializing an oversized upstream JSON response", async () => {
  const fetcher = vi.fn().mockResolvedValue(
    new Response(" ".repeat(8 * 1024 * 1024 + 1), {
      headers: { "content-type": "application/json" },
    }),
  );
  const response = await requestExtraction(
    config,
    "proposals",
    new Request("https://web.example/api/extraction/proposals"),
    fetcher,
  );
  expect(response.status).toBe(413);
  expect((await response.json()).error.code).toBe("EXTRACTION_TOO_LARGE");
});

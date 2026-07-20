import { describe, expect, it, vi } from "vitest";

import { ObservatoryApiError, ObservatoryContractError } from "./errors";
import { HttpObservatorySource } from "./http-source";
import type { CreateQuery } from "./query-source";
import {
  MOCK_QUERY_ID,
  MOCK_QUERY_SNAPSHOT,
  MOCK_RUN_ID,
  MOCK_TRACE,
} from "./fixtures/synthetic-trace";

const WORKSPACE_ID = "dddddddd-0000-4000-8000-000000000001";
const BASE_URL = "https://api.example.test/";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function makeSource(fetchImpl: typeof fetch, token: string | (() => string) = "test-token") {
  return new HttpObservatorySource({
    baseUrl: BASE_URL,
    workspaceId: WORKSPACE_ID,
    token,
    fetchImpl,
  });
}

const CREATE: CreateQuery = {
  question: "What was revenue?",
  lanes: ["dense", "lexical"],
  top_k: 25,
};

describe("HttpObservatorySource requests", () => {
  it("creates a query with bearer auth, no-store, JSON body, and Idempotency-Key", async () => {
    const accepted = { query_id: MOCK_QUERY_ID, run_id: MOCK_RUN_ID, events_url: "/e" };
    const fetchImpl = vi.fn(async () => jsonResponse(accepted, 202));
    const result = await makeSource(fetchImpl as unknown as typeof fetch).createQuery(
      CREATE,
      "idem-1",
    );

    expect(result.query_id).toBe(MOCK_QUERY_ID);
    const [url, init] = fetchImpl.mock.calls[0]! as unknown as [string, RequestInit];
    expect(url).toBe(`https://api.example.test/v1/workspaces/${WORKSPACE_ID}/queries`);
    expect(init.method).toBe("POST");
    expect(init.cache).toBe("no-store");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
    expect(headers["Idempotency-Key"]).toBe("idem-1");
    expect(JSON.parse(init.body as string)).toEqual(CREATE);
  });

  it("keeps the token out of the URL when using an async token provider", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(MOCK_QUERY_SNAPSHOT));
    await makeSource(fetchImpl as unknown as typeof fetch, () => "minted").getQuery(MOCK_QUERY_ID);
    const [url, init] = fetchImpl.mock.calls[0]! as unknown as [string, RequestInit];
    expect(url).not.toContain("minted");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer minted");
  });

  it("validates and returns a query snapshot and a trace", async () => {
    const snapshot = await makeSource(
      vi.fn(async () => jsonResponse(MOCK_QUERY_SNAPSHOT)) as unknown as typeof fetch,
    ).getQuery(MOCK_QUERY_ID);
    expect(snapshot.query_id).toBe(MOCK_QUERY_ID);
    const trace = await makeSource(
      vi.fn(async () => jsonResponse(MOCK_TRACE)) as unknown as typeof fetch,
    ).getRun(MOCK_RUN_ID);
    expect(trace.candidates.length).toBe(MOCK_TRACE.candidates.length);
  });

  it("maps 401/403/409/422/5xx to distinct typed failure kinds without leaking the body", async () => {
    const cases: [number, string][] = [
      [401, "authentication"],
      [403, "forbidden"],
      [409, "conflict"],
      [422, "invalid_scope"],
      [503, "unavailable"],
    ];
    for (const [status, kind] of cases) {
      const envelope = {
        error: { code: "SECRET_CODE", message: "secret detail", request_id: "rq" },
      };
      const fetchImpl = vi.fn(async () => jsonResponse(envelope, status));
      const error = await makeSource(fetchImpl as unknown as typeof fetch)
        .createQuery(CREATE, "k")
        .catch((error: unknown) => error);
      expect(error).toBeInstanceOf(ObservatoryApiError);
      expect((error as ObservatoryApiError).kind).toBe(kind);
      expect((error as ObservatoryApiError).message).not.toContain("secret detail");
      expect((error as ObservatoryApiError).code).toBe("SECRET_CODE");
    }
  });

  it("classifies a transport failure and a bad token as unavailable/authentication", async () => {
    const network = makeSource((() =>
      Promise.reject(new Error("down"))) as unknown as typeof fetch);
    await expect(network.getRun(MOCK_RUN_ID)).rejects.toMatchObject({ kind: "unavailable" });
    const badToken = makeSource(vi.fn() as unknown as typeof fetch, () => {
      throw new Error("no token");
    });
    await expect(badToken.getRun(MOCK_RUN_ID)).rejects.toMatchObject({ kind: "authentication" });
  });

  it("rejects a 2xx body that violates the trace contract", async () => {
    const broken = { ...structuredClone(MOCK_TRACE), candidates: [{ item_id: 5 }] };
    const fetchImpl = vi.fn(async () => jsonResponse(broken));
    await expect(
      makeSource(fetchImpl as unknown as typeof fetch).getRun(MOCK_RUN_ID),
    ).rejects.toBeInstanceOf(ObservatoryContractError);
  });

  it("records feedback with Idempotency-Key and treats non-201 as an error", async () => {
    const ok = vi.fn(async () => new Response(null, { status: 201 }));
    await makeSource(ok as unknown as typeof fetch).submitFeedback(
      MOCK_RUN_ID,
      { item_id: "10101010-0000-4000-8000-000000000001", label: "relevant" },
      "fb-1",
    );
    const [, init] = ok.mock.calls[0]! as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe("fb-1");

    const conflict = vi.fn(async () =>
      jsonResponse({ error: { code: "C", message: "m", request_id: "r" } }, 409),
    );
    await expect(
      makeSource(conflict as unknown as typeof fetch).submitFeedback(
        MOCK_RUN_ID,
        { item_id: "10101010-0000-4000-8000-000000000001", label: "relevant" },
        "fb-2",
      ),
    ).rejects.toMatchObject({ kind: "conflict" });
  });

  it("opens the event stream with Accept text/event-stream and Last-Event-ID when resuming", async () => {
    const body = new Response("id: 3\ndata: {}\n\n").body!;
    const fetchImpl = vi.fn(async () => new Response(body, { status: 200 }));
    const open = makeSource(fetchImpl as unknown as typeof fetch).openEventStream(MOCK_RUN_ID);
    const controller = new AbortController();

    await open(null, controller.signal);
    let init = fetchImpl.mock.calls[0]! as unknown as [string, RequestInit];
    let headers = init[1].headers as Record<string, string>;
    expect(headers.Accept).toBe("text/event-stream");
    expect(headers.Authorization).toBe("Bearer test-token");
    expect(headers["Last-Event-ID"]).toBeUndefined();

    await open(3, controller.signal).catch(() => undefined);
    init = fetchImpl.mock.calls[1]! as unknown as [string, RequestInit];
    headers = init[1].headers as Record<string, string>;
    expect(headers["Last-Event-ID"]).toBe("3");
  });

  it("raises a typed error when the event stream cannot be opened", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ error: { code: "C", message: "m", request_id: "r" } }, 403),
    );
    const open = makeSource(fetchImpl as unknown as typeof fetch).openEventStream(MOCK_RUN_ID);
    await expect(open(null, new AbortController().signal)).rejects.toMatchObject({
      kind: "forbidden",
    });
  });
});

// Guard: importing the server-only source must not have pulled process env into
// a shape that leaks; a smoke read confirms the stream body is consumable.
describe("event stream body", () => {
  it("returns a readable byte stream", async () => {
    const fetchImpl = vi.fn(
      async () => new Response(new Response("id: 1\ndata: {}\n\n").body, { status: 200 }),
    );
    const open = makeSource(fetchImpl as unknown as typeof fetch).openEventStream(MOCK_RUN_ID);
    const stream = await open(null, new AbortController().signal);
    const reader = (stream as ReadableStream<Uint8Array>).getReader();
    const { value } = await reader.read();
    expect(new TextDecoder().decode(value)).toContain("data:");
  });
});

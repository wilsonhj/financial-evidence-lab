import { describe, expect, it, vi } from "vitest";

import type { DocumentMeta } from "../contracts";
import { EvidenceApiError, HttpEvidenceSource } from "./http-source";

const ENTITY_A = "11111111-1111-4111-8111-111111111111";
const ENTITY_B = "22222222-2222-4222-8222-222222222222";

function doc(id: string, entityId: string, publishedAt: string): DocumentMeta {
  return {
    id,
    entity_id: entityId,
    accession: `acc-${id}`,
    source_url: `https://filings.example.test/${id}.htm`,
    content_hash: `sha256:${"0".repeat(64)}`,
    published_at: publishedAt,
    ingested_at: "2026-07-01T00:00:00Z",
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function makeSource(
  fetchImpl: typeof fetch,
  options: Partial<{ asOf: string; entityIds: string[] }> = {},
) {
  return new HttpEvidenceSource({
    baseUrl: "https://api.example.test",
    entityIds: options.entityIds ?? [ENTITY_A],
    token: "test-token",
    asOf: options.asOf,
    fetchImpl,
  });
}

describe("HttpEvidenceSource", () => {
  // Regression (finding 3a): no Authorization header was ever sent, so every
  // call against apps/api would 401.
  it("sends a bearer Authorization header on every request", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse([]));
    await makeSource(fetchImpl as unknown as typeof fetch).listDocuments();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [, init] = fetchImpl.mock.calls[0]! as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer test-token");
  });

  it("supports an async token provider", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse([]));
    const source = new HttpEvidenceSource({
      baseUrl: "https://api.example.test",
      entityIds: [ENTITY_A],
      token: async () => "minted-token",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    await source.listDocuments();
    const [, init] = fetchImpl.mock.calls[0]! as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer minted-token");
  });

  // Regression (finding 3b): as_of was never propagated although point-in-time
  // filtering is a core contract invariant.
  it("propagates asOf as the as_of query parameter on document listing", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse([]));
    await makeSource(fetchImpl as unknown as typeof fetch, {
      asOf: "2026-06-30T00:00:00Z",
    }).listDocuments();
    const [url] = fetchImpl.mock.calls[0]! as unknown as [string];
    expect(url).toBe(
      `https://api.example.test/v1/entities/${ENTITY_A}/documents?as_of=2026-06-30T00%3A00%3A00Z`,
    );
  });

  it("omits as_of when not configured", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse([]));
    await makeSource(fetchImpl as unknown as typeof fetch).listDocuments();
    const [url] = fetchImpl.mock.calls[0]! as unknown as [string];
    expect(url).toBe(`https://api.example.test/v1/entities/${ENTITY_A}/documents`);
  });

  // Regression (finding 3d): a single hard-coded entityId silently narrowed
  // the advertised workspace-wide listing to one entity.
  it("merges documents across entityIds in deterministic published-then-id order", async () => {
    const fetchImpl = vi.fn(async (url: string) => {
      if (url.includes(ENTITY_A)) {
        return jsonResponse([
          doc("bbbbbbbb-0000-4000-8000-000000000002", ENTITY_A, "2026-05-01T00:00:00Z"),
        ]);
      }
      return jsonResponse([
        // Offset timestamp equal to an earlier instant than ENTITY_A's doc.
        doc("bbbbbbbb-0000-4000-8000-000000000001", ENTITY_B, "2026-04-30T22:00:00+02:00"),
        doc("bbbbbbbb-0000-4000-8000-000000000003", ENTITY_B, "2026-06-01T00:00:00Z"),
      ]);
    });
    const documents = await makeSource(fetchImpl as unknown as typeof fetch, {
      entityIds: [ENTITY_A, ENTITY_B],
    }).listDocuments();
    expect(documents.map((entry) => entry.id)).toEqual([
      "bbbbbbbb-0000-4000-8000-000000000001",
      "bbbbbbbb-0000-4000-8000-000000000002",
      "bbbbbbbb-0000-4000-8000-000000000003",
    ]);
  });

  // Regression (finding 3c): getDocument used to catch ALL errors and return
  // null, so API outages and auth failures rendered as 404 pages.
  it("maps only a true API 404 to null", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ error: { code: "NOT_FOUND", message: "no", request_id: "r-1" } }, 404),
    );
    const result = await makeSource(fetchImpl as unknown as typeof fetch).getDocument(
      "bbbbbbbb-0000-4000-8000-000000000404",
    );
    expect(result).toBeNull();
  });

  it("throws a typed EvidenceApiError carrying the contract envelope on non-404 failures", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(
        { error: { code: "INTERNAL", message: "database unavailable", request_id: "req-42" } },
        500,
      ),
    );
    const source = makeSource(fetchImpl as unknown as typeof fetch);
    const error = await source
      .getDocument("bbbbbbbb-0000-4000-8000-000000000500")
      .then(() => null)
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(EvidenceApiError);
    const apiError = error as EvidenceApiError;
    expect(apiError.status).toBe(500);
    expect(apiError.code).toBe("INTERNAL");
    expect(apiError.requestId).toBe("req-42");
    expect(apiError.message).toContain("database unavailable");
  });

  it("throws a typed EvidenceApiError even when the error body is not an envelope", async () => {
    const fetchImpl = vi.fn(async () => new Response("gateway timeout", { status: 504 }));
    const source = makeSource(fetchImpl as unknown as typeof fetch);
    await expect(source.getDocument("bbbbbbbb-0000-4000-8000-000000000504")).rejects.toBeInstanceOf(
      EvidenceApiError,
    );
  });

  it("throws on listDocuments failures instead of returning an empty list", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(
        { error: { code: "UNAUTHENTICATED", message: "no token", request_id: "r" } },
        401,
      ),
    );
    await expect(
      makeSource(fetchImpl as unknown as typeof fetch).listDocuments(),
    ).rejects.toBeInstanceOf(EvidenceApiError);
  });

  // Regression (finding 3e): getSections/getSpans/getFacts reject
  // unconditionally, and the reader used to await them unguarded; the
  // capabilities flags are what let the UI degrade gracefully.
  it("advertises that sections, spans, and facts are unavailable", () => {
    const source = makeSource(vi.fn() as unknown as typeof fetch);
    expect(source.capabilities).toEqual({ sections: false, spans: false, facts: false });
  });
});

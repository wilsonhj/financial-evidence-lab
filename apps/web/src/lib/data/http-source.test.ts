import { describe, expect, it, vi } from "vitest";

import readerFixtureJson from "../../../../../packages/contracts/fixtures/reader-response.json";
import type { DocumentMeta, ReaderResponse } from "../contracts";
import {
  EvidenceApiError,
  EvidenceContractError,
  HttpEvidenceSource,
} from "./http-source";

const ENTITY_A = "11111111-1111-4111-8111-111111111111";
const ENTITY_B = "22222222-2222-4222-8222-222222222222";
const DOCUMENT_ID = readerFixtureJson.document.meta.id;
const AS_OF = readerFixtureJson.as_of;
const CORPUS_VERSION_ID = "33333333-3333-4333-8333-333333333333";

const readerFixture = structuredClone(readerFixtureJson) as ReaderResponse;

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
  options: Partial<{
    asOf: string;
    corpusVersionId: string;
    entityIds: string[];
  }> = {},
) {
  return new HttpEvidenceSource({
    baseUrl: "https://api.example.test/",
    entityIds: options.entityIds ?? [ENTITY_A],
    token: "test-token",
    asOf: options.asOf,
    corpusVersionId: options.corpusVersionId,
    fetchImpl,
  });
}

describe("HttpEvidenceSource composite reader", () => {
  it("calls the composite endpoint with bearer auth and configured temporal/corpus scope", async () => {
    const body: ReaderResponse = {
      ...structuredClone(readerFixture),
      corpus_version_id: CORPUS_VERSION_ID,
      selection_policy: "corpus_pinned",
    };
    const fetchImpl = vi.fn(async () => jsonResponse(body));

    const result = await makeSource(fetchImpl as unknown as typeof fetch, {
      asOf: AS_OF,
      corpusVersionId: CORPUS_VERSION_ID,
    }).getReader(DOCUMENT_ID);

    expect(result?.document.meta.id).toBe(DOCUMENT_ID);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0]! as unknown as [string, RequestInit];
    expect(url).toBe(
      `https://api.example.test/v1/documents/${DOCUMENT_ID}/reader?as_of=${encodeURIComponent(AS_OF)}&corpus_version_id=${CORPUS_VERSION_ID}`,
    );
    expect(init.cache).toBe("no-store");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer test-token");
  });

  it("supports an async token provider without putting the token in the URL", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(readerFixture));
    const source = new HttpEvidenceSource({
      baseUrl: "https://api.example.test",
      entityIds: [ENTITY_A],
      token: async () => "minted-token",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await source.getReader(DOCUMENT_ID);

    const [url, init] = fetchImpl.mock.calls[0]! as unknown as [string, RequestInit];
    expect(url).not.toContain("minted-token");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer minted-token");
  });

  it("maps only a composite endpoint 404 to null", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ error: { code: "NOT_FOUND", message: "no", request_id: "r-1" } }, 404),
    );
    await expect(
      makeSource(fetchImpl as unknown as typeof fetch).getReader(DOCUMENT_ID),
    ).resolves.toBeNull();
  });

  it.each([
    [401, "authentication"],
    [403, "forbidden"],
    [409, "conflict"],
    [422, "invalid_scope"],
    [429, "unavailable"],
    [503, "unavailable"],
  ] as const)("preserves HTTP %i as typed %s failure", async (status, kind) => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(
        {
          error: {
            code: "UPSTREAM_DETAIL",
            message: "sensitive internal detail",
            details: { secret: "must-not-render" },
            request_id: "req-42",
          },
        },
        status,
      ),
    );
    const error = await makeSource(fetchImpl as unknown as typeof fetch)
      .getReader(DOCUMENT_ID)
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(EvidenceApiError);
    expect((error as EvidenceApiError).kind).toBe(kind);
    expect((error as EvidenceApiError).status).toBe(status);
    expect((error as Error).message).not.toContain("sensitive internal detail");
    expect((error as Error).message).not.toContain("must-not-render");
  });

  it("classifies transport failures as unavailable without exposing token material", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("request failed with Authorization: Bearer secret-token");
    });
    const error = await makeSource(fetchImpl as unknown as typeof fetch)
      .getReader(DOCUMENT_ID)
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(EvidenceApiError);
    expect((error as EvidenceApiError).kind).toBe("unavailable");
    expect((error as Error).message).not.toContain("secret-token");
  });

  it("rejects a target id that differs from the requested document", async () => {
    const body = structuredClone(readerFixture);
    body.document.meta.id = "aaaaaaaa-0000-4000-8000-000000000001";
    const source = makeSource(vi.fn(async () => jsonResponse(body)) as unknown as typeof fetch);
    await expect(source.getReader(DOCUMENT_ID)).rejects.toBeInstanceOf(EvidenceContractError);
  });

  it("rejects effective cutoff or corpus pins that differ from the configured scope", async () => {
    const wrongCutoff = structuredClone(readerFixture);
    wrongCutoff.as_of = "2026-07-02T00:00:00Z";
    await expect(
      makeSource(vi.fn(async () => jsonResponse(wrongCutoff)) as unknown as typeof fetch, {
        asOf: AS_OF,
      }).getReader(DOCUMENT_ID),
    ).rejects.toBeInstanceOf(EvidenceContractError);

    const wrongCorpus = structuredClone(readerFixture);
    wrongCorpus.corpus_version_id = null;
    await expect(
      makeSource(vi.fn(async () => jsonResponse(wrongCorpus)) as unknown as typeof fetch, {
        corpusVersionId: CORPUS_VERSION_ID,
      }).getReader(DOCUMENT_ID),
    ).rejects.toBeInstanceOf(EvidenceContractError);
  });

  it("rejects cross-version sections, spans, facts, and dangling fact citations", async () => {
    const mutations: Array<(body: ReaderResponse) => void> = [
      (body) => {
        body.document.sections[0]!.document_version_id = "aaaaaaaa-0000-4000-8000-000000000001";
      },
      (body) => {
        body.document.spans[0]!.span.document_version_id =
          "aaaaaaaa-0000-4000-8000-000000000001";
      },
      (body) => {
        body.document.facts[0]!.document_version_id =
          "aaaaaaaa-0000-4000-8000-000000000001";
      },
      (body) => {
        body.document.facts[0]!.fact.source_span_id =
          "aaaaaaaa-0000-4000-8000-000000000001";
      },
    ];

    for (const mutate of mutations) {
      const body = structuredClone(readerFixture);
      mutate(body);
      await expect(
        makeSource(vi.fn(async () => jsonResponse(body)) as unknown as typeof fetch).getReader(
          DOCUMENT_ID,
        ),
      ).rejects.toBeInstanceOf(EvidenceContractError);
    }
  });

  it("rejects siblings outside the effective cutoff", async () => {
    const body = structuredClone(readerFixture);
    body.siblings[0]!.meta.published_at = "2026-07-02T00:00:00Z";
    await expect(
      makeSource(vi.fn(async () => jsonResponse(body)) as unknown as typeof fetch).getReader(
        DOCUMENT_ID,
      ),
    ).rejects.toBeInstanceOf(EvidenceContractError);
  });
});

describe("HttpEvidenceSource document listing", () => {
  it("sends bearer auth and as_of on every configured entity request", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse([]));
    await makeSource(fetchImpl as unknown as typeof fetch, {
      asOf: AS_OF,
      entityIds: [ENTITY_A, ENTITY_B],
    }).listDocuments();

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    for (const [url, init] of fetchImpl.mock.calls as unknown as Array<[string, RequestInit]>) {
      expect(url).toContain(`?as_of=${encodeURIComponent(AS_OF)}`);
      expect(init.cache).toBe("no-store");
      expect((init.headers as Record<string, string>).Authorization).toBe("Bearer test-token");
    }
  });

  it("merges entity listings in deterministic published-then-id order", async () => {
    const fetchImpl = vi.fn(async (url: string) =>
      jsonResponse(
        url.includes(ENTITY_A)
          ? [doc("bbbbbbbb-0000-4000-8000-000000000002", ENTITY_A, "2026-05-01T00:00:00Z")]
          : [
              doc(
                "bbbbbbbb-0000-4000-8000-000000000001",
                ENTITY_B,
                "2026-04-30T22:00:00+02:00",
              ),
              doc(
                "bbbbbbbb-0000-4000-8000-000000000003",
                ENTITY_B,
                "2026-06-01T00:00:00Z",
              ),
            ],
      ),
    );
    const documents = await makeSource(fetchImpl as unknown as typeof fetch, {
      entityIds: [ENTITY_A, ENTITY_B],
    }).listDocuments();
    expect(documents.map((entry) => entry.id)).toEqual([
      "bbbbbbbb-0000-4000-8000-000000000001",
      "bbbbbbbb-0000-4000-8000-000000000002",
      "bbbbbbbb-0000-4000-8000-000000000003",
    ]);
  });
});

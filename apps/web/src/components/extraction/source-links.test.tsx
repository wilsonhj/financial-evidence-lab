import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SourceLinks } from "./SourceLinks";
import { initialFixture } from "../../lib/extraction/fixture";
import { HttpEvidenceSource } from "../../lib/data/http-source";
const state = initialFixture(),
  proposal = state.proposals[0]!,
  run = state.runs[0]!;
const sources = [{ run_id: run.id, as_of: run.as_of, corpus_version_id: run.corpus_version_id }];
afterEach(() => vi.unstubAllEnvs());
describe("immutable source navigation", () => {
  it("resolves distinct document/version IDs only under the artifact cutoff and corpus", async () => {
    vi.stubEnv("FEL_DEPLOYMENT_MODE", "fixture").stubEnv("FEL_EVIDENCE_SOURCE", "fixture");
    const html = renderToStaticMarkup(await SourceLinks({ evidence: proposal.evidence, sources }));
    expect(html).toContain("Read evidence span");
    expect(html).toContain("as_of=2026-07-01T00%3A00%3A00Z");
    expect(html).toContain("document_version_id=aaaaaaaa-0000-4000-8000-000000001001");
    expect(html).toContain("/reader/aaaaaaaa-0000-4000-8000-000000000001?");
  });
  it.each([
    { name: "unpinned", corpus: undefined },
    { name: "pinned", corpus: run.corpus_version_id },
  ])(
    "preserves $name historical scope through the reader despite a configured corpus",
    async ({ corpus }) => {
      vi.stubEnv("FEL_DEPLOYMENT_MODE", "fixture").stubEnv("FEL_EVIDENCE_SOURCE", "fixture");
      const html = renderToStaticMarkup(
        await SourceLinks({
          evidence: proposal.evidence,
          sources: [{ run_id: run.id, as_of: run.as_of, corpus_version_id: corpus }],
        }),
      );
      expect(html).toContain("Read evidence span");
      if (!corpus) expect(html).toContain("No corpus pin recorded");
      const href = html.match(/href="([^"]*\/reader\/[^"]*)"/)![1]!.replaceAll("&amp;", "&");
      const link = new URL(href, "http://localhost");
      const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 404 }));
      const reader = new HttpEvidenceSource({
        baseUrl: "https://api.example.test",
        token: "synthetic-test-token",
        entityIds: [run.entity_id],
        corpusVersionId: "33333333-3333-4333-8333-333333333333",
        fetchImpl: fetcher,
      });
      // Match the reader page's search-parameter mapping: an absent value is
      // undefined (deployment default), whereas an explicit empty pin overrides it.
      await reader.getReader(link.pathname.split("/").at(-1)!, {
        asOf: link.searchParams.get("as_of") ?? undefined,
        documentVersionId: link.searchParams.get("document_version_id") ?? undefined,
        corpusVersionId: link.searchParams.get("corpus_version_id") ?? undefined,
      });
      expect(fetcher).toHaveBeenCalledOnce();
      const request = new URL(String(fetcher.mock.calls[0]![0]));
      expect(request.searchParams.get("as_of")).toBe(run.as_of);
      expect(request.searchParams.get("document_version_id")).toBe(
        proposal.evidence[0]!.document_version_id,
      );
      expect(request.searchParams.get("corpus_version_id")).toBe(corpus ?? null);
    },
  );
  it("never substitutes present context for unknown historical provenance", async () => {
    const html = renderToStaticMarkup(
      await SourceLinks({ evidence: proposal.evidence, sources: null }),
    );
    expect(html).toContain("Unknown");
    expect(html).not.toContain("/reader/");
  });
  it("keeps multiple source contexts explicit without guessing an edge association", async () => {
    const html = renderToStaticMarkup(
      await SourceLinks({
        evidence: proposal.evidence,
        sources: [...sources, { ...sources[0]!, run_id: "00000000-0000-4000-8000-000000000001" }],
      }),
    );
    expect(html).toContain("multiple source contexts");
    expect(html).not.toContain("/reader/");
  });
  it("keeps unavailable evidence IDs visible and handles empty evidence", async () => {
    vi.stubEnv("FEL_EVIDENCE_SOURCE", "invalid");
    const html = renderToStaticMarkup(await SourceLinks({ evidence: proposal.evidence, sources }));
    expect(html).toContain(proposal.evidence[0]!.source_span_id);
    expect(html).not.toContain("/reader/");
    expect(renderToStaticMarkup(await SourceLinks({ evidence: [], sources }))).toContain(
      "No evidence edges recorded",
    );
  });
});

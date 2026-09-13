import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SourceLinks } from "./SourceLinks";
import { initialFixture } from "../../lib/extraction/fixture";
const state = initialFixture(),
  proposal = state.proposals[0]!,
  run = state.runs[0]!;
const sources = [{ run_id: run.id, as_of: run.as_of, corpus_version_id: run.corpus_version_id }];
afterEach(() => vi.unstubAllEnvs());
describe("immutable source navigation", () => {
  it("resolves distinct document/version IDs only under the artifact cutoff and corpus", async () => {
    vi.stubEnv("FEL_EVIDENCE_SOURCE", "fixture");
    const html = renderToStaticMarkup(await SourceLinks({ evidence: proposal.evidence, sources }));
    expect(html).toContain("Read evidence span");
    expect(html).toContain("as_of=2026-07-01T00%3A00%3A00Z");
    expect(html).toContain("document_version_id=aaaaaaaa-0000-4000-8000-000000001001");
    expect(html).toContain("/reader/aaaaaaaa-0000-4000-8000-000000000001?");
  });
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

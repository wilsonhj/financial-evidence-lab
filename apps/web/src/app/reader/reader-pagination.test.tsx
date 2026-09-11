import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/data/server", () => ({ getEvidenceSource: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
}));

import ReaderPage from "./[documentId]/page";
import { EvidenceReader } from "../../components/EvidenceReader";
import { getEvidenceSource } from "../../lib/data/server";
import { FixtureEvidenceSource } from "../../lib/data/fixture-source";
import { EvidenceApiError, EvidenceContractError } from "../../lib/data/http-source";
import { DOC_10Q_ID, DOC_10QA_ID } from "../../lib/fixtures/synthetic-filing";
import { findOne } from "../../lib/test-support/shallow-tree";

let source: FixtureEvidenceSource;
const params = () => Promise.resolve({ documentId: DOC_10Q_ID });
const cutoff = "2026-12-31T23:59:59Z";
function anchors(html: string) {
  return [...html.matchAll(/href="([^"]+)"[^>]*>([^<]+)<\/a>/g)].map((match) => ({
    url: new URL(match[1]!.replaceAll("&amp;", "&"), "https://app.test"),
    label: match[2],
  }));
}

beforeEach(() => {
  vi.resetAllMocks();
  source = new FixtureEvidenceSource();
  vi.mocked(getEvidenceSource).mockReturnValue(source);
});

describe("reader page scope and bounded history", () => {
  it("initially loads only the target and pins version/cutoff/span when opting into related history", async () => {
    const getReader = vi.spyOn(source, "getReader");
    const element = await ReaderPage({
      params: params(),
      searchParams: Promise.resolve({
        span: ["selected", "ignored"],
        as_of: cutoff,
        corpus_version_id: "",
      }),
    });
    expect(getReader).toHaveBeenCalledExactlyOnceWith(DOC_10Q_ID, {
      includeSiblings: false,
      documentVersionId: undefined,
      asOf: cutoff,
      corpusVersionId: "",
    });
    const reader = findOne(element, (node) => node.type === EvidenceReader) as ReactElement<{
      initialSpanId: string;
      historyComplete: boolean;
    }>;
    expect(reader.props.initialSpanId).toBe("selected");
    expect(reader.props.historyComplete).toBe(false);
    const link = anchors(renderToStaticMarkup(element)).find(
      (anchor) => anchor.label === "Load related filings",
    )!.url;
    expect(link.searchParams.get("span")).toBe("selected");
    expect(link.searchParams.get("related")).toBe("1");
    expect(link.searchParams.get("document_version_id")).toBeTruthy();
    expect(link.searchParams.get("as_of")).toBe(cutoff);
    expect(link.searchParams.get("corpus_version_id")).toBe("");
  });

  it("retains the target and each sibling's own version across related-page navigation", async () => {
    const body = (await source.getReader(DOC_10Q_ID, { siblingLimit: 10, asOf: cutoff }))!;
    body.sibling_page = {
      scope: "page",
      returned: body.siblings.length,
      limit: 10,
      complete: false,
      next_cursor: "after+/=",
      previous_cursor: "before+/=",
    };
    vi.spyOn(source, "getReader").mockResolvedValue(body);
    const element = await ReaderPage({
      params: params(),
      searchParams: Promise.resolve({
        related: "1",
        sibling_cursor: "current",
        sibling_order: "desc",
        document_version_id: body.document.document_version_id,
        as_of: cutoff,
      }),
    });
    expect(source.getReader).toHaveBeenCalledWith(DOC_10Q_ID, {
      includeSiblings: true,
      siblingLimit: 10,
      siblingCursor: "current",
      siblingOrder: "desc",
      documentVersionId: body.document.document_version_id,
      asOf: cutoff,
      corpusVersionId: undefined,
    });
    const html = renderToStaticMarkup(element);
    const next = anchors(html).find((anchor) => anchor.label === "Next page")!.url;
    expect(next.searchParams.get("sibling_cursor")).toBe("after+/=");
    expect(next.searchParams.get("sibling_order")).toBe("desc");
    expect(next.searchParams.get("document_version_id")).toBe(body.document.document_version_id);
    for (const sibling of body.siblings) {
      const link = anchors(html).find(
        (anchor) => anchor.url.pathname === `/reader/${sibling.meta.id}`,
      )!;
      expect(link.url.searchParams.get("document_version_id")).toBe(sibling.document_version_id);
      expect(link.url.searchParams.get("as_of")).toBe(cutoff);
    }
    expect(html).toContain("Browsing history; pages may change between requests.");
  });

  it("labels corpus-pinned history and handles an empty terminal sibling page", async () => {
    const body = (await source.getReader(DOC_10Q_ID, { includeSiblings: false }))!;
    body.corpus_version_id = "pinned-corpus";
    body.sibling_page = {
      scope: "page",
      returned: 0,
      limit: 10,
      complete: true,
      next_cursor: null,
      previous_cursor: null,
    };
    vi.spyOn(source, "getReader").mockResolvedValue(body);
    const html = renderToStaticMarkup(
      await ReaderPage({ params: params(), searchParams: Promise.resolve({ related: "1" }) }),
    );
    expect(html).toContain("0 related filings on this page.");
    expect(html).toContain("Corpus-pinned history.");
    expect(html.match(/aria-disabled="true"/g)).toHaveLength(2);
  });

  it("opens the actual offending sibling's original URL and preserves target pins in the recovery link", async () => {
    vi.spyOn(source, "getReader").mockRejectedValue(
      new EvidenceApiError(413, "/reader", "too_large", {
        error: {
          code: "reader_limit_exceeded",
          message: "private upstream detail",
          request_id: "test",
          details: { resource: DOC_10QA_ID },
        },
      }),
    );
    const getDocument = vi.spyOn(source, "getDocument");
    const html = renderToStaticMarkup(
      await ReaderPage({
        params: params(),
        searchParams: Promise.resolve({
          related: "1",
          span: "selected",
          as_of: cutoff,
          document_version_id: "target-version",
          corpus_version_id: "",
          sibling_cursor: "discard",
        }),
      }),
    );
    expect(getDocument).toHaveBeenCalledExactlyOnceWith(DOC_10QA_ID, { asOf: cutoff });
    const recovery = anchors(html).find(
      (anchor) => anchor.label === "Open target filing without related history",
    )!.url;
    expect(recovery.pathname).toBe(`/reader/${DOC_10Q_ID}`);
    expect(recovery.searchParams.get("document_version_id")).toBe("target-version");
    expect(recovery.searchParams.get("corpus_version_id")).toBe("");
    expect(recovery.searchParams.get("span")).toBe("selected");
    expect(recovery.searchParams.has("related")).toBe(false);
    expect(recovery.searchParams.has("sibling_cursor")).toBe(false);
    const meta = await source.getDocument(DOC_10QA_ID);
    expect(anchors(html).find((anchor) => anchor.label === "Open original filing")?.url.href).toBe(
      meta!.source_url,
    );
    expect(html).not.toContain("private upstream detail");
  });

  it.each(["missing", "unsafe"] as const)(
    "keeps the 413 message when original metadata is %s",
    async (state) => {
      vi.spyOn(source, "getReader").mockRejectedValue(
        new EvidenceApiError(413, "/reader", "too_large"),
      );
      const meta = await source.getDocument(DOC_10Q_ID);
      const getDocument = vi.spyOn(source, "getDocument");
      if (state === "missing") getDocument.mockRejectedValue(new Error("offline"));
      else getDocument.mockResolvedValue({ ...meta!, source_url: "javascript:alert(1)" });
      const html = renderToStaticMarkup(await ReaderPage({ params: params() }));
      expect(getDocument).toHaveBeenCalledWith(DOC_10Q_ID, { asOf: undefined });
      expect(html).toContain("Evidence exceeds the read limit");
      expect(html).not.toContain("Open original filing");
      expect(html).not.toContain("Open target filing without related history");
    },
  );

  it("distinguishes rejected evidence, an absent target, and an unexpected loader failure", async () => {
    const read = vi
      .spyOn(source, "getReader")
      .mockRejectedValueOnce(new EvidenceContractError("private details"));
    expect(renderToStaticMarkup(await ReaderPage({ params: params() }))).toContain(
      "Evidence response rejected",
    );
    read.mockResolvedValueOnce(null);
    await expect(ReaderPage({ params: params() })).rejects.toThrow("NOT_FOUND");
    const error = new Error("unexpected loader error");
    read.mockRejectedValueOnce(error);
    await expect(ReaderPage({ params: params() })).rejects.toBe(error);
  });
});

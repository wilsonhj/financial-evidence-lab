import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";

import ReaderPage from "./[documentId]/page";
import { EvidenceReader } from "../../components/EvidenceReader";
import { DOC_10Q_ID, DOC_10QA_ID } from "../../lib/fixtures/synthetic-filing";

async function renderPageElement(documentId: string): Promise<ReactElement> {
  return (await ReaderPage({
    params: Promise.resolve({ documentId }),
  })) as ReactElement;
}

describe("ReaderPage", () => {
  beforeEach(() => {
    vi.stubEnv("FEL_EVIDENCE_SOURCE", "fixture");
  });

  // Regression (finding 5), updated for issue #198: the reader used to leak
  // client state (selection, outline focus, notes) across filings when
  // navigating, which the page originally fixed with <EvidenceReader
  // key={documentId}> (forcing a remount). EvidenceReader now keys its
  // internal useReducer state by documentId and resets on a prop change
  // instead (see lib/reader-state.test.ts), so the page passes documentId
  // straight through without a key.
  it("passes documentId through without a remount key (reducer now owns the reset)", async () => {
    const element10q = await renderPageElement(DOC_10Q_ID);
    const element10qa = await renderPageElement(DOC_10QA_ID);

    expect(element10q.type).toBe(EvidenceReader);
    expect(element10qa.type).toBe(EvidenceReader);
    expect((element10q.props as { documentId: string }).documentId).toBe(DOC_10Q_ID);
    expect((element10qa.props as { documentId: string }).documentId).toBe(DOC_10QA_ID);
    expect(element10q.key).toBeNull();
    expect(element10qa.key).toBeNull();
  });

  it("raises Next.js notFound for an unknown document id", async () => {
    await expect(renderPageElement("aaaaaaaa-0000-4000-8000-0000000cafe0")).rejects.toThrowError();
  });
});

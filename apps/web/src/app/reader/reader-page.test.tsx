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

  // Regression (finding 5): the reader was not keyed by document, so client
  // state (selection, outline focus, notes) leaked across filings when
  // navigating. The page must render <EvidenceReader key={documentId}> so a
  // different document remounts the reader with fresh state.
  it("keys the EvidenceReader by documentId so navigation remounts it", async () => {
    const element10q = await renderPageElement(DOC_10Q_ID);
    const element10qa = await renderPageElement(DOC_10QA_ID);

    expect(element10q.type).toBe(EvidenceReader);
    expect(element10qa.type).toBe(EvidenceReader);
    expect(element10q.key).toBe(DOC_10Q_ID);
    expect(element10qa.key).toBe(DOC_10QA_ID);
    expect(element10q.key).not.toBe(element10qa.key);
  });

  it("raises Next.js notFound for an unknown document id", async () => {
    await expect(renderPageElement("aaaaaaaa-0000-4000-8000-0000000cafe0")).rejects.toThrowError();
  });
});

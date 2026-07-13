import { notFound } from "next/navigation";

import { EvidenceReader } from "@/components/EvidenceReader";
import { evidenceSource } from "@/lib/data";
import type { SectionRecord, SourceSpanRecord } from "@/lib/contracts";

export async function generateStaticParams() {
  const documents = await evidenceSource.listDocuments();
  return documents.map((doc) => ({ documentId: doc.id }));
}

export default async function ReaderPage({ params }: { params: Promise<{ documentId: string }> }) {
  const { documentId } = await params;
  const document = await evidenceSource.getDocument(documentId);
  if (!document) notFound();

  const documents = await evidenceSource.listDocuments();
  const facts = await evidenceSource.getFacts(document.entity_id);

  // Sections and spans across every version of this entity's documents:
  // duplicate comparison and restatement flagging must see sibling versions.
  const entityDocs = documents.filter((doc) => doc.entity_id === document.entity_id);
  const sections: SectionRecord[] = [];
  const spans: SourceSpanRecord[] = [];
  for (const doc of entityDocs) {
    sections.push(...(await evidenceSource.getSections(doc.id)));
    spans.push(...(await evidenceSource.getSpans(doc.id)));
  }

  return (
    <EvidenceReader
      documentId={documentId}
      documents={entityDocs}
      sections={sections}
      spans={spans}
      facts={facts}
    />
  );
}

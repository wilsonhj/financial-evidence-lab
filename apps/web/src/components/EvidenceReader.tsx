"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import type {
  DocumentMeta,
  FinancialFactRecord,
  SectionRecord,
  SourceSpanRecord,
} from "@/lib/contracts";
import { amendmentStatusFor, linkAmendments } from "@/lib/amendments";
import { duplicateGroupIndex, groupDuplicateFacts } from "@/lib/facts";
import { buildOutline } from "@/lib/outline";
import { addNote, emptyNotesState, removeNote, type NoteAnchor } from "@/lib/notes";
import { DocumentPane } from "./DocumentPane";
import { FactPanel } from "./FactPanel";
import { NotesPanel } from "./NotesPanel";
import { OutlineNav } from "./OutlineNav";

export interface EvidenceReaderProps {
  documentId: string;
  /** Every document version of the entity (for amendment linkage). */
  documents: DocumentMeta[];
  /** Sections across all entity document versions. */
  sections: SectionRecord[];
  /** Spans across all entity document versions. */
  spans: SourceSpanRecord[];
  /** All normalized facts of the entity. */
  facts: FinancialFactRecord[];
}

export function EvidenceReader({
  documentId,
  documents,
  sections,
  spans,
  facts,
}: EvidenceReaderProps) {
  const document = documents.find((doc) => doc.id === documentId);
  const ownSections = useMemo(
    () =>
      sections
        .filter((section) => section.document_version_id === documentId)
        .sort((a, b) => a.order - b.order),
    [sections, documentId],
  );
  const outline = useMemo(() => buildOutline(ownSections), [ownSections]);

  const spansById = useMemo(() => new Map(spans.map((record) => [record.id, record])), [spans]);
  const sectionsById = useMemo(
    () => new Map(sections.map((section) => [section.id, section])),
    [sections],
  );
  const documentsById = useMemo(() => new Map(documents.map((doc) => [doc.id, doc])), [documents]);

  const amendmentLinks = useMemo(() => linkAmendments(documents), [documents]);
  const amendment = amendmentStatusFor(documentId, amendmentLinks);

  const duplicateIndex = useMemo(() => duplicateGroupIndex(groupDuplicateFacts(facts)), [facts]);

  const docFacts = useMemo(
    () =>
      facts.filter(
        (record) =>
          spansById.get(record.fact.source_span_id)?.span.document_version_id === documentId,
      ),
    [facts, spansById, documentId],
  );

  const [activeSectionId, setActiveSectionId] = useState<string | null>(ownSections[0]?.id ?? null);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);
  const [notes, setNotes] = useState(emptyNotesState);

  const handleSelectSection = (sectionId: string) => {
    setActiveSectionId(sectionId);
    globalThis.document?.getElementById(`section-${sectionId}`)?.scrollIntoView();
  };

  const describeAnchor = (anchor: NoteAnchor): string => {
    if (anchor.kind === "section") {
      return `Section: ${sectionsById.get(anchor.id)?.title ?? anchor.id}`;
    }
    const span = spansById.get(anchor.id);
    const section = span ? sectionsById.get(span.span.section_id) : undefined;
    return `Span in ${section?.title ?? anchor.id}`;
  };

  const noteAnchor: NoteAnchor | null = selectedSpanId
    ? { kind: "span", id: selectedSpanId }
    : activeSectionId
      ? { kind: "section", id: activeSectionId }
      : null;

  if (!document) return null;

  return (
    <>
      <header className="page-main" style={{ paddingBottom: 0 }}>
        <h2 style={{ marginBottom: "0.2rem" }}>
          {document.form ?? "Filing"} — {document.accession}
        </h2>
        <p style={{ margin: 0, color: "var(--color-muted)", fontSize: "0.9rem" }}>
          Period {document.period_start} to {document.period_end} · Published{" "}
          {document.published_at.slice(0, 10)}
        </p>
      </header>

      {amendment.kind === "superseded" && (
        <aside className="reader-banner superseded" aria-label="Amendment notice">
          <span aria-hidden="true">&#9888;</span> <strong>Superseded.</strong> This filing was
          amended and restated by{" "}
          <Link href={`/reader/${amendment.byDocumentId}`}>
            {documentsById.get(amendment.byDocumentId)?.form ?? "an amendment"} (
            {documentsById.get(amendment.byDocumentId)?.accession})
          </Link>
          . Values here may no longer be authoritative.
        </aside>
      )}
      {amendment.kind === "amendment" && (
        <aside className="reader-banner" aria-label="Amendment notice">
          <strong>Amendment / restatement.</strong> This filing amends{" "}
          <Link href={`/reader/${amendment.amendsDocumentId}`}>
            {documentsById.get(amendment.amendsDocumentId)?.form ?? "the original filing"} (
            {documentsById.get(amendment.amendsDocumentId)?.accession})
          </Link>
          .
        </aside>
      )}

      <div className="reader-layout">
        <OutlineNav model={outline} activeId={activeSectionId} onSelect={handleSelectSection} />
        <main aria-label="Document reader">
          <DocumentPane
            sections={ownSections}
            spans={spans}
            selectedSpanId={selectedSpanId}
            onSelectSpan={setSelectedSpanId}
          />
        </main>
        <aside className="evidence-panel" aria-label="Evidence details">
          <FactPanel
            facts={docFacts}
            spansById={spansById}
            sectionsById={sectionsById}
            documentsById={documentsById}
            duplicateIndex={duplicateIndex}
            amendmentLinks={amendmentLinks}
            selectedSpanId={selectedSpanId}
          />
          <NotesPanel
            notes={notes}
            anchor={noteAnchor}
            anchorLabel={noteAnchor ? describeAnchor(noteAnchor) : "nothing selected"}
            onAdd={(anchor, body) => setNotes((state) => addNote(state, anchor, body))}
            onRemove={(noteId) => setNotes((state) => removeNote(state, noteId))}
            describeAnchor={describeAnchor}
          />
        </aside>
      </div>
    </>
  );
}

"use client";

import { useEffect, useMemo, useReducer } from "react";
import Link from "next/link";

import type {
  DocumentMeta,
  FinancialFactRecord,
  SectionRecord,
  SourceSpanRecord,
} from "../lib/contracts";
import type { CitationIntegrityFailure } from "../lib/citation-integrity";
import { amendmentStatusFor, linkAmendments } from "../lib/amendments";
import { formatPeriodRange } from "../lib/document-display";
import { duplicateGroupIndex, groupDuplicateFacts } from "../lib/facts";
import { buildOutline } from "../lib/outline";
import type { NoteAnchor } from "../lib/notes";
import { initReaderState, readerReducer } from "../lib/reader-state";
import { recordTiming } from "../lib/telemetry";
import { DocumentPane } from "./DocumentPane";
import { FactPanel } from "./FactPanel";
import { NotesPanel } from "./NotesPanel";
import { OutlineNav } from "./OutlineNav";

export interface EvidenceReaderProps {
  documentId: string;
  /** Every document of the entity (for amendment linkage). */
  documents: DocumentMeta[];
  /** Canonical sections of the selected target version. */
  sections: SectionRecord[];
  /** Verified target spans plus non-rendered sibling provenance spans. */
  spans: SourceSpanRecord[];
  /** All normalized facts of the entity. */
  facts: FinancialFactRecord[];
  /**
   * Provenance: section/span record id -> DocumentMeta.id, built by the data
   * loader from its per-document fetches. The UI attributes evidence to
   * documents ONLY through these maps — never by comparing
   * `document_version_id` (a different UUID namespace) with DocumentMeta.id.
   */
  documentIdBySectionId: Record<string, string>;
  documentIdBySpanId: Record<string, string>;
  /** Spans excluded fail-closed by citation verification. */
  integrityFailures: CitationIntegrityFailure[];
  /**
   * Span to select and scroll to on mount (from an Observatory candidate deep
   * link, `?span=`). Ignored unless it belongs to this document.
   */
  initialSpanId?: string | null;
}

export function EvidenceReader({
  documentId,
  documents,
  sections,
  spans,
  facts,
  documentIdBySectionId,
  documentIdBySpanId,
  integrityFailures,
  initialSpanId = null,
}: EvidenceReaderProps) {
  const document = documents.find((doc) => doc.id === documentId);
  const ownSections = useMemo(
    () =>
      sections
        .filter((section) => documentIdBySectionId[section.id] === documentId)
        .sort((a, b) => a.order - b.order),
    [sections, documentIdBySectionId, documentId],
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

  const integrityFailureBySpanId = useMemo(
    () => new Map(integrityFailures.map((failure) => [failure.spanId, failure])),
    [integrityFailures],
  );
  const ownIntegrityFailures = useMemo(
    () => integrityFailures.filter((failure) => documentIdBySpanId[failure.spanId] === documentId),
    [integrityFailures, documentIdBySpanId, documentId],
  );

  const docFacts = useMemo(
    () => facts.filter((record) => documentIdBySpanId[record.fact.source_span_id] === documentId),
    [facts, documentIdBySpanId, documentId],
  );

  // Only target spans are hash-verified before reaching this component (see
  // loadReaderData); any span attributed to this document is one of those.
  const verifiedSpanCount = useMemo(
    () => spans.filter((span) => documentIdBySpanId[span.id] === documentId).length,
    [spans, documentIdBySpanId, documentId],
  );

  useEffect(() => {
    const ms = typeof performance !== "undefined" ? performance.now() : 0;
    recordTiming("reader.load", ms, { documentId });
    if (verifiedSpanCount > 0) {
      recordTiming("reader.first_verified_span", ms, { documentId, count: verifiedSpanCount });
    }
    // Re-run when the document changes (component can stay mounted across
    // client-side navigation — see the reducer note below).
  }, [documentId, verifiedSpanCount]);

  // Only honour a deep-linked span that belongs to this document; a foreign
  // span id from the URL must never select or scroll cross-document evidence.
  const deepLinkedSpanId =
    initialSpanId && documentIdBySpanId[initialSpanId] === documentId ? initialSpanId : null;
  const deepLinkedSectionId = deepLinkedSpanId
    ? (spansById.get(deepLinkedSpanId)?.span.section_id ?? null)
    : null;

  const initialActiveSectionId = deepLinkedSectionId ?? ownSections[0]?.id ?? null;

  // Single reducer for selection, outline focus, and the notes overlay, keyed
  // by documentId (see lib/reader-state.ts). Without a key={documentId}
  // remount at the page level, this component instance can stay mounted
  // across a client-side navigation to a different filing; when that happens
  // state.documentId no longer matches the documentId prop, so a "reset"
  // action is dispatched during render (an established React pattern for
  // adjusting state from a prop change) to derive fresh state for the new
  // document before anything paints.
  const [state, dispatch] = useReducer(
    readerReducer,
    undefined,
    (): ReturnType<typeof initReaderState> =>
      initReaderState(documentId, initialActiveSectionId, deepLinkedSpanId),
  );
  if (state.documentId !== documentId) {
    dispatch({
      type: "reset",
      documentId,
      activeSectionId: initialActiveSectionId,
      selectedSpanId: deepLinkedSpanId,
    });
  }
  const { activeSectionId, selectedSpanId, notes } = state;

  useEffect(() => {
    if (deepLinkedSectionId) {
      globalThis.document?.getElementById(`section-${deepLinkedSectionId}`)?.scrollIntoView();
    }
    // Re-run when the document (and therefore its deep link) changes, not
    // just on mount, now that the reader can stay mounted across navigation.
  }, [documentId, deepLinkedSectionId]);

  const handleSelectSection = (sectionId: string) => {
    dispatch({ type: "select-section", sectionId });
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
          Period {formatPeriodRange(document)} · Published {document.published_at.slice(0, 10)}
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
      {ownIntegrityFailures.length > 0 && (
        <aside className="reader-banner citation-error" role="alert">
          <span aria-hidden="true">&#9888;</span> <strong>Citation integrity error.</strong>{" "}
          {ownIntegrityFailures.length === 1
            ? "1 cited source span"
            : `${ownIntegrityFailures.length} cited source spans`}{" "}
          in this filing failed offset or hash verification and{" "}
          {ownIntegrityFailures.length === 1 ? "is" : "are"} not highlighted or quoted.
        </aside>
      )}

      <div className="reader-layout">
        <OutlineNav model={outline} activeId={activeSectionId} onSelect={handleSelectSection} />
        <main id="main-content" tabIndex={-1} aria-label="Document reader">
          <DocumentPane
            sections={ownSections}
            spans={spans}
            selectedSpanId={selectedSpanId}
            onSelectSpan={(spanId) => dispatch({ type: "select-span", spanId })}
          />
        </main>
        <aside className="evidence-panel" aria-label="Evidence details">
          <FactPanel
            facts={docFacts}
            spansById={spansById}
            sectionsById={sectionsById}
            documentsById={documentsById}
            documentIdBySpanId={documentIdBySpanId}
            integrityFailureBySpanId={integrityFailureBySpanId}
            duplicateIndex={duplicateIndex}
            amendmentLinks={amendmentLinks}
            selectedSpanId={selectedSpanId}
          />
          <NotesPanel
            notes={notes}
            anchor={noteAnchor}
            anchorLabel={noteAnchor ? describeAnchor(noteAnchor) : "nothing selected"}
            onAdd={(anchor, body) => dispatch({ type: "add-note", anchor, body })}
            onRemove={(noteId) => dispatch({ type: "remove-note", noteId })}
            describeAnchor={describeAnchor}
          />
        </aside>
      </div>
    </>
  );
}

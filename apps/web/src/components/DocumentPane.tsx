"use client";

import type { SectionRecord, SourceSpanRecord } from "@/lib/contracts";
import { segmentSection } from "@/lib/spans";

export interface DocumentPaneProps {
  sections: SectionRecord[];
  spans: SourceSpanRecord[];
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string | null) => void;
}

function headingLevel(depth: number): "h2" | "h3" | "h4" {
  if (depth <= 1) return "h2";
  if (depth === 2) return "h3";
  return "h4";
}

/**
 * Rendered document content synchronized with the extracted sections. Source
 * spans are highlighted with background + dotted underline + a citation glyph
 * (never color alone) and are focusable buttons that drive the fact panel.
 */
export function DocumentPane({ sections, spans, selectedSpanId, onSelectSpan }: DocumentPaneProps) {
  return (
    <article className="document-pane" aria-label="Filing content">
      {sections.map((section) => {
        const Heading = headingLevel(section.level);
        const segments = segmentSection(section.content, spans, section.id);
        return (
          <section key={section.id} id={`section-${section.id}`} aria-label={section.title}>
            <Heading className={`section-heading depth-${section.level}`}>{section.title}</Heading>
            <p className="section-content">
              {segments.map((segment) =>
                segment.spanIds.length === 0 ? (
                  <span key={`${section.id}-${segment.start}`}>{segment.text}</span>
                ) : (
                  <button
                    key={`${section.id}-${segment.start}`}
                    type="button"
                    className="span-mark"
                    aria-pressed={segment.spanIds.includes(selectedSpanId ?? "")}
                    onClick={() => {
                      const spanId = segment.spanIds[0] ?? null;
                      onSelectSpan(spanId === selectedSpanId ? null : spanId);
                    }}
                  >
                    <span className="visually-hidden">Cited source span: </span>
                    {segment.text}
                    <span className="span-glyph" aria-hidden="true">
                      &dagger;
                    </span>
                  </button>
                ),
              )}
            </p>
          </section>
        );
      })}
    </article>
  );
}

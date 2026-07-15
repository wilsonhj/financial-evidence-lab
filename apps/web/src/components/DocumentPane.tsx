"use client";

import { useMemo } from "react";

import type { SectionRecord, SourceSpanRecord } from "../lib/contracts";
import { resolveSegmentSelection, segmentSection } from "../lib/spans";

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
 *
 * Clicking (or keyboard-activating — the segments are real buttons) a segment
 * covered by several spans selects the NARROWEST covering span so nested
 * spans stay reachable; activating a segment whose covering spans include the
 * current selection toggles it off.
 */
export function DocumentPane({ sections, spans, selectedSpanId, onSelectSpan }: DocumentPaneProps) {
  // Memoized so selection changes re-render without re-segmenting every
  // section. Span offsets are GLOBAL canonical offsets; segmentSection derives
  // the section-local render anchors internally (last-moment derivation).
  const segmentedSections = useMemo(
    () =>
      sections.map((section) => ({
        section,
        segments: segmentSection(section, spans),
      })),
    [sections, spans],
  );
  // Span length is coordinate-system independent (global end - global start).
  const spanLengthById = useMemo(
    () =>
      new Map(spans.map((record) => [record.id, record.span.end_char - record.span.start_char])),
    [spans],
  );

  return (
    <article className="document-pane" aria-label="Filing content">
      {segmentedSections.map(({ section, segments }) => {
        const Heading = headingLevel(section.level);
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
                    onClick={() =>
                      onSelectSpan(
                        resolveSegmentSelection(segment.spanIds, selectedSpanId, spanLengthById),
                      )
                    }
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

"use client";

import type {
  DocumentMeta,
  FinancialFactRecord,
  SectionRecord,
  SourceSpanRecord,
} from "@/lib/contracts";
import type { AmendmentLink } from "@/lib/amendments";
import type { DuplicateFactGroup } from "@/lib/facts";
import { formatScaledValue, scaledDecimal } from "@/lib/facts";
import { extractSpanText } from "@/lib/spans";

export interface FactPanelProps {
  facts: FinancialFactRecord[];
  spansById: Map<string, SourceSpanRecord>;
  sectionsById: Map<string, SectionRecord>;
  documentsById: Map<string, DocumentMeta>;
  duplicateIndex: Map<string, DuplicateFactGroup>;
  amendmentLinks: AmendmentLink[];
  selectedSpanId: string | null;
}

function periodLabel(period: FinancialFactRecord["fact"]["period"]): string {
  return period.type === "instant"
    ? `As of ${period.instant ?? "?"}`
    : `${period.start ?? "?"} to ${period.end ?? "?"}`;
}

function locate(
  record: FinancialFactRecord,
  spansById: Map<string, SourceSpanRecord>,
  sectionsById: Map<string, SectionRecord>,
  documentsById: Map<string, DocumentMeta>,
): { span?: SourceSpanRecord; section?: SectionRecord; document?: DocumentMeta } {
  const span = spansById.get(record.fact.source_span_id);
  const section = span ? sectionsById.get(span.span.section_id) : undefined;
  const document = span ? documentsById.get(span.span.document_version_id) : undefined;
  return { span, section, document };
}

/**
 * True when an amendment reports a different canonical value than the filing
 * it amends — i.e. the fact was actually restated, not merely repeated.
 */
function isRestatementGroup(group: DuplicateFactGroup, ctx: FactPanelProps): boolean {
  const valuesByDoc = new Map<string, Set<string>>();
  for (const record of group.records) {
    const docId = ctx.spansById.get(record.fact.source_span_id)?.span.document_version_id;
    if (!docId) continue;
    const values = valuesByDoc.get(docId) ?? new Set<string>();
    values.add(scaledDecimal(record.fact.value, record.fact.scale));
    valuesByDoc.set(docId, values);
  }
  return ctx.amendmentLinks.some((link) => {
    const original = valuesByDoc.get(link.originalId);
    const amended = valuesByDoc.get(link.amendmentId);
    if (!original || !amended) return false;
    return [...amended].some((value) => !original.has(value));
  });
}

function DuplicateComparison({ group, ctx }: { group: DuplicateFactGroup; ctx: FactPanelProps }) {
  const restatement = isRestatementGroup(group, ctx);
  const conflicting = group.status === "conflicting";
  return (
    <div className="duplicate-compare">
      <p>
        {conflicting ? (
          <strong className="badge badge-warning">
            <span aria-hidden="true">&#9888;</span> Inconsistent duplicate values
          </strong>
        ) : (
          <span className="badge badge-ok">
            <span aria-hidden="true">&#10003;</span> Duplicates consistent
          </span>
        )}{" "}
        {restatement && <span className="badge badge-info">Restated by amendment</span>}
      </p>
      <table>
        <caption className="visually-hidden">
          Reported locations of this fact and their values
        </caption>
        <thead>
          <tr>
            <th scope="col">Filing</th>
            <th scope="col">Section</th>
            <th scope="col">Value</th>
          </tr>
        </thead>
        <tbody>
          {group.records.map((record) => {
            const { section, document } = locate(
              record,
              ctx.spansById,
              ctx.sectionsById,
              ctx.documentsById,
            );
            return (
              <tr key={record.id}>
                <td>{document?.form ?? "?"}</td>
                <td>{section?.title ?? "Unknown section"}</td>
                <td>
                  {formatScaledValue(record.fact)} {record.fact.unit}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FactCard({ record, ctx }: { record: FinancialFactRecord; ctx: FactPanelProps }) {
  const { fact } = record;
  const { span, section } = locate(record, ctx.spansById, ctx.sectionsById, ctx.documentsById);
  const rawText = span && section ? extractSpanText(section, span) : "";
  const group = ctx.duplicateIndex.get(record.id);
  const selected = ctx.selectedSpanId !== null && fact.source_span_id === ctx.selectedSpanId;

  return (
    <li className={`fact-card${selected ? " selected" : ""}`}>
      <h3>{fact.label ?? fact.concept}</h3>
      {rawText && (
        <blockquote className="fact-source" cite={fact.source_span_id}>
          {rawText}
        </blockquote>
      )}
      <dl>
        <dt>Concept</dt>
        <dd>{fact.concept}</dd>
        <dt>Normalized</dt>
        <dd>
          {formatScaledValue(fact)} {fact.unit}
        </dd>
        <dt>Raw value</dt>
        <dd>
          {fact.value} (scale 10^{fact.scale}) = {scaledDecimal(fact.value, fact.scale)}
        </dd>
        <dt>Unit</dt>
        <dd>{fact.unit}</dd>
        <dt>Period</dt>
        <dd>{periodLabel(fact.period)}</dd>
        <dt>Dimensions</dt>
        <dd>
          {fact.dimensions && Object.keys(fact.dimensions).length > 0
            ? Object.entries(fact.dimensions)
                .map(([key, value]) => `${key} = ${value}`)
                .join("; ")
            : "none"}
        </dd>
        <dt>Basis</dt>
        <dd>
          {fact.reported_or_derived}
          {typeof fact.confidence === "number" ? `, confidence ${fact.confidence}` : ""}
        </dd>
      </dl>
      {group && <DuplicateComparison group={group} ctx={ctx} />}
    </li>
  );
}

/**
 * Extracted-fact panel: raw source text, normalized value, unit, scale, and
 * dimensions per fact, plus duplicate comparison and restatement flags.
 */
export function FactPanel(props: FactPanelProps) {
  const visible = props.selectedSpanId
    ? props.facts.filter((record) => record.fact.source_span_id === props.selectedSpanId)
    : props.facts;

  return (
    <section className="panel-card" aria-label="Extracted facts">
      <h2>
        Extracted facts{" "}
        {props.selectedSpanId ? "(selected span)" : `(${visible.length} in this filing)`}
      </h2>
      {visible.length === 0 ? (
        <p>No extracted facts for this selection.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {visible.map((record) => (
            <FactCard key={record.id} record={record} ctx={props} />
          ))}
        </ul>
      )}
    </section>
  );
}

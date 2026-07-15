// Node built-in import is a compile-time server-only tripwire for bearer auth.
import "node:process";

import type { components } from "@fel/contracts";

import type {
  DocumentMeta,
  NormalizedFinancialFact,
  ReaderResponse,
  SourceSpan,
} from "../contracts";
import type { EvidenceSource } from "./evidence-source";
import { matchesReaderResponseSchema } from "./reader-contract-validator";

export type ErrorEnvelope = components["schemas"]["Error"];
export type EvidenceFailureKind =
  "authentication" | "forbidden" | "conflict" | "invalid_scope" | "unavailable";

/** Safe, UI-facing classification of an API or transport failure. */
export class EvidenceApiError extends Error {
  readonly status: number;
  readonly path: string;
  readonly kind: EvidenceFailureKind;
  readonly code?: string;
  readonly requestId?: string;

  constructor(status: number, path: string, kind: EvidenceFailureKind, envelope?: ErrorEnvelope) {
    // Deliberately exclude upstream message/details and request headers. Those
    // may contain sensitive implementation context and must never render.
    super(`Evidence service request failed (${kind}, HTTP ${status || "transport"})`);
    this.name = "EvidenceApiError";
    this.status = status;
    this.path = path;
    this.kind = kind;
    this.code = envelope?.error.code;
    this.requestId = envelope?.error.request_id;
  }
}

/** The API returned 2xx JSON that violates the frozen ADR-0005 contract. */
export class EvidenceContractError extends Error {
  constructor(reason: string) {
    super(`Evidence response failed contract validation: ${reason}`);
    this.name = "EvidenceContractError";
  }
}

export type BearerTokenProvider = string | (() => string | Promise<string>);

export interface HttpEvidenceSourceOptions {
  baseUrl: string;
  entityIds: readonly string[];
  token: BearerTokenProvider;
  asOf?: string;
  corpusVersionId?: string;
  fetchImpl?: typeof fetch;
}

function failureKind(status: number): EvidenceFailureKind {
  if (status === 401) return "authentication";
  if (status === 403) return "forbidden";
  if (status === 409) return "conflict";
  if (status === 422) return "invalid_scope";
  return "unavailable";
}

function object(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new EvidenceContractError(`${path} must be an object`);
  }
  return value as Record<string, unknown>;
}

function string(value: unknown, path: string): string {
  if (typeof value !== "string") throw new EvidenceContractError(`${path} must be a string`);
  return value;
}

function integer(value: unknown, path: string): number {
  if (!Number.isInteger(value)) throw new EvidenceContractError(`${path} must be an integer`);
  return value as number;
}

function array(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) throw new EvidenceContractError(`${path} must be an array`);
  return value;
}

function optionalString(value: unknown, path: string): string | undefined {
  if (value === undefined) return undefined;
  return string(value, path);
}

function assertTimestamp(value: unknown, path: string): string {
  const timestamp = string(value, path);
  if (Number.isNaN(Date.parse(timestamp))) {
    throw new EvidenceContractError(`${path} must be a valid timestamp`);
  }
  return timestamp;
}

function assertDocumentMeta(value: unknown, path: string): asserts value is DocumentMeta {
  const meta = object(value, path);
  for (const key of [
    "id",
    "entity_id",
    "accession",
    "source_url",
    "content_hash",
    "published_at",
    "ingested_at",
  ] as const) {
    string(meta[key], `${path}.${key}`);
  }
  assertTimestamp(meta.published_at, `${path}.published_at`);
  assertTimestamp(meta.ingested_at, `${path}.ingested_at`);
  for (const key of [
    "form",
    "filed_at",
    "period_start",
    "period_end",
    "valid_from",
    "valid_to",
  ] as const) {
    optionalString(meta[key], `${path}.${key}`);
  }
}

function assertSpan(value: unknown, path: string): asserts value is SourceSpan {
  const span = object(value, path);
  string(span.document_version_id, `${path}.document_version_id`);
  string(span.section_id, `${path}.section_id`);
  integer(span.start_char, `${path}.start_char`);
  integer(span.end_char, `${path}.end_char`);
  string(span.text_hash, `${path}.text_hash`);
  if (span.page !== undefined) integer(span.page, `${path}.page`);
}

function assertFact(value: unknown, path: string): asserts value is NormalizedFinancialFact {
  const fact = object(value, path);
  for (const key of [
    "entity_id",
    "concept",
    "value",
    "unit",
    "source_span_id",
    "reported_or_derived",
  ] as const) {
    string(fact[key], `${path}.${key}`);
  }
  integer(fact.scale, `${path}.scale`);
  const period = object(fact.period, `${path}.period`);
  string(period.type, `${path}.period.type`);
  optionalString(period.instant, `${path}.period.instant`);
  optionalString(period.start, `${path}.period.start`);
  optionalString(period.end, `${path}.period.end`);
  if (fact.dimensions !== undefined) object(fact.dimensions, `${path}.dimensions`);
  if (fact.confidence !== undefined && typeof fact.confidence !== "number") {
    throw new EvidenceContractError(`${path}.confidence must be a number`);
  }
}

type Block = ReaderResponse["document"] | ReaderResponse["siblings"][number];

function assertBlock(value: unknown, path: string, target: boolean): asserts value is Block {
  const block = object(value, path);
  assertDocumentMeta(block.meta, `${path}.meta`);
  const versionId = string(block.document_version_id, `${path}.document_version_id`);
  const meta = block.meta as DocumentMeta;
  const sectionIds = new Set<string>();

  if (target) {
    for (const [index, raw] of array(block.sections, `${path}.sections`).entries()) {
      const sectionPath = `${path}.sections[${index}]`;
      const section = object(raw, sectionPath);
      const id = string(section.id, `${sectionPath}.id`);
      if (sectionIds.has(id)) throw new EvidenceContractError(`${sectionPath}.id is duplicated`);
      sectionIds.add(id);
      if (string(section.document_version_id, `${sectionPath}.document_version_id`) !== versionId) {
        throw new EvidenceContractError(`${sectionPath} crosses document versions`);
      }
      optionalString(section.parent_id, `${sectionPath}.parent_id`);
      string(section.heading, `${sectionPath}.heading`);
      for (const [part, heading] of array(
        section.heading_path,
        `${sectionPath}.heading_path`,
      ).entries()) {
        string(heading, `${sectionPath}.heading_path[${part}]`);
      }
      integer(section.ord, `${sectionPath}.ord`);
      const start = integer(section.start_char, `${sectionPath}.start_char`);
      const end = integer(section.end_char, `${sectionPath}.end_char`);
      const content = string(section.content, `${sectionPath}.content`);
      if (start < 0 || end < start || content.length !== end - start) {
        throw new EvidenceContractError(`${sectionPath} has an inconsistent canonical range`);
      }
    }
  }

  const spanIds = new Set<string>();
  for (const [index, raw] of array(block.spans, `${path}.spans`).entries()) {
    const recordPath = `${path}.spans[${index}]`;
    const record = object(raw, recordPath);
    const id = string(record.id, `${recordPath}.id`);
    if (spanIds.has(id)) throw new EvidenceContractError(`${recordPath}.id is duplicated`);
    spanIds.add(id);
    assertSpan(record.span, `${recordPath}.span`);
    const span = record.span as SourceSpan;
    if (span.document_version_id !== versionId) {
      throw new EvidenceContractError(`${recordPath} crosses document versions`);
    }
    if (target && !sectionIds.has(span.section_id)) {
      throw new EvidenceContractError(`${recordPath}.span.section_id is dangling`);
    }
  }

  const factIds = new Set<string>();
  for (const [index, raw] of array(block.facts, `${path}.facts`).entries()) {
    const recordPath = `${path}.facts[${index}]`;
    const record = object(raw, recordPath);
    const id = string(record.id, `${recordPath}.id`);
    if (factIds.has(id)) throw new EvidenceContractError(`${recordPath}.id is duplicated`);
    factIds.add(id);
    if (string(record.document_version_id, `${recordPath}.document_version_id`) !== versionId) {
      throw new EvidenceContractError(`${recordPath} crosses document versions`);
    }
    optionalString(record.duplicate_of, `${recordPath}.duplicate_of`);
    optionalString(record.restates, `${recordPath}.restates`);
    assertFact(record.fact, `${recordPath}.fact`);
    const fact = record.fact as NormalizedFinancialFact;
    if (fact.entity_id !== meta.entity_id) {
      throw new EvidenceContractError(`${recordPath}.fact belongs to another entity`);
    }
    if (!spanIds.has(fact.source_span_id)) {
      throw new EvidenceContractError(`${recordPath}.fact.source_span_id is dangling`);
    }
  }
}

function validateReaderResponse(
  value: unknown,
  requestedDocumentId: string,
  requestedAsOf?: string,
  requestedCorpusVersionId?: string,
): ReaderResponse {
  if (!matchesReaderResponseSchema(value)) {
    throw new EvidenceContractError("payload does not match reader-response/v1");
  }
  const response = object(value, "reader");
  const effectiveAsOf = assertTimestamp(response.as_of, "reader.as_of");
  const corpusVersionId =
    response.corpus_version_id === null
      ? null
      : string(response.corpus_version_id, "reader.corpus_version_id");
  string(response.selection_policy, "reader.selection_policy");
  assertBlock(response.document, "reader.document", true);
  const document = response.document as ReaderResponse["document"];

  if (document.meta.id !== requestedDocumentId) {
    throw new EvidenceContractError("target document id differs from the request");
  }
  if (requestedAsOf && Date.parse(effectiveAsOf) !== Date.parse(requestedAsOf)) {
    throw new EvidenceContractError("effective as_of differs from the requested cutoff");
  }
  if ((requestedCorpusVersionId ?? null) !== corpusVersionId) {
    throw new EvidenceContractError("effective corpus pin differs from the requested pin");
  }
  if (corpusVersionId && response.selection_policy === "latest_parsed") {
    throw new EvidenceContractError("pinned response reports latest_parsed selection");
  }
  if (!corpusVersionId && response.selection_policy === "corpus_pinned") {
    throw new EvidenceContractError("unpinned response reports corpus_pinned selection");
  }

  const cutoff = Date.parse(effectiveAsOf);
  if (Date.parse(document.meta.published_at) > cutoff) {
    throw new EvidenceContractError("target document is newer than the effective cutoff");
  }

  const siblingIds = new Set<string>();
  for (const [index, raw] of array(response.siblings, "reader.siblings").entries()) {
    const siblingPath = `reader.siblings[${index}]`;
    assertBlock(raw, siblingPath, false);
    const sibling = raw as ReaderResponse["siblings"][number];
    if (
      sibling.meta.id === document.meta.id ||
      siblingIds.has(sibling.meta.id) ||
      sibling.meta.entity_id !== document.meta.entity_id
    ) {
      throw new EvidenceContractError(`${siblingPath} is not a unique same-entity sibling`);
    }
    siblingIds.add(sibling.meta.id);
    if (Date.parse(sibling.meta.published_at) > cutoff) {
      throw new EvidenceContractError(`${siblingPath} is newer than the effective cutoff`);
    }
  }

  const versionOwners = new Map<string, string>();
  const spanOwners = new Map<string, string>();
  const factOwners = new Map<string, string>();
  const blocks = [document, ...(response.siblings as ReaderResponse["siblings"])];
  for (const block of blocks) {
    const documentId = block.meta.id;
    const priorVersionOwner = versionOwners.get(block.document_version_id);
    if (priorVersionOwner) {
      throw new EvidenceContractError(
        `document version is shared by ${priorVersionOwner} and ${documentId}`,
      );
    }
    versionOwners.set(block.document_version_id, documentId);
    for (const record of block.spans) {
      const priorSpanOwner = spanOwners.get(record.id);
      if (priorSpanOwner) {
        throw new EvidenceContractError(
          `source span id is shared by ${priorSpanOwner} and ${documentId}`,
        );
      }
      spanOwners.set(record.id, documentId);
    }
    for (const record of block.facts) {
      const priorFactOwner = factOwners.get(record.id);
      if (priorFactOwner) {
        throw new EvidenceContractError(
          `financial fact id is shared by ${priorFactOwner} and ${documentId}`,
        );
      }
      factOwners.set(record.id, documentId);
    }
  }
  for (const block of blocks) {
    for (const record of block.facts) {
      for (const [name, target] of [
        ["duplicate_of", record.duplicate_of],
        ["restates", record.restates],
      ] as const) {
        if (target && (target === record.id || !factOwners.has(target))) {
          throw new EvidenceContractError(`${name} does not resolve to another response fact`);
        }
      }
    }
  }

  return response as unknown as ReaderResponse;
}

function parseErrorEnvelope(value: unknown): ErrorEnvelope | undefined {
  try {
    const root = object(value, "error envelope");
    const error = object(root.error, "error envelope.error");
    string(error.code, "error envelope.error.code");
    string(error.message, "error envelope.error.message");
    string(error.request_id, "error envelope.error.request_id");
    return value as ErrorEnvelope;
  } catch {
    return undefined;
  }
}

export class HttpEvidenceSource implements EvidenceSource {
  private readonly baseUrl: string;
  private readonly entityIds: readonly string[];
  private readonly token: BearerTokenProvider;
  private readonly asOf?: string;
  private readonly corpusVersionId?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: HttpEvidenceSourceOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.entityIds = options.entityIds;
    this.token = options.token;
    this.asOf = options.asOf;
    this.corpusVersionId = options.corpusVersionId;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  private async request(path: string): Promise<Response> {
    let token: string;
    try {
      token = typeof this.token === "function" ? await this.token() : this.token;
    } catch {
      throw new EvidenceApiError(0, path, "authentication");
    }
    try {
      return await this.fetchImpl(`${this.baseUrl}${path}`, {
        cache: "no-store",
        headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
      });
    } catch {
      throw new EvidenceApiError(0, path, "unavailable");
    }
  }

  private async toApiError(response: Response, path: string): Promise<EvidenceApiError> {
    let envelope: ErrorEnvelope | undefined;
    try {
      envelope = parseErrorEnvelope(await response.json());
    } catch {
      // Status classification is sufficient when the body is not JSON.
    }
    return new EvidenceApiError(response.status, path, failureKind(response.status), envelope);
  }

  private async json(response: Response, path: string): Promise<unknown> {
    try {
      return await response.json();
    } catch {
      throw new EvidenceContractError(`${path} returned invalid JSON`);
    }
  }

  private async getJson(path: string): Promise<unknown> {
    const response = await this.request(path);
    if (!response.ok) throw await this.toApiError(response, path);
    return this.json(response, path);
  }

  async listDocuments(): Promise<DocumentMeta[]> {
    const query = this.asOf ? `?as_of=${encodeURIComponent(this.asOf)}` : "";
    const perEntity = await Promise.all(
      this.entityIds.map(async (entityId) => {
        const path = `/v1/entities/${entityId}/documents${query}`;
        const raw = array(await this.getJson(path), path);
        return raw.map((value, index) => {
          assertDocumentMeta(value, `${path}[${index}]`);
          if (this.asOf && Date.parse(value.published_at) > Date.parse(this.asOf)) {
            throw new EvidenceContractError(`${path}[${index}] is newer than the requested cutoff`);
          }
          return value;
        });
      }),
    );
    const candidates = perEntity
      .flat()
      .sort(
        (a, b) =>
          Date.parse(a.published_at) - Date.parse(b.published_at) || a.id.localeCompare(b.id),
      );
    const unique = [...new Map(candidates.map((document) => [document.id, document])).values()];
    if (!this.corpusVersionId) return unique;

    // Entity listings have no corpus-pin parameter in contract v0.2.0. Treat
    // them as discovery only, then fail closed by resolving every advertised
    // document through the pinned composite endpoint. A 404 means absent from
    // the selected snapshot and is filtered; every other error aborts.
    const pinned: DocumentMeta[] = [];
    const concurrency = 6;
    for (let offset = 0; offset < unique.length; offset += concurrency) {
      const batch = unique.slice(offset, offset + concurrency);
      const resolved = await Promise.all(batch.map((document) => this.getReader(document.id)));
      for (const reader of resolved) {
        if (reader) pinned.push(reader.document.meta);
      }
    }
    return pinned.sort(
      (a, b) => Date.parse(a.published_at) - Date.parse(b.published_at) || a.id.localeCompare(b.id),
    );
  }

  async getReader(documentId: string): Promise<ReaderResponse | null> {
    const query = new URLSearchParams();
    if (this.asOf) query.set("as_of", this.asOf);
    if (this.corpusVersionId) query.set("corpus_version_id", this.corpusVersionId);
    const suffix = query.size > 0 ? `?${query.toString()}` : "";
    const path = `/v1/documents/${encodeURIComponent(documentId)}/reader${suffix}`;
    const response = await this.request(path);
    if (response.status === 404) return null;
    if (!response.ok) throw await this.toApiError(response, path);
    return validateReaderResponse(
      await this.json(response, path),
      documentId,
      this.asOf,
      this.corpusVersionId,
    );
  }
}

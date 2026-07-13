import type {
  DocumentMeta,
  FinancialFactRecord,
  SectionRecord,
  SourceSpanRecord,
} from "../contracts";
import type { EvidenceSource, EvidenceSourceCapabilities } from "./evidence-source";

/** Contract error envelope (packages/contracts/schemas/error.schema.json). */
export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id: string;
  };
}

/**
 * Typed failure for non-404 evidence API errors. Carries the contract error
 * envelope (code/message/request_id) when the response body parses as one.
 */
export class EvidenceApiError extends Error {
  readonly status: number;
  readonly path: string;
  readonly envelope?: ErrorEnvelope;

  constructor(status: number, path: string, envelope?: ErrorEnvelope) {
    super(
      envelope
        ? `Evidence API error ${status} on ${path}: ${envelope.error.code} — ${envelope.error.message} (request ${envelope.error.request_id})`
        : `Evidence API error ${status} on ${path}`,
    );
    this.name = "EvidenceApiError";
    this.status = status;
    this.path = path;
    this.envelope = envelope;
  }

  get code(): string | undefined {
    return this.envelope?.error.code;
  }

  get requestId(): string | undefined {
    return this.envelope?.error.request_id;
  }
}

/** Static bearer token or an (async) provider for one. */
export type BearerTokenProvider = string | (() => string | Promise<string>);

export interface HttpEvidenceSourceOptions {
  baseUrl: string;
  /**
   * Entities whose documents this source serves. `listDocuments` fetches
   * every entity's documents (the contract only exposes per-entity listing)
   * and merges them into one deterministic ordering.
   */
  entityIds: readonly string[];
  /** apps/api requires a bearer token on every route. */
  token: BearerTokenProvider;
  /**
   * Optional point-in-time cutoff, propagated as the `as_of` query parameter
   * on document listing (a core contract invariant).
   */
  asOf?: string;
  fetchImpl?: typeof fetch;
}

/**
 * HTTP-backed EvidenceSource for the ingestion API (M1-INGESTION, apps/api).
 *
 * Document listing/detail bind to the endpoints in the frozen OpenAPI
 * contract (GET /v1/entities/{entityId}/documents, GET /v1/documents/{id}).
 * Section, span, and fact listing endpoints are not part of the contract yet,
 * so `capabilities` advertises them as unavailable and the reader renders a
 * graceful "details not yet available" state instead of calling them.
 */
export class HttpEvidenceSource implements EvidenceSource {
  readonly capabilities: EvidenceSourceCapabilities = {
    sections: false,
    spans: false,
    facts: false,
  };

  private readonly baseUrl: string;
  private readonly entityIds: readonly string[];
  private readonly token: BearerTokenProvider;
  private readonly asOf?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: HttpEvidenceSourceOptions) {
    this.baseUrl = options.baseUrl;
    this.entityIds = options.entityIds;
    this.token = options.token;
    this.asOf = options.asOf;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  private async request(path: string): Promise<Response> {
    const token = typeof this.token === "function" ? await this.token() : this.token;
    return this.fetchImpl(`${this.baseUrl}${path}`, {
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
      },
    });
  }

  /** Builds the typed error, attaching the contract envelope when parseable. */
  private async toApiError(response: Response, path: string): Promise<EvidenceApiError> {
    let envelope: ErrorEnvelope | undefined;
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "error" in body &&
        typeof (body as ErrorEnvelope).error === "object" &&
        (body as ErrorEnvelope).error !== null &&
        typeof (body as ErrorEnvelope).error.code === "string" &&
        typeof (body as ErrorEnvelope).error.message === "string"
      ) {
        envelope = body as ErrorEnvelope;
      }
    } catch {
      // Non-JSON error body; report status only.
    }
    return new EvidenceApiError(response.status, path, envelope);
  }

  private async getJson<T>(path: string): Promise<T> {
    const response = await this.request(path);
    if (!response.ok) {
      throw await this.toApiError(response, path);
    }
    return (await response.json()) as T;
  }

  async listDocuments(): Promise<DocumentMeta[]> {
    const query = this.asOf ? `?as_of=${encodeURIComponent(this.asOf)}` : "";
    const perEntity = await Promise.all(
      this.entityIds.map((entityId) =>
        this.getJson<DocumentMeta[]>(`/v1/entities/${entityId}/documents${query}`),
      ),
    );
    // Deterministic merged ordering regardless of entity order or API paging:
    // published instant (epoch), then id.
    return perEntity
      .flat()
      .sort(
        (a, b) =>
          Date.parse(a.published_at) - Date.parse(b.published_at) || a.id.localeCompare(b.id),
      );
  }

  async getDocument(documentId: string): Promise<DocumentMeta | null> {
    const path = `/v1/documents/${documentId}`;
    const response = await this.request(path);
    // Only a true API 404 means "no such document"; every other failure is a
    // real error and must surface as one (never as notFound()).
    if (response.status === 404) return null;
    if (!response.ok) throw await this.toApiError(response, path);
    return (await response.json()) as DocumentMeta;
  }

  getSections(documentId: string): Promise<SectionRecord[]> {
    return Promise.reject(
      new Error(
        `Section listing for document ${documentId} is not in the ingestion API contract yet (lands with M1-INGESTION); check capabilities.sections before calling.`,
      ),
    );
  }

  getSpans(documentId: string): Promise<SourceSpanRecord[]> {
    return Promise.reject(
      new Error(
        `Span listing for document ${documentId} is not in the ingestion API contract yet (lands with M1-INGESTION); check capabilities.spans before calling.`,
      ),
    );
  }

  getFacts(entityId: string): Promise<FinancialFactRecord[]> {
    return Promise.reject(
      new Error(
        `Fact listing for entity ${entityId} is not in the ingestion API contract yet (lands with M1-INGESTION); check capabilities.facts before calling.`,
      ),
    );
  }
}

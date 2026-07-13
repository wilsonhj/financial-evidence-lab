import type {
  DocumentMeta,
  FinancialFactRecord,
  SectionRecord,
  SourceSpanRecord,
} from "../contracts";
import type { EvidenceSource } from "./evidence-source";

/**
 * HTTP-backed EvidenceSource for the ingestion API (M1-INGESTION, apps/api).
 *
 * Document listing/detail bind to the endpoints already present in the frozen
 * OpenAPI contract (GET /v1/entities/{entityId}/documents). Section, span, and
 * fact listing endpoints are not part of the contract yet, so those methods
 * fail loudly instead of guessing at unpublished shapes; the UI stays on the
 * fixture source until the API lands and this class fills in behind the same
 * interface.
 */
export class HttpEvidenceSource implements EvidenceSource {
  constructor(
    private readonly baseUrl: string,
    private readonly entityId: string,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  private async getJson<T>(path: string): Promise<T> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`Evidence API request failed: ${response.status} ${path}`);
    }
    return (await response.json()) as T;
  }

  async listDocuments(): Promise<DocumentMeta[]> {
    return this.getJson<DocumentMeta[]>(`/v1/entities/${this.entityId}/documents`);
  }

  async getDocument(documentId: string): Promise<DocumentMeta | null> {
    try {
      return await this.getJson<DocumentMeta>(`/v1/documents/${documentId}`);
    } catch {
      return null;
    }
  }

  getSections(documentId: string): Promise<SectionRecord[]> {
    return Promise.reject(
      new Error(
        `Section listing for document ${documentId} is not in the ingestion API contract yet (lands with M1-INGESTION).`,
      ),
    );
  }

  getSpans(documentId: string): Promise<SourceSpanRecord[]> {
    return Promise.reject(
      new Error(
        `Span listing for document ${documentId} is not in the ingestion API contract yet (lands with M1-INGESTION).`,
      ),
    );
  }

  getFacts(entityId: string): Promise<FinancialFactRecord[]> {
    return Promise.reject(
      new Error(
        `Fact listing for entity ${entityId} is not in the ingestion API contract yet (lands with M1-INGESTION).`,
      ),
    );
  }
}

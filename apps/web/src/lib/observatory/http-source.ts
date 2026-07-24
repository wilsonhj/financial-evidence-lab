// Node built-in import is a compile-time server-only tripwire for bearer auth:
// a client-component import of this module fails the build instead of leaking
// the token into the browser bundle.
import "node:process";

import {
  ObservatoryApiError,
  ObservatoryContractError,
  observatoryFailureKind,
  parseErrorEnvelope,
  type ErrorEnvelope,
} from "./errors";
import type {
  CreateQuery,
  EvidenceFeedback,
  ObservatoryQuerySource,
  QueryAccepted,
  QuerySnapshot,
  RetrievalTrace,
} from "./query-source";
import type { RetrievalStreamOpener } from "./sse";
import { LANES } from "./trace-view";

export type BearerTokenProvider = string | (() => string | Promise<string>);

export interface HttpObservatorySourceOptions {
  baseUrl: string;
  workspaceId: string;
  token: BearerTokenProvider;
  fetchImpl?: typeof fetch;
}

function object(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ObservatoryContractError(`${path} must be an object`);
  }
  return value as Record<string, unknown>;
}

function string(value: unknown, path: string): string {
  if (typeof value !== "string") throw new ObservatoryContractError(`${path} must be a string`);
  return value;
}

function array(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) throw new ObservatoryContractError(`${path} must be an array`);
  return value;
}

function number(value: unknown, path: string): number {
  if (typeof value !== "number") throw new ObservatoryContractError(`${path} must be a number`);
  return value;
}

function validateQueryAccepted(value: unknown, path: string): QueryAccepted {
  const accepted = object(value, path);
  string(accepted.query_id, `${path}.query_id`);
  string(accepted.run_id, `${path}.run_id`);
  string(accepted.events_url, `${path}.events_url`);
  return value as QueryAccepted;
}

function validatePlan(value: unknown, path: string): void {
  const plan = object(value, path);
  if (plan.schema_version !== "query-plan/v1") {
    throw new ObservatoryContractError(`${path}.schema_version must be query-plan/v1`);
  }
  string(plan.intent, `${path}.intent`);
  string(plan.effective_as_of, `${path}.effective_as_of`);
  string(plan.corpus_version_id, `${path}.corpus_version_id`);
  string(plan.index_version_id, `${path}.index_version_id`);
  array(plan.lanes, `${path}.lanes`);
  array(plan.variants, `${path}.variants`);
  object(plan.filters, `${path}.filters`);
  object(plan.budgets, `${path}.budgets`);
}

function validateQuerySnapshot(value: unknown, path: string): QuerySnapshot {
  const snapshot = object(value, path);
  string(snapshot.query_id, `${path}.query_id`);
  string(snapshot.question, `${path}.question`);
  validatePlan(snapshot.plan, `${path}.plan`);
  for (const [index, raw] of array(snapshot.runs, `${path}.runs`).entries()) {
    const run = object(raw, `${path}.runs[${index}]`);
    string(run.run_id, `${path}.runs[${index}].run_id`);
    string(run.status, `${path}.runs[${index}].status`);
    string(run.mode, `${path}.runs[${index}].mode`);
    string(run.created_at, `${path}.runs[${index}].created_at`);
  }
  string(snapshot.created_at, `${path}.created_at`);
  return value as QuerySnapshot;
}

function validateTrace(value: unknown, path: string): RetrievalTrace {
  const trace = object(value, path);
  string(trace.run_id, `${path}.run_id`);
  string(trace.query_id, `${path}.query_id`);
  string(trace.status, `${path}.status`);
  validatePlan(trace.plan, `${path}.plan`);
  const lineage = object(trace.lineage, `${path}.lineage`);
  string(lineage.corpus_version_id, `${path}.lineage.corpus_version_id`);
  string(lineage.index_version_id, `${path}.lineage.index_version_id`);
  for (const [index, raw] of array(trace.events, `${path}.events`).entries()) {
    const event = object(raw, `${path}.events[${index}]`);
    number(event.seq, `${path}.events[${index}].seq`);
    string(event.type, `${path}.events[${index}].type`);
    string(event.occurred_at, `${path}.events[${index}].occurred_at`);
  }
  for (const [index, raw] of array(trace.candidates, `${path}.candidates`).entries()) {
    const candidate = object(raw, `${path}.candidates[${index}]`);
    string(candidate.item_id, `${path}.candidates[${index}].item_id`);
    string(candidate.source_span_id, `${path}.candidates[${index}].source_span_id`);
    string(candidate.document_version_id, `${path}.candidates[${index}].document_version_id`);
    string(candidate.published_at, `${path}.candidates[${index}].published_at`);
    string(candidate.fused_score, `${path}.candidates[${index}].fused_score`);
    if (typeof candidate.accepted !== "boolean") {
      throw new ObservatoryContractError(`${path}.candidates[${index}].accepted must be a boolean`);
    }
    const contributions = array(
      candidate.contributions,
      `${path}.candidates[${index}].contributions`,
    );
    for (const [cIndex, rawContribution] of contributions.entries()) {
      const cPath = `${path}.candidates[${index}].contributions[${cIndex}]`;
      const contribution = object(rawContribution, cPath);
      const lane = string(contribution.lane, `${cPath}.lane`);
      if (!(LANES as readonly string[]).includes(lane)) {
        throw new ObservatoryContractError(`${cPath}.lane must be a known retrieval lane`);
      }
      number(contribution.lane_rank, `${cPath}.lane_rank`);
    }
  }
  array(trace.decisions, `${path}.decisions`);
  for (const [index, raw] of array(trace.claims, `${path}.claims`).entries()) {
    const claim = object(raw, `${path}.claims[${index}]`);
    string(claim.id, `${path}.claims[${index}].id`);
    string(claim.text, `${path}.claims[${index}].text`);
    string(claim.status, `${path}.claims[${index}].status`);
    array(claim.citations, `${path}.claims[${index}].citations`);
  }
  const timings = object(trace.timings_ms, `${path}.timings_ms`);
  for (const [stage, ms] of Object.entries(timings)) {
    number(ms, `${path}.timings_ms.${stage}`);
  }
  const budget = object(trace.budget_usage, `${path}.budget_usage`);
  number(budget.context_items, `${path}.budget_usage.context_items`);
  number(budget.context_tokens, `${path}.budget_usage.context_tokens`);
  number(budget.input_tokens, `${path}.budget_usage.input_tokens`);
  number(budget.output_tokens, `${path}.budget_usage.output_tokens`);
  string(trace.cost_usd, `${path}.cost_usd`);
  string(trace.started_at, `${path}.started_at`);
  return value as RetrievalTrace;
}
export class HttpObservatorySource implements ObservatoryQuerySource {
  private readonly baseUrl: string;
  private readonly workspaceId: string;
  private readonly token: BearerTokenProvider;
  private readonly fetchImpl: typeof fetch;

  constructor(options: HttpObservatorySourceOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.workspaceId = options.workspaceId;
    this.token = options.token;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  private async bearer(path: string): Promise<string> {
    try {
      return typeof this.token === "function" ? await this.token() : this.token;
    } catch {
      throw new ObservatoryApiError(0, path, "authentication");
    }
  }

  private async request(path: string, init: RequestInit): Promise<Response> {
    const token = await this.bearer(path);
    try {
      return await this.fetchImpl(`${this.baseUrl}${path}`, {
        ...init,
        cache: "no-store",
        headers: {
          Accept: "application/json",
          ...(init.headers as Record<string, string> | undefined),
          Authorization: `Bearer ${token}`,
        },
      });
    } catch {
      throw new ObservatoryApiError(0, path, "unavailable");
    }
  }

  private async toApiError(response: Response, path: string): Promise<ObservatoryApiError> {
    let envelope: ErrorEnvelope | undefined;
    try {
      envelope = parseErrorEnvelope(await response.json());
    } catch {
      // Status classification is sufficient when the body is not JSON.
    }
    return new ObservatoryApiError(
      response.status,
      path,
      observatoryFailureKind(response.status),
      envelope,
    );
  }

  private async json(response: Response, path: string): Promise<unknown> {
    try {
      return await response.json();
    } catch {
      throw new ObservatoryContractError(`${path} returned invalid JSON`);
    }
  }

  async createQuery(input: CreateQuery, idempotencyKey: string): Promise<QueryAccepted> {
    const path = `/v1/workspaces/${encodeURIComponent(this.workspaceId)}/queries`;
    const response = await this.request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(input),
    });
    if (response.status !== 202) throw await this.toApiError(response, path);
    return validateQueryAccepted(await this.json(response, path), path);
  }

  async getQuery(queryId: string): Promise<QuerySnapshot> {
    const path = `/v1/queries/${encodeURIComponent(queryId)}`;
    const response = await this.request(path, { method: "GET" });
    if (!response.ok) throw await this.toApiError(response, path);
    return validateQuerySnapshot(await this.json(response, path), path);
  }

  async createRerun(queryId: string, idempotencyKey: string): Promise<QueryAccepted> {
    const path = `/v1/queries/${encodeURIComponent(queryId)}/reruns`;
    const response = await this.request(path, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
    });
    if (response.status !== 202) throw await this.toApiError(response, path);
    return validateQueryAccepted(await this.json(response, path), path);
  }

  async getRun(runId: string): Promise<RetrievalTrace> {
    const path = `/v1/retrieval-runs/${encodeURIComponent(runId)}`;
    const response = await this.request(path, { method: "GET" });
    if (!response.ok) throw await this.toApiError(response, path);
    return validateTrace(await this.json(response, path), path);
  }

  async submitFeedback(
    runId: string,
    feedback: EvidenceFeedback,
    idempotencyKey: string,
  ): Promise<void> {
    const path = `/v1/retrieval-runs/${encodeURIComponent(runId)}/feedback`;
    const response = await this.request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(feedback),
    });
    if (response.status !== 201) throw await this.toApiError(response, path);
  }

  openEventStream(runId: string): RetrievalStreamOpener {
    const path = `/v1/retrieval-runs/${encodeURIComponent(runId)}/events`;
    return async (lastEventId, signal) => {
      const token = await this.bearer(path);
      let response: Response;
      try {
        response = await this.fetchImpl(`${this.baseUrl}${path}`, {
          method: "GET",
          cache: "no-store",
          signal,
          headers: {
            Accept: "text/event-stream",
            Authorization: `Bearer ${token}`,
            ...(lastEventId !== null ? { "Last-Event-ID": String(lastEventId) } : {}),
          },
        });
      } catch {
        throw new ObservatoryApiError(0, path, "unavailable");
      }
      if (!response.ok || !response.body) {
        throw await this.toApiError(response, path);
      }
      return response.body;
    };
  }
}

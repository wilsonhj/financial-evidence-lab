import type { PageOptions } from "../data/evidence-source";
import { fixturePage } from "../data/pagination";
import { ObservatoryApiError, ObservatoryContractError } from "./errors";
import type {
  ObservatoryQuerySource,
  QueryAccepted,
  QueryPage,
  RetrievalEventPage,
  RetrievalTrace,
} from "./query-source";
import { serializeEventFrame, type RetrievalStreamOpener } from "./sse";
import {
  MOCK_ABSTAINED_RUN_ID,
  MOCK_ABSTAINED_TRACE,
  MOCK_EVENTS,
  MOCK_QUERY_ID,
  MOCK_QUERY_SNAPSHOT,
  MOCK_RERUN_ID,
  MOCK_RUN_ID,
  MOCK_TRACE,
} from "./fixtures/synthetic-trace";

const encoder = new TextEncoder();

/**
 * Deterministic in-memory Observatory source over the committed synthetic
 * trace. Backs fixture mode and every component/E2E test. Never reaches the
 * network and never reads a bearer token; selection is explicit in server.ts,
 * so fixture data can never leak into a configured HTTP deployment.
 */
export class MockObservatorySource implements ObservatoryQuerySource {
  private readonly events: readonly (typeof MOCK_EVENTS)[number][];
  private readonly heartbeatEvery: number;

  constructor(
    options: { events?: readonly (typeof MOCK_EVENTS)[number][]; heartbeatEvery?: number } = {},
  ) {
    this.events = options.events ?? MOCK_EVENTS;
    this.heartbeatEvery = options.heartbeatEvery ?? 0;
  }

  createQuery(): Promise<QueryAccepted> {
    return Promise.resolve({
      query_id: MOCK_QUERY_ID,
      run_id: MOCK_RUN_ID,
      events_url: `/observatory/api/runs/${MOCK_RUN_ID}/events`,
    });
  }

  getQuery(queryId: string, options: PageOptions = {}): Promise<QueryPage> {
    if (queryId !== MOCK_QUERY_ID) {
      return Promise.reject(new ObservatoryApiError(404, `/v1/queries/${queryId}`, "unavailable"));
    }
    const snapshot = structuredClone(MOCK_QUERY_SNAPSHOT);
    const runPage = fixturePage(
      snapshot.runs.sort(
        (a, b) => a.created_at.localeCompare(b.created_at) || a.run_id.localeCompare(b.run_id),
      ),
      options,
      `query:${queryId}`,
      ObservatoryContractError,
    );
    return Promise.resolve({ ...snapshot, runs: runPage.items, runPage });
  }

  async getEventHistory(runId: string, options: PageOptions = {}): Promise<RetrievalEventPage> {
    await this.getRun(runId);
    const page = fixturePage(
      [...this.events].sort((a, b) => a.seq - b.seq),
      options,
      `events:${runId}`,
      ObservatoryContractError,
    );
    return {
      run_id: runId,
      items: structuredClone(page.items),
      next_cursor: page.nextCursor,
      previous_cursor: page.previousCursor,
    };
  }

  createRerun(): Promise<QueryAccepted> {
    return Promise.resolve({
      query_id: MOCK_QUERY_ID,
      run_id: MOCK_RERUN_ID,
      events_url: `/observatory/api/runs/${MOCK_RERUN_ID}/events`,
    });
  }

  getRun(runId: string): Promise<RetrievalTrace> {
    if (runId === MOCK_ABSTAINED_RUN_ID) {
      return Promise.resolve(structuredClone(MOCK_ABSTAINED_TRACE));
    }
    if (runId !== MOCK_RUN_ID && runId !== MOCK_RERUN_ID) {
      return Promise.reject(
        new ObservatoryApiError(404, `/v1/retrieval-runs/${runId}`, "unavailable"),
      );
    }
    return Promise.resolve({ ...structuredClone(MOCK_TRACE), run_id: runId });
  }

  submitFeedback(): Promise<void> {
    return Promise.resolve();
  }

  openEventStream(): RetrievalStreamOpener {
    const events = this.events;
    const heartbeatEvery = this.heartbeatEvery;
    return (lastEventId) => {
      const pending = events.filter((event) => lastEventId === null || event.seq > lastEventId);
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          pending.forEach((event, index) => {
            if (heartbeatEvery > 0 && index > 0 && index % heartbeatEvery === 0) {
              controller.enqueue(encoder.encode(": heartbeat\n\n"));
            }
            controller.enqueue(encoder.encode(serializeEventFrame(event)));
          });
          controller.close();
        },
      });
      return Promise.resolve(stream);
    };
  }
}

export const mockObservatorySource = new MockObservatorySource();

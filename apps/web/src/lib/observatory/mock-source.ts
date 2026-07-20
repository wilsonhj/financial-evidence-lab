import { ObservatoryApiError } from "./errors";
import type {
  ObservatoryQuerySource,
  QueryAccepted,
  QuerySnapshot,
  RetrievalTrace,
} from "./query-source";
import { serializeEventFrame, type RetrievalStreamOpener } from "./sse";
import {
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

  getQuery(queryId: string): Promise<QuerySnapshot> {
    if (queryId !== MOCK_QUERY_ID) {
      return Promise.reject(new ObservatoryApiError(404, `/v1/queries/${queryId}`, "unavailable"));
    }
    return Promise.resolve(structuredClone(MOCK_QUERY_SNAPSHOT));
  }

  createRerun(): Promise<QueryAccepted> {
    return Promise.resolve({
      query_id: MOCK_QUERY_ID,
      run_id: MOCK_RERUN_ID,
      events_url: `/observatory/api/runs/${MOCK_RERUN_ID}/events`,
    });
  }

  getRun(runId: string): Promise<RetrievalTrace> {
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

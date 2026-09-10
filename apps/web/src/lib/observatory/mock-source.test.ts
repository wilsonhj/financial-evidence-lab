import { describe, expect, it } from "vitest";

import { MockObservatorySource } from "./mock-source";
import type { ObservatoryQuerySource } from "./query-source";
import { consumeRetrievalRun } from "./sse";
import { MOCK_EVENTS, MOCK_QUERY_ID, MOCK_RUN_ID } from "./fixtures/synthetic-trace";

describe("MockObservatorySource", () => {
  const source: ObservatoryQuerySource = new MockObservatorySource();

  it("returns the committed snapshot and trace", async () => {
    const snapshot = await source.getQuery(MOCK_QUERY_ID);
    expect(snapshot.query_id).toBe(MOCK_QUERY_ID);
    const trace = await source.getRun(MOCK_RUN_ID);
    expect(trace.run_id).toBe(MOCK_RUN_ID);
    expect(trace.candidates.length).toBeGreaterThan(0);
  });

  it("rejects unknown query and run ids as unavailable", async () => {
    await expect(source.getQuery("00000000-0000-4000-8000-000000000000")).rejects.toMatchObject({
      kind: "unavailable",
    });
    await expect(source.getRun("00000000-0000-4000-8000-000000000000")).rejects.toMatchObject({
      kind: "unavailable",
    });
  });

  it("streams the full scripted event log to completion", async () => {
    const open = source.openEventStream(MOCK_RUN_ID);
    const events = [];
    for await (const event of consumeRetrievalRun(open, { signal: new AbortController().signal })) {
      events.push(event);
    }
    expect(events.map((event) => event.seq)).toEqual(MOCK_EVENTS.map((event) => event.seq));
    expect(events.at(-1)?.type).toBe("run_completed");
  });

  it("replays only events after Last-Event-ID on resume", async () => {
    const open = source.openEventStream(MOCK_RUN_ID);
    const stream = await open(10, new AbortController().signal);
    const chunks: string[] = [];
    const reader = (stream as ReadableStream<Uint8Array>).getReader();
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      chunks.push(new TextDecoder().decode(value));
    }
    const text = chunks.join("");
    expect(text).not.toContain('"seq":10');
    expect(text).toContain('"seq":11');
    expect(text).toContain('"seq":13');
  });
});

it("keeps terminal evidence after more than 2,000 replayed events and bounded event pages", async () => {
  const events = Array.from({ length: 2201 }, (_, index) => ({
    ...MOCK_EVENTS[0]!,
    seq: index + 1,
    type: index === 2200 ? ("run_completed" as const) : ("run_started" as const),
  }));
  const source = new MockObservatorySource({ events, heartbeatEvery: 200 });
  const delivered = [];
  for await (const event of consumeRetrievalRun(source.openEventStream(), {
    signal: new AbortController().signal,
  }))
    delivered.push(event.seq);
  expect(delivered).toEqual(events.map((event) => event.seq));
  let page = await source.getEventHistory(MOCK_RUN_ID, { limit: 200 });
  const stored = [...page.items];
  while (page.next_cursor) {
    page = await source.getEventHistory(MOCK_RUN_ID, { cursor: page.next_cursor });
    expect(page.items.length).toBeLessThanOrEqual(200);
    stored.push(...page.items);
  }
  expect(stored.map((event) => event.seq)).toEqual(delivered);
  expect(stored.at(-1)?.type).toBe("run_completed");
});

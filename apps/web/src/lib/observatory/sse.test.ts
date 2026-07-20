import { describe, expect, it } from "vitest";

import { ObservatoryContractError } from "./errors";
import {
  consumeRetrievalRun,
  parseRetrievalEventStream,
  SeqDeduper,
  serializeEventFrame,
  type RetrievalEvent,
  type RetrievalStreamOpener,
} from "./sse";

function event(seq: number, type: RetrievalEvent["type"] = "candidate_batch"): RetrievalEvent {
  return {
    schema_version: "retrieval-event/v1",
    run_id: "ffffffff-0000-4000-8000-000000000001",
    seq,
    type,
    occurred_at: "2026-07-01T12:00:00Z",
    payload: {},
  };
}

const encoder = new TextEncoder();

function byteStream(text: string, chunkSize = text.length): ReadableStream<Uint8Array> {
  const bytes = encoder.encode(text);
  let offset = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (offset >= bytes.length) {
        controller.close();
        return;
      }
      controller.enqueue(bytes.slice(offset, offset + chunkSize));
      offset += chunkSize;
    },
  });
}

function frames(events: RetrievalEvent[]): string {
  return events.map(serializeEventFrame).join("");
}

async function collect<T>(gen: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const item of gen) out.push(item);
  return out;
}

describe("parseRetrievalEventStream", () => {
  it("parses events across arbitrary chunk boundaries", async () => {
    const text = frames([event(1), event(2), event(3)]);
    for (const chunkSize of [1, 3, 7, text.length]) {
      const parsed = await collect(parseRetrievalEventStream(byteStream(text, chunkSize)));
      const seqs = parsed.flatMap((frame) => (frame.kind === "event" ? [frame.event.seq] : []));
      expect(seqs).toEqual([1, 2, 3]);
    }
  });

  it("surfaces comment-only and typed heartbeats as heartbeat frames, not events", async () => {
    const text = `: keep-alive\n\n${serializeEventFrame(event(1))}${serializeEventFrame(event(2, "heartbeat"))}`;
    const parsed = await collect(parseRetrievalEventStream(byteStream(text, 5)));
    expect(parsed.map((frame) => frame.kind)).toEqual(["heartbeat", "event", "heartbeat"]);
  });

  it("rejects a data payload that is not a retrieval-event/v1 object", async () => {
    const bad = `data: ${JSON.stringify({ schema_version: "wrong", seq: 1 })}\n\n`;
    await expect(collect(parseRetrievalEventStream(byteStream(bad)))).rejects.toBeInstanceOf(
      ObservatoryContractError,
    );
  });
});

describe("SeqDeduper", () => {
  it("accepts strictly increasing seqs and rejects duplicates or older seqs", () => {
    const deduper = new SeqDeduper();
    expect(deduper.accept(event(1))).toBe(true);
    expect(deduper.accept(event(2))).toBe(true);
    // Duplicate of the highest seq: the load-bearing guard against re-render.
    expect(deduper.accept(event(2))).toBe(false);
    expect(deduper.accept(event(1))).toBe(false);
    expect(deduper.lastEventId).toBe(2);
    expect(deduper.accept(event(3))).toBe(true);
    expect(deduper.lastEventId).toBe(3);
  });
});

describe("consumeRetrievalRun", () => {
  it("yields every event once, stops on a terminal event, and never reconnects after it", async () => {
    const opens: (number | null)[] = [];
    const open: RetrievalStreamOpener = (lastEventId) => {
      opens.push(lastEventId);
      return Promise.resolve(byteStream(frames([event(1), event(2), event(3, "run_completed")])));
    };
    const controller = new AbortController();
    const events = await collect(consumeRetrievalRun(open, { signal: controller.signal }));
    expect(events.map((event) => event.seq)).toEqual([1, 2, 3]);
    expect(opens).toEqual([null]); // opened exactly once; no post-terminal reconnect
  });

  it("resumes after a mid-run disconnect with no missing or duplicate rendered events", async () => {
    const opens: (number | null)[] = [];
    const open: RetrievalStreamOpener = (lastEventId) => {
      opens.push(lastEventId);
      if (lastEventId === null) {
        // First connection drops after seq 2 without a terminal event.
        return Promise.resolve(byteStream(frames([event(1), event(2)])));
      }
      // Server resumes strictly after Last-Event-ID; a well-behaved server would
      // send [3, terminal], but re-sending seq 2 must still not double-render.
      return Promise.resolve(byteStream(frames([event(2), event(3), event(4, "run_completed")])));
    };
    const controller = new AbortController();
    const events = await collect(consumeRetrievalRun(open, { signal: controller.signal }));
    expect(events.map((event) => event.seq)).toEqual([1, 2, 3, 4]);
    expect(opens).toEqual([null, 2]); // reconnected with Last-Event-ID = highest seq seen
  });

  it("stops reconnecting once abort is signalled", async () => {
    const controller = new AbortController();
    let calls = 0;
    const open: RetrievalStreamOpener = () => {
      calls += 1;
      controller.abort();
      return Promise.resolve(byteStream(frames([event(calls)])));
    };
    const events = await collect(consumeRetrievalRun(open, { signal: controller.signal }));
    expect(events.length).toBeLessThanOrEqual(1);
    expect(calls).toBe(1);
  });

  it("bounds reconnect attempts when a stream repeatedly ends without progress", async () => {
    const opens: (number | null)[] = [];
    const open: RetrievalStreamOpener = (lastEventId) => {
      opens.push(lastEventId);
      return Promise.resolve(byteStream(": heartbeat\n\n")); // no events, never terminal
    };
    const controller = new AbortController();
    const events = await collect(
      consumeRetrievalRun(open, { signal: controller.signal, maxReconnects: 3 }),
    );
    expect(events).toEqual([]);
    expect(opens.length).toBe(4); // initial open + 3 bounded reconnects
  });
});

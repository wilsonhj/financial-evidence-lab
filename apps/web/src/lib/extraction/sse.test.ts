import { describe, expect, it, vi } from "vitest";
import { parseExtractionEvents, consumeExtractionEvents } from "./sse";
import type { Event } from "./contracts";
const run = "00000000-0000-4000-8000-000000000001";
const event = (id: number, type: Event["type"] = "review_waiting"): Event => ({
  schema_version: "extraction-event/v1",
  id,
  run_id: run,
  type,
  occurred_at: "2026-07-01T00:00:00Z",
  payload: { label: "étape" },
});
const frame = (e: Event) => `id: ${e.id}\r\ndata: ${JSON.stringify(e)}\r\n\r\n`;
function response(text: string, split = 1) {
  const bytes = new TextEncoder().encode(text);
  let offset = 0;
  return new Response(
    new ReadableStream<Uint8Array>({
      pull(c) {
        if (offset >= bytes.length) c.close();
        else {
          c.enqueue(bytes.slice(offset, offset + split));
          offset += split;
        }
      },
    }),
    { headers: { "content-type": "text/event-stream" } },
  );
}
async function read(r: Response, last = 0) {
  const found: Event[] = [];
  for await (const e of parseExtractionEvents(r, run, last)) found.push(e);
  return found;
}
describe("bounded extraction SSE", () => {
  it("preserves split UTF-8/CRLF frames and comments", async () => {
    expect(await read(response(": heartbeat\r\n\r\n" + frame(event(1))))).toEqual([event(1)]);
  });
  it("deduplicates replay without treating waiting_review as terminal", async () => {
    expect(
      (
        await read(
          response(frame(event(1)) + frame(event(2)) + frame(event(3, "review_completed")), 13),
          1,
        )
      ).map((e) => e.id),
    ).toEqual([2, 3]);
  });
  it.each([
    frame({ ...event(1), run_id: "00000000-0000-4000-8000-000000000002" }),
    frame(event(9007199254740992)),
    "id: 2\ndata: " + JSON.stringify(event(1)) + "\n\n",
    "data: broken\n\n",
    "data: " + "x".repeat(65536) + "\n\n",
  ])("rejects malformed/wrong-scope/oversized frames", async (text) => {
    await expect(read(response(text, 4096))).rejects.toThrow();
  });
  it("processes many small frames in a large network chunk", async () => {
    expect(
      await read(
        response(Array.from({ length: 600 }, (_, i) => frame(event(i + 1))).join(""), 1000000),
      ),
    ).toHaveLength(600);
  });
  it("reconnects from the last event and waits for human completion", async () => {
    const open = vi
      .fn()
      .mockResolvedValueOnce(response(frame(event(1))))
      .mockResolvedValueOnce(
        response(
          frame(event(1)) + frame(event(2, "review_completed")) + frame(event(3, "run_succeeded")),
        ),
      );
    const seen: number[] = [];
    await consumeExtractionEvents(run, {
      open,
      onEvent: (e) => seen.push(e.id),
      signal: new AbortController().signal,
      wait: async () => {},
    });
    expect(seen).toEqual([1, 2, 3]);
    expect(open.mock.calls[1]?.[0]).toBe(1);
  });
  it("delivers a bare-CR framed stream", async () => {
    const e = event(1);
    expect(await read(response(`id: ${e.id}\rdata: ${JSON.stringify(e)}\r\r`))).toEqual([e]);
  });
  it("delivers a final frame closed without its trailing blank line", async () => {
    expect(await read(response(`id: 1\r\ndata: ${JSON.stringify(event(1))}\r\n`))).toEqual([
      event(1),
    ]);
  });
  it("discards a frame truncated by a cut connection instead of failing", async () => {
    expect(await read(response(`id: 1\r\ndata: ${JSON.stringify(event(1)).slice(0, 20)}`))).toEqual(
      [],
    );
  });
  it("reconnects after a connection cut mid-frame", async () => {
    const open = vi
      .fn()
      .mockResolvedValueOnce(response(`id: 1\r\ndata: ${JSON.stringify(event(1)).slice(0, 20)}`))
      .mockResolvedValueOnce(response(frame(event(1, "run_succeeded"))));
    const seen: number[] = [];
    await consumeExtractionEvents(run, {
      open,
      onEvent: (e) => seen.push(e.id),
      signal: new AbortController().signal,
      wait: async () => {},
    });
    expect(seen).toEqual([1]);
  });
  it("does not spend the frame budget on keepalive comments", async () => {
    expect(await read(response(": ping\r\n".repeat(12000) + frame(event(1)), 4096))).toEqual([
      event(1),
    ]);
  });
  it("retries a transient upstream status instead of ending the view", async () => {
    const open = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 502 }))
      .mockResolvedValueOnce(response(frame(event(1, "run_succeeded"))));
    const seen: number[] = [];
    await consumeExtractionEvents(run, {
      open,
      onEvent: (e) => seen.push(e.id),
      signal: new AbortController().signal,
      wait: async () => {},
    });
    expect(seen).toEqual([1]);
    expect(open).toHaveBeenCalledTimes(2);
  });
  it("does not retry a refusal", async () => {
    const open = vi.fn().mockResolvedValue(new Response("", { status: 403 }));
    await expect(
      consumeExtractionEvents(run, {
        open,
        onEvent: () => {},
        signal: new AbortController().signal,
        wait: async () => {},
      }),
    ).rejects.toThrow("HTTP 403");
    expect(open).toHaveBeenCalledTimes(1);
  });
  it("keeps resuming a long review while each attempt delivers events", async () => {
    let id = 0;
    const open = vi.fn().mockImplementation(() => {
      id += 1;
      return Promise.resolve(
        response(frame(event(id, id > 8 ? "run_succeeded" : "review_waiting"))),
      );
    });
    const seen: number[] = [];
    await consumeExtractionEvents(run, {
      open,
      onEvent: (e) => seen.push(e.id),
      signal: new AbortController().signal,
      wait: async () => {},
    });
    expect(seen).toHaveLength(9);
  });
  it("bounds reconnect attempts and cancels on abort", async () => {
    const open = vi.fn().mockResolvedValue(response(""));
    await expect(
      consumeExtractionEvents(run, {
        open,
        onEvent: () => {},
        signal: new AbortController().signal,
        wait: async () => {},
      }),
    ).rejects.toThrow("Reconnect limit");
    expect(open).toHaveBeenCalledTimes(6);
    const controller = new AbortController();
    controller.abort();
    await consumeExtractionEvents(run, { open, onEvent: () => {}, signal: controller.signal });
    expect(open).toHaveBeenCalledTimes(6);
  });
});

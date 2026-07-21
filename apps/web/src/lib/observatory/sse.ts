import type { components } from "@fel/contracts";

import { ObservatoryContractError } from "./errors";

export type RetrievalEvent = components["schemas"]["RetrievalEvent"];
export type RetrievalEventType = RetrievalEvent["type"];

/**
 * Run-ending event types. Once one of these is rendered the stream is complete
 * and the client must NOT reconnect — reconnecting would re-request a finished
 * run and (absent dedupe) re-render its tail.
 */
export const TERMINAL_EVENT_TYPES: ReadonlySet<RetrievalEventType> = new Set([
  "run_completed",
  "run_abstained",
  "run_failed",
  "run_cancelled",
]);

export function isTerminalEvent(event: RetrievalEvent): boolean {
  return TERMINAL_EVENT_TYPES.has(event.type);
}

/** A parsed SSE frame: either a validated event or a heartbeat (comment or typed). */
export type RetrievalFrame =
  { kind: "event"; event: RetrievalEvent } | { kind: "heartbeat"; id?: number };

/**
 * Monotonic sequence gate. The contract streams events in ascending `seq` and
 * resumes with events strictly after Last-Event-ID, so a rendered event is new
 * iff its seq exceeds every seq accepted so far. This is the single guarantee
 * that reconnection produces no duplicate rendered events.
 */
export class SeqDeduper {
  private highest: number | null = null;

  constructor(initial: number | null = null) {
    this.highest = initial;
  }

  /** True when the event is newer than everything seen; records it as seen. */
  accept(event: RetrievalEvent): boolean {
    if (this.highest !== null && event.seq <= this.highest) return false;
    this.highest = event.seq;
    return true;
  }

  /** Last-Event-ID to send on the next (re)connection, or null before any event. */
  get lastEventId(): number | null {
    return this.highest;
  }
}

function assertRetrievalEvent(value: unknown): RetrievalEvent {
  if (typeof value !== "object" || value === null) {
    throw new ObservatoryContractError("SSE data payload is not an object");
  }
  const event = value as Record<string, unknown>;
  if (event.schema_version !== "retrieval-event/v1") {
    throw new ObservatoryContractError("SSE data payload is not retrieval-event/v1");
  }
  if (typeof event.run_id !== "string") {
    throw new ObservatoryContractError("SSE event.run_id must be a string");
  }
  if (!Number.isInteger(event.seq)) {
    throw new ObservatoryContractError("SSE event.seq must be an integer");
  }
  if (typeof event.type !== "string") {
    throw new ObservatoryContractError("SSE event.type must be a string");
  }
  if (typeof event.occurred_at !== "string") {
    throw new ObservatoryContractError("SSE event.occurred_at must be a string");
  }
  if (typeof event.payload !== "object" || event.payload === null) {
    throw new ObservatoryContractError("SSE event.payload must be an object");
  }
  return value as RetrievalEvent;
}

/** Splits one raw SSE event block into its `id:` and concatenated `data:` lines. */
function parseBlock(block: string): { id?: number; data?: string; comment: boolean } {
  const dataLines: string[] = [];
  let id: number | undefined;
  let sawComment = false;
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (line === "") continue;
    if (line.startsWith(":")) {
      sawComment = true;
      continue;
    }
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    // A leading space after the colon is stripped per the SSE spec.
    const rawValue = colon === -1 ? "" : line.slice(colon + 1);
    const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue;
    if (field === "data") dataLines.push(value);
    else if (field === "id") {
      const parsed = Number(value);
      if (Number.isInteger(parsed)) id = parsed;
    }
  }
  return {
    id,
    data: dataLines.length > 0 ? dataLines.join("\n") : undefined,
    comment: sawComment,
  };
}

async function* iterateBytes(
  source: AsyncIterable<Uint8Array> | ReadableStream<Uint8Array>,
): AsyncGenerator<Uint8Array> {
  if (Symbol.asyncIterator in source) {
    yield* source as AsyncIterable<Uint8Array>;
    return;
  }
  const reader = (source as ReadableStream<Uint8Array>).getReader();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      if (value) yield value;
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Parses a byte stream of `text/event-stream` into validated RetrievalFrames.
 * A blank line terminates an event block; a comment-only block (or a typed
 * `heartbeat` event) is surfaced as a heartbeat frame so callers can reset a
 * liveness timer without treating it as data.
 */
export async function* parseRetrievalEventStream(
  source: AsyncIterable<Uint8Array> | ReadableStream<Uint8Array>,
): AsyncGenerator<RetrievalFrame> {
  const decoder = new TextDecoder();
  let buffer = "";

  const flush = function* (block: string): Generator<RetrievalFrame> {
    // Whitespace-only separator run: nothing to emit.
    if (block.trim() === "") return;
    const { id, data, comment } = parseBlock(block);
    if (data === undefined) {
      if (comment) yield { kind: "heartbeat", ...(id !== undefined ? { id } : {}) };
      return;
    }
    let json: unknown;
    try {
      json = JSON.parse(data);
    } catch {
      throw new ObservatoryContractError("SSE data payload is not valid JSON");
    }
    const event = assertRetrievalEvent(json);
    if (event.type === "heartbeat") {
      yield { kind: "heartbeat", id: event.seq };
      return;
    }
    yield { kind: "event", event };
  };

  for await (const chunk of iterateBytes(source)) {
    buffer += decoder.decode(chunk, { stream: true });
    let boundary = findSseBlockBoundary(buffer);
    while (boundary !== null) {
      const block = buffer.slice(0, boundary.index);
      buffer = buffer.slice(boundary.index + boundary.length);
      yield* flush(block);
      boundary = findSseBlockBoundary(buffer);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim() !== "") yield* flush(buffer);
}

/**
 * Locate the next SSE event-block terminator. Spec blank lines are `\n\n`;
 * CRLF streams use `\r\n\r\n`; some peers emit bare `\r\r`. Prefer the earliest
 * match so mixed framing still splits mid-stream.
 */
function findSseBlockBoundary(buffer: string): { index: number; length: number } | null {
  let best: { index: number; length: number } | null = null;
  for (const [sep, length] of [
    ["\r\n\r\n", 4],
    ["\n\n", 2],
    ["\r\r", 2],
  ] as const) {
    const index = buffer.indexOf(sep);
    if (index !== -1 && (best === null || index < best.index)) {
      best = { index, length };
    }
  }
  return best;
}

/** Opens the upstream event stream resuming after `lastEventId` (null = from start). */
export type RetrievalStreamOpener = (
  lastEventId: number | null,
  signal: AbortSignal,
) => Promise<ReadableStream<Uint8Array> | AsyncIterable<Uint8Array>>;

export interface ConsumeOptions {
  signal: AbortSignal;
  /** Deduper to carry sequence state across reconnects; created fresh if omitted. */
  deduper?: SeqDeduper;
  /** Bound on consecutive reconnects after a stream ends without a terminal event. */
  maxReconnects?: number;
}

/**
 * Drives a retrieval run to completion across reconnects. Yields each event
 * exactly once in seq order. When a stream ends without a terminal event it
 * reopens with Last-Event-ID = the highest seq seen, so no event is missed and
 * none is re-rendered. Stops on a terminal event, on abort, or when reconnects
 * are exhausted.
 */
export async function* consumeRetrievalRun(
  open: RetrievalStreamOpener,
  { signal, deduper = new SeqDeduper(), maxReconnects = 10 }: ConsumeOptions,
): AsyncGenerator<RetrievalEvent> {
  let reconnects = 0;
  for (;;) {
    if (signal.aborted) return;
    const stream = await open(deduper.lastEventId, signal);
    let terminal = false;
    let progressed = false;
    for await (const frame of parseRetrievalEventStream(stream)) {
      if (signal.aborted) return;
      if (frame.kind === "heartbeat") continue;
      if (!deduper.accept(frame.event)) continue;
      progressed = true;
      yield frame.event;
      if (isTerminalEvent(frame.event)) {
        terminal = true;
        break;
      }
    }
    if (terminal || signal.aborted) return;
    reconnects = progressed ? 0 : reconnects + 1;
    if (reconnects > maxReconnects) return;
  }
}

/** Serializes an event as one SSE frame with `id: <seq>` for a same-origin proxy. */
export function serializeEventFrame(event: RetrievalEvent): string {
  return `id: ${event.seq}\ndata: ${JSON.stringify(event)}\n\n`;
}

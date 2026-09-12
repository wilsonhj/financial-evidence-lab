import { guards, uuid, type Event } from "./contracts";

/** A contract violation in the stream itself. Reconnecting cannot repair it. */
class InvalidStream extends Error {}
/** A transport failure that a later attempt may well succeed through. */
class StreamUnavailable extends Error {}
const FRAME_BYTES = 65536;
const terminal = new Set<Event["type"]>(["run_succeeded", "run_failed", "run_cancelled"]);
/** Incremental framing with a byte ceiling, including a frame split across arbitrary chunks. */
export async function* parseExtractionEvents(
  response: Response,
  runId: string,
  lastId = 0,
): AsyncGenerator<Event> {
  if (
    !uuid(runId) ||
    !response.ok ||
    !response.headers.get("content-type")?.startsWith("text/event-stream") ||
    !response.body
  )
    throw new InvalidStream("Invalid extraction stream");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const encoder = new TextEncoder();
  let pending = "",
    data: string[] = [],
    id: string | undefined,
    bytes = 0;
  const line = (value: string): Event | undefined => {
    // Comments and keepalives terminate no frame, so they must not spend the
    // frame budget: a healthy run held open by bare `:` pings would otherwise
    // be killed once those pings accumulate past the ceiling.
    if (value.startsWith(":")) return;
    bytes += encoder.encode(value).length + 1;
    if (bytes > FRAME_BYTES) throw new InvalidStream("Extraction frame exceeds 64 KiB");
    if (value === "") {
      const json = data.join("\n"),
        frameId = id;
      data = [];
      id = undefined;
      bytes = 0;
      if (!json) return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(json);
      } catch {
        throw new InvalidStream("Malformed extraction event");
      }
      if (!guards.event(parsed) || parsed.run_id !== runId || frameId !== String(parsed.id))
        throw new InvalidStream("Invalid extraction event identity");
      if (parsed.id <= lastId) return;
      lastId = parsed.id;
      return parsed;
    }
    const colon = value.indexOf(":"),
      field = colon < 0 ? value : value.slice(0, colon);
    const raw = colon < 0 ? "" : value.slice(colon + 1);
    const content = raw.startsWith(" ") ? raw.slice(1) : raw;
    if (field === "data") data.push(content);
    if (field === "id") {
      if (id !== undefined || !/^[1-9]\d*$/.test(content))
        throw new InvalidStream("Invalid event ID");
      id = content;
    }
  };
  /** SSE terminates a line with CRLF, a bare LF or a bare CR. */
  function* drain(final: boolean): Generator<Event> {
    for (;;) {
      const cr = pending.indexOf("\r"),
        lf = pending.indexOf("\n");
      let end: number, next: number;
      if (cr >= 0 && (lf < 0 || cr < lf)) {
        // A trailing CR may still be the first half of a CRLF pair.
        if (cr === pending.length - 1 && !final) return;
        end = cr;
        next = pending[cr + 1] === "\n" ? cr + 2 : cr + 1;
      } else if (lf >= 0) {
        end = lf;
        next = lf + 1;
      } else if (final && pending.length > 0) {
        end = next = pending.length;
      } else return;
      const event = line(pending.slice(0, end));
      pending = pending.slice(next);
      if (event) yield event;
    }
  }
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) {
        pending += decoder.decode();
        yield* drain(true);
        // A peer that closes right after the last frame without its trailing
        // blank line would otherwise drop that frame — including a terminal one.
        // A genuinely truncated frame is discarded instead, so a connection cut
        // mid-frame reconnects rather than failing the view outright.
        let tail: Event | undefined;
        try {
          tail = line("");
        } catch {
          tail = undefined;
        }
        if (tail) yield tail;
        return;
      }
      // A large network chunk may contain many legal small frames. Decode in
      // bounded pieces instead of retaining an arbitrary chunk as one string.
      for (let offset = 0; offset < chunk.value.length; offset += 4096) {
        pending += decoder.decode(chunk.value.subarray(offset, offset + 4096), { stream: true });
        yield* drain(false);
        if (bytes + encoder.encode(pending).length > FRAME_BYTES)
          throw new InvalidStream("Extraction frame exceeds 64 KiB");
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
const pause = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const done = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    signal.addEventListener("abort", done, { once: true });
  });
/** A blip, a restart or a proxy timeout is worth another attempt; a refusal is not. */
const retryable = (status: number) => status >= 500 || status === 408 || status === 429;
export async function consumeExtractionEvents(
  runId: string,
  options: {
    signal: AbortSignal;
    onEvent: (event: Event) => void;
    onStatus?: (status: "connected" | "reconnecting" | "complete") => void;
    lastId?: number;
    open?: (lastId: number, signal: AbortSignal) => Promise<Response>;
    wait?: typeof pause;
  },
): Promise<void> {
  if (!uuid(runId)) throw new InvalidStream("Invalid run ID");
  const open =
    options.open ??
    ((lastId, signal) =>
      fetch(`/api/extraction/runs/${runId}/events`, {
        signal,
        cache: "no-store",
        headers: lastId ? { "last-event-id": String(lastId) } : {},
      }));
  let lastId = options.lastId ?? 0;
  let attempts = 0;
  while (!options.signal.aborted) {
    let progressed = false;
    try {
      const response = await open(lastId, options.signal);
      if (!response.ok) {
        await response.body?.cancel();
        const reason = `Extraction stream unavailable (HTTP ${response.status})`;
        throw retryable(response.status)
          ? new StreamUnavailable(reason)
          : new InvalidStream(reason);
      }
      options.onStatus?.("connected");
      for await (const event of parseExtractionEvents(response, runId, lastId)) {
        if (options.signal.aborted) return;
        lastId = event.id;
        progressed = true;
        options.onEvent(event);
        if (terminal.has(event.type)) {
          options.onStatus?.("complete");
          return;
        }
      }
    } catch (error) {
      if (options.signal.aborted) return;
      if (error instanceof InvalidStream) throw error;
    }
    // A reconnect that delivered events is progress, not budget spent, so a
    // long human review does not exhaust the budget just by lasting.
    attempts = progressed ? 0 : attempts + 1;
    if (attempts > 5) throw new Error("Reconnect limit reached; reconnect explicitly");
    options.onStatus?.("reconnecting");
    await (options.wait ?? pause)(Math.min(250 * 2 ** (attempts - 1), 2000), options.signal);
  }
}

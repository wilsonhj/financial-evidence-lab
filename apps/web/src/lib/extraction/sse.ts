import { guards, uuid, type Event } from "./contracts";

class InvalidStream extends Error {}
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
    bytes += encoder.encode(value).length + 1;
    if (bytes > FRAME_BYTES) throw new InvalidStream("Extraction frame exceeds 64 KiB");
    const text = value.endsWith("\r") ? value.slice(0, -1) : value;
    if (text === "") {
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
    if (text.startsWith(":")) return;
    const colon = text.indexOf(":"),
      field = colon < 0 ? text : text.slice(0, colon);
    const raw = colon < 0 ? "" : text.slice(colon + 1);
    const content = raw.startsWith(" ") ? raw.slice(1) : raw;
    if (field === "data") data.push(content);
    if (field === "id") {
      if (id !== undefined || !/^[1-9]\d*$/.test(content))
        throw new InvalidStream("Invalid event ID");
      id = content;
    }
  };
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) {
        decoder.decode();
        return;
      }
      // A large network chunk may contain many legal small frames. Decode in
      // bounded pieces instead of retaining an arbitrary chunk as one string.
      for (let offset = 0; offset < chunk.value.length; offset += 4096) {
        pending += decoder.decode(chunk.value.subarray(offset, offset + 4096), { stream: true });
        let newline: number;
        while ((newline = pending.indexOf("\n")) >= 0) {
          const event = line(pending.slice(0, newline));
          pending = pending.slice(newline + 1);
          if (event) yield event;
        }
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
  for (let attempt = 0; attempt <= 5 && !options.signal.aborted; attempt++) {
    try {
      const response = await open(lastId, options.signal);
      if (!response.ok) {
        await response.body?.cancel();
        throw new InvalidStream(`Extraction stream unavailable (HTTP ${response.status})`);
      }
      options.onStatus?.("connected");
      for await (const event of parseExtractionEvents(response, runId, lastId)) {
        if (options.signal.aborted) return;
        lastId = event.id;
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
    if (attempt === 5) throw new Error("Reconnect limit reached; reconnect explicitly");
    options.onStatus?.("reconnecting");
    await (options.wait ?? pause)(Math.min(250 * 2 ** attempt, 2000), options.signal);
  }
}

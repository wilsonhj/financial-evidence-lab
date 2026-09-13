import type { FixtureState } from "./fixture";
/** Incremental synthetic session; the real worker/browser proof is a separate HTTP test. */
export function fixtureStream(
  state: FixtureState,
  runId: string,
  lastId: number,
  signal?: AbortSignal | null,
): Response {
  const encoder = new TextEncoder();
  let stopped = false,
    timer: ReturnType<typeof setInterval>,
    controller: ReadableStreamDefaultController<Uint8Array>;
  const cleanup = () => {
    stopped = true;
    clearInterval(timer);
    signal?.removeEventListener("abort", abort);
  };
  const abort = () => {
    if (!stopped) {
      cleanup();
      controller.close();
    }
  };
  const flush = () => {
    if (stopped || (controller.desiredSize ?? 0) <= 0) return;
    const event = state.events.find((e) => e.run_id === runId && e.id > lastId);
    if (!event) return;
    // enqueue can synchronously trigger pull; advance and stop before exposing
    // the terminal chunk so reentrant readers cannot deliver or close it twice.
    lastId = event.id;
    const terminal = ["run_succeeded", "run_failed", "run_cancelled"].includes(event.type);
    if (terminal) cleanup();
    controller.enqueue(encoder.encode(`id: ${event.id}\ndata: ${JSON.stringify(event)}\n\n`));
    if (terminal) controller.close();
  };
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
      timer = setInterval(flush, 50);
      signal?.addEventListener("abort", abort, { once: true });
      if (signal?.aborted) abort();
      else flush();
    },
    pull: flush,
    cancel: cleanup,
  });
  return new Response(stream, { headers: { "content-type": "text/event-stream" } });
}

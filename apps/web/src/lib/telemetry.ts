/**
 * Client-side telemetry channel (issue #138). `recordTiming`/`recordError`
 * queue small, allowlisted events and batch-flush them via
 * `navigator.sendBeacon` (falling back to `fetch` with `keepalive`) to the
 * same-origin `/api/telemetry` route, which does the real validation,
 * redaction, and structured logging — see `lib/telemetry-validation.ts` and
 * `app/api/telemetry/route.ts`. Nothing here decides what is safe to log; it
 * only decides what to *try* to send.
 *
 * Gated by `NEXT_PUBLIC_FEL_WEB_TELEMETRY=1`, inlined by Next.js at build
 * time. Unset (the default) in fixture mode and in the test suite, and the
 * vitest environment has no `window` in any case, so `isEnabled()` is false
 * and every call below is a no-op — no network activity, no timers. Every
 * exported function is a deliberate no-throw boundary: telemetry must never
 * surface as an app error.
 */

import type { TelemetryAttrs as ValidatedAttrs, TelemetryEventName } from "./telemetry-validation";

export type { TelemetryEventName } from "./telemetry-validation";
export type TelemetryAttrs = ValidatedAttrs;

interface TelemetryEvent {
  type: "timing" | "error";
  name: TelemetryEventName;
  ts: number;
  ms?: number;
  message?: string;
  attrs?: TelemetryAttrs;
}

const ENDPOINT = "/api/telemetry";
/** Mirrors telemetry-validation's MAX_EVENTS_PER_BATCH so a full queue never
 * gets truncated server-side; kept as a literal to avoid importing
 * server-only-flavoured validation constants into the client bundle. */
const MAX_BATCH_SIZE = 50;
const FLUSH_DELAY_MS = 2000;

let queue: TelemetryEvent[] = [];
let flushTimer: ReturnType<typeof setTimeout> | undefined;
let unloadListenersAttached = false;

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

function isEnabled(): boolean {
  return isBrowser() && process.env.NEXT_PUBLIC_FEL_WEB_TELEMETRY === "1";
}

function attachUnloadFlush(): void {
  if (unloadListenersAttached || typeof document === "undefined") return;
  unloadListenersAttached = true;
  try {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") flush();
    });
    window.addEventListener("pagehide", flush);
  } catch {
    // Best-effort: an environment without these APIs just keeps the timer flush.
  }
}

function send(events: TelemetryEvent[]): void {
  try {
    const payload = JSON.stringify({ events });
    if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
      const blob = new Blob([payload], { type: "application/json" });
      if (navigator.sendBeacon(ENDPOINT, blob)) return;
    }
    if (typeof fetch === "function") {
      void fetch(ENDPOINT, {
        method: "POST",
        body: payload,
        headers: { "Content-Type": "application/json" },
        keepalive: true,
      }).catch(() => {
        // Telemetry is best-effort and must never surface as an app error.
      });
    }
  } catch {
    // Never let a telemetry transport failure become a caller-visible error.
  }
}

/** Sends any queued events immediately. Exported for page-hide/tests. */
export function flush(): void {
  try {
    if (flushTimer !== undefined) {
      clearTimeout(flushTimer);
      flushTimer = undefined;
    }
    if (queue.length === 0) return;
    const batch = queue;
    queue = [];
    send(batch);
  } catch {
    // See `send`: telemetry must never throw into the caller.
  }
}

function enqueue(event: TelemetryEvent): void {
  try {
    if (!isEnabled()) return;
    attachUnloadFlush();
    queue.push(event);
    if (queue.length >= MAX_BATCH_SIZE) {
      flush();
      return;
    }
    flushTimer ??= setTimeout(flush, FLUSH_DELAY_MS);
  } catch {
    // Never let a scheduling failure become a caller-visible error.
  }
}

/** Records a timing measurement in milliseconds for an allowlisted event. */
export function recordTiming(name: TelemetryEventName, ms: number, attrs?: TelemetryAttrs): void {
  try {
    enqueue({ type: "timing", name, ts: Date.now(), ms, ...(attrs ? { attrs } : {}) });
  } catch {
    // No-throw boundary.
  }
}

/** Records a caught error for an allowlisted event. */
export function recordError(name: TelemetryEventName, err: unknown, attrs?: TelemetryAttrs): void {
  try {
    const message = err instanceof Error ? err.message : String(err);
    enqueue({ type: "error", name, ts: Date.now(), message, ...(attrs ? { attrs } : {}) });
  } catch {
    // No-throw boundary.
  }
}

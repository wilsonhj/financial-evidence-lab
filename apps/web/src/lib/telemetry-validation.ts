/**
 * Server-side validation and redaction for the web-layer telemetry channel
 * (issue #138). This is the trust boundary: `app/api/telemetry/route.ts`
 * accepts a batch of events from the browser (queued by `lib/telemetry.ts`)
 * and MUST run every event through `validateTelemetryBatch` before logging
 * anything. Nothing here trusts the shape, size, or content of client input,
 * and this module never logs or performs I/O itself — it only decides what
 * is safe to log.
 */

/** The only event names the route will accept and log. Anything else is dropped. */
export const TELEMETRY_EVENT_NAMES = [
  "reader.load",
  "reader.first_verified_span",
  "observatory.query.fetch",
  "observatory.trace.fetch",
  "observatory.fetch.error",
  "reader.fetch.error",
] as const;

export type TelemetryEventName = (typeof TELEMETRY_EVENT_NAMES)[number];

const ALLOWED_NAMES: ReadonlySet<string> = new Set(TELEMETRY_EVENT_NAMES);

/** The only attribute keys events may carry. Anything else fails the event. */
export const TELEMETRY_ATTR_KEYS = [
  "documentId",
  "runId",
  "queryId",
  "path",
  "status",
  "reason",
  "count",
] as const;

const ALLOWED_ATTR_KEYS: ReadonlySet<string> = new Set(TELEMETRY_ATTR_KEYS);

/** Bounds enforced on every batch/event; see each check below for why. */
export const MAX_EVENTS_PER_BATCH = 50;
export const MAX_STRING_LENGTH = 512;
/** 10 minutes: generous for a page-load or fetch timing, rejects garbage. */
export const MAX_TIMING_MS = 10 * 60 * 1000;

export type TelemetryAttrValue = string | number | boolean;
export type TelemetryAttrs = Record<string, TelemetryAttrValue>;

export interface ValidTelemetryEvent {
  type: "timing" | "error";
  name: TelemetryEventName;
  ts: number;
  ms?: number;
  message?: string;
  attrs?: TelemetryAttrs;
}

const EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
const BEARER_RE = /\bBearer\s+[A-Za-z0-9._~+/-]+=*/gi;
const API_KEY_RE = /\b(?:api[_-]?key|apikey|secret|token)\s*[:=]\s*\S+/gi;
// A UUID (8-4-4-4-12 hex) is a routine, non-secret identifier in this app
// (run ids, span ids, ...) and is deliberately exempted from redaction so
// telemetry stays useful; everything else that looks like a long opaque
// token (bearer tokens, API keys, JWT segments) is not.
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// 20+ consecutive base64url-ish characters: long enough that a human label
// would not naturally produce one, but a token, key, or JWT segment would.
const CANDIDATE_TOKEN_RE = /[A-Za-z0-9_-]{20,}/g;

/**
 * Strips anything that looks like a bearer token, API key, or email address
 * from free text. Used on every string field before it is ever logged. Errs
 * toward over-redacting (see UUID_RE note) rather than leaking.
 */
export function redact(text: string): string {
  return text
    .replace(BEARER_RE, "[redacted-token]")
    .replace(API_KEY_RE, "[redacted-token]")
    .replace(EMAIL_RE, "[redacted-email]")
    .replace(CANDIDATE_TOKEN_RE, (match) => (UUID_RE.test(match) ? match : "[redacted-token]"));
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function validateAttrs(raw: unknown): TelemetryAttrs | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const entries = Object.entries(raw as Record<string, unknown>);

  const result: TelemetryAttrs = {};
  for (const [key, value] of entries) {
    if (!ALLOWED_ATTR_KEYS.has(key)) return null;
    if (typeof value === "string") {
      if (value.length > MAX_STRING_LENGTH) return null;
      result[key] = redact(value);
    } else if (typeof value === "boolean") {
      result[key] = value;
    } else if (isFiniteNumber(value)) {
      result[key] = value;
    } else {
      return null;
    }
  }
  return result;
}

/** Validates and redacts a single event. Returns null to drop it. */
export function validateTelemetryEvent(raw: unknown): ValidTelemetryEvent | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;

  if (r.type !== "timing" && r.type !== "error") return null;
  if (typeof r.name !== "string" || !ALLOWED_NAMES.has(r.name)) return null;
  if (!isFiniteNumber(r.ts) || r.ts < 0) return null;

  const event: ValidTelemetryEvent = {
    type: r.type,
    name: r.name as TelemetryEventName,
    ts: r.ts,
  };

  if (r.type === "timing") {
    if (!isFiniteNumber(r.ms) || r.ms < 0 || r.ms > MAX_TIMING_MS) return null;
    event.ms = r.ms;
  } else if (r.ms !== undefined) {
    // Errors do not carry a duration; a malformed shape is rejected outright.
    return null;
  }

  if (r.message !== undefined) {
    if (typeof r.message !== "string" || r.message.length > MAX_STRING_LENGTH) return null;
    event.message = redact(r.message);
  }

  if (r.attrs !== undefined) {
    const attrs = validateAttrs(r.attrs);
    if (attrs === null) return null;
    event.attrs = attrs;
  }

  return event;
}

/**
 * Validates a whole request body. Returns null for a body so malformed the
 * request should be rejected outright (not an object, no `events` array, or
 * more events than the batch ceiling allows); otherwise returns the subset
 * of `events` that individually validated — a single malformed event never
 * takes the rest of a legitimate batch down with it.
 */
export function validateTelemetryBatch(body: unknown): ValidTelemetryEvent[] | null {
  if (typeof body !== "object" || body === null) return null;
  const events = (body as Record<string, unknown>).events;
  if (!Array.isArray(events)) return null;
  if (events.length === 0 || events.length > MAX_EVENTS_PER_BATCH) return null;

  const valid: ValidTelemetryEvent[] = [];
  for (const raw of events) {
    const event = validateTelemetryEvent(raw);
    if (event) valid.push(event);
  }
  return valid;
}

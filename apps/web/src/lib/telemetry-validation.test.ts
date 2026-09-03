import { describe, expect, it } from "vitest";

import {
  MAX_EVENTS_PER_BATCH,
  redact,
  validateTelemetryBatch,
  validateTelemetryEvent,
} from "./telemetry-validation";

function timingEvent(overrides: Record<string, unknown> = {}) {
  return {
    type: "timing",
    name: "reader.load",
    ts: 1000,
    ms: 42,
    ...overrides,
  };
}

describe("validateTelemetryEvent", () => {
  it("accepts a well-formed timing event", () => {
    const event = validateTelemetryEvent(timingEvent());
    expect(event).toEqual({ type: "timing", name: "reader.load", ts: 1000, ms: 42 });
  });

  it("accepts a well-formed error event with a message", () => {
    const event = validateTelemetryEvent({
      type: "error",
      name: "reader.fetch.error",
      ts: 5,
      message: "boom",
    });
    expect(event).toEqual({
      type: "error",
      name: "reader.fetch.error",
      ts: 5,
      message: "boom",
    });
  });

  it("rejects an event name not on the allowlist", () => {
    expect(validateTelemetryEvent(timingEvent({ name: "totally.unknown" }))).toBeNull();
  });

  it("rejects a type that is neither timing nor error", () => {
    expect(validateTelemetryEvent(timingEvent({ type: "debug" }))).toBeNull();
  });

  it("rejects a negative or non-finite ts", () => {
    expect(validateTelemetryEvent(timingEvent({ ts: -1 }))).toBeNull();
    expect(validateTelemetryEvent(timingEvent({ ts: Number.NaN }))).toBeNull();
  });

  it("rejects a negative ms", () => {
    expect(validateTelemetryEvent(timingEvent({ ms: -1 }))).toBeNull();
  });

  it("rejects an ms above the timing ceiling", () => {
    expect(validateTelemetryEvent(timingEvent({ ms: 10 * 60 * 1000 + 1 }))).toBeNull();
  });

  it("rejects a timing event missing ms", () => {
    const withoutMs: Record<string, unknown> = timingEvent();
    delete withoutMs.ms;
    expect(validateTelemetryEvent(withoutMs)).toBeNull();
  });

  it("rejects an error event carrying an ms field", () => {
    expect(
      validateTelemetryEvent({ type: "error", name: "reader.fetch.error", ts: 1, ms: 5 }),
    ).toBeNull();
  });

  it("rejects a message longer than the string bound", () => {
    expect(
      validateTelemetryEvent({
        type: "error",
        name: "reader.fetch.error",
        ts: 1,
        message: "x".repeat(513),
      }),
    ).toBeNull();
  });

  it("rejects a non-object payload", () => {
    expect(validateTelemetryEvent(null)).toBeNull();
    expect(validateTelemetryEvent("nope")).toBeNull();
    expect(validateTelemetryEvent([1, 2])).toBeNull();
  });

  describe("attrs", () => {
    it("accepts string, number, and boolean attrs on allowlisted keys", () => {
      const event = validateTelemetryEvent(
        timingEvent({ attrs: { documentId: "doc-1", count: 3, status: true } }),
      );
      expect(event?.attrs).toEqual({ documentId: "doc-1", count: 3, status: true });
    });

    it("rejects an attrs key not on the allowlist", () => {
      expect(validateTelemetryEvent(timingEvent({ attrs: { secretKey: "x" } }))).toBeNull();
    });

    it("rejects a non-string/number/boolean attr value", () => {
      expect(
        validateTelemetryEvent(timingEvent({ attrs: { documentId: { nested: true } } })),
      ).toBeNull();
      expect(validateTelemetryEvent(timingEvent({ attrs: { documentId: null } }))).toBeNull();
    });

    it("rejects an attrs string value over the length bound", () => {
      expect(
        validateTelemetryEvent(timingEvent({ attrs: { documentId: "x".repeat(513) } })),
      ).toBeNull();
    });

    it("rejects attrs that are not an object", () => {
      expect(validateTelemetryEvent(timingEvent({ attrs: "not-an-object" }))).toBeNull();
      expect(validateTelemetryEvent(timingEvent({ attrs: ["a"] }))).toBeNull();
    });

    it("redacts an email address inside an attr value", () => {
      const event = validateTelemetryEvent(
        timingEvent({ attrs: { reason: "contact person@example.com for help" } }),
      );
      expect(event?.attrs?.reason).toBe("contact [redacted-email] for help");
    });
  });
});

describe("redact", () => {
  it("redacts a bearer token", () => {
    expect(redact("Authorization: Bearer abc123.def456-ghi")).toBe(
      "Authorization: [redacted-token]",
    );
  });

  it("redacts an api-key style key=value pair", () => {
    expect(redact("failed with api_key=sk-abcdef1234567890")).toBe("failed with [redacted-token]");
  });

  it("redacts an email address", () => {
    expect(redact("send to jane.doe+test@example.co for review")).toBe(
      "send to [redacted-email] for review",
    );
  });

  it("redacts a long opaque token-like string", () => {
    expect(redact("session=aB3dEf9hJkLmNoPqRsTuVwXyZ0123")).toBe("session=[redacted-token]");
  });

  it("leaves a UUID untouched", () => {
    const uuid = "3fa85f64-5717-4562-b3fc-2c963f66afa6";
    expect(redact(`run ${uuid} completed`)).toBe(`run ${uuid} completed`);
  });

  it("leaves ordinary text untouched", () => {
    expect(redact("fetched 12 candidates in 340ms")).toBe("fetched 12 candidates in 340ms");
  });
});

describe("validateTelemetryBatch", () => {
  it("accepts a batch and validates each event", () => {
    const result = validateTelemetryBatch({ events: [timingEvent(), timingEvent({ ms: 7 })] });
    expect(result).toHaveLength(2);
  });

  it("drops an individually invalid event without failing the whole batch", () => {
    const result = validateTelemetryBatch({
      events: [timingEvent(), timingEvent({ name: "not.allowed" })],
    });
    expect(result).toHaveLength(1);
  });

  it("rejects a body without an events array", () => {
    expect(validateTelemetryBatch({})).toBeNull();
    expect(validateTelemetryBatch({ events: "nope" })).toBeNull();
  });

  it("rejects a non-object body", () => {
    expect(validateTelemetryBatch(null)).toBeNull();
    expect(validateTelemetryBatch("nope")).toBeNull();
  });

  it("rejects an empty batch", () => {
    expect(validateTelemetryBatch({ events: [] })).toBeNull();
  });

  it("rejects a batch over the size ceiling", () => {
    const events = Array.from({ length: MAX_EVENTS_PER_BATCH + 1 }, () => timingEvent());
    expect(validateTelemetryBatch({ events })).toBeNull();
  });

  it("accepts a batch exactly at the size ceiling", () => {
    const events = Array.from({ length: MAX_EVENTS_PER_BATCH }, () => timingEvent());
    expect(validateTelemetryBatch({ events })).toHaveLength(MAX_EVENTS_PER_BATCH);
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * vitest runs with `environment: "node"` (see the workspace vitest.config),
 * so there is no ambient `window`/`navigator`/`document` — exactly the
 * production posture this module relies on for its no-op fixture/test
 * behaviour. These tests stub just enough of the browser globals to exercise
 * the enabled path, and always restore them afterwards.
 */

const ORIGINAL_ENV = process.env.NEXT_PUBLIC_FEL_WEB_TELEMETRY;

function stubBrowser(sendBeaconImpl?: (url: string, data?: BodyInit | null) => boolean) {
  const listeners = new Map<string, () => void>();
  vi.stubGlobal("window", {
    addEventListener: (type: string, listener: () => void) => listeners.set(type, listener),
  });
  vi.stubGlobal("document", {
    addEventListener: () => {},
    visibilityState: "visible",
  });
  if (sendBeaconImpl) {
    vi.stubGlobal("navigator", { sendBeacon: vi.fn(sendBeaconImpl) });
  } else {
    vi.stubGlobal("navigator", {});
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  process.env.NEXT_PUBLIC_FEL_WEB_TELEMETRY = ORIGINAL_ENV;
});

describe("telemetry: disabled (no window, or env unset)", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_FEL_WEB_TELEMETRY = "1";
  });

  it("recordTiming is a no-op with no window in scope", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const { recordTiming, flush } = await import("./telemetry");
    expect(() => recordTiming("reader.load", 10)).not.toThrow();
    flush();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("recordError is a no-op with no window in scope", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const { recordError, flush } = await import("./telemetry");
    expect(() => recordError("reader.fetch.error", new Error("boom"))).not.toThrow();
    flush();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("is a no-op in the browser when the env flag is unset", async () => {
    process.env.NEXT_PUBLIC_FEL_WEB_TELEMETRY = undefined;
    const sendBeacon = vi.fn<(url: string, data?: BodyInit | null) => boolean>(() => true);
    stubBrowser(sendBeacon);
    const { recordTiming, flush } = await import("./telemetry");
    recordTiming("reader.load", 10);
    flush();
    expect(sendBeacon).not.toHaveBeenCalled();
  });
});

describe("telemetry: enabled in a browser-like environment", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_FEL_WEB_TELEMETRY = "1";
  });

  it("sends a batch via sendBeacon on flush", async () => {
    const sendBeacon = vi.fn<(url: string, data?: BodyInit | null) => boolean>(() => true);
    stubBrowser(sendBeacon);
    const { recordTiming, flush } = await import("./telemetry");

    recordTiming("reader.load", 123, { documentId: "doc-1" });
    flush();

    expect(sendBeacon).toHaveBeenCalledTimes(1);
    const [url, blob] = sendBeacon.mock.calls[0]!;
    expect(url).toBe("/api/telemetry");
    const text = await (blob as Blob).text();
    const body = JSON.parse(text) as { events: Array<Record<string, unknown>> };
    expect(body.events).toHaveLength(1);
    expect(body.events[0]).toMatchObject({
      type: "timing",
      name: "reader.load",
      ms: 123,
      attrs: { documentId: "doc-1" },
    });
  });

  it("falls back to fetch with keepalive when sendBeacon is unavailable", async () => {
    stubBrowser();
    const fetchSpy = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(
      async () => new Response(null, { status: 204 }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const { recordError, flush } = await import("./telemetry");

    recordError("reader.fetch.error", new Error("boom"));
    flush();

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0]!;
    expect(url).toBe("/api/telemetry");
    expect(init?.method).toBe("POST");
    expect(init?.keepalive).toBe(true);
    const body = JSON.parse(init?.body as string) as { events: Array<Record<string, unknown>> };
    expect(body.events[0]).toMatchObject({
      type: "error",
      name: "reader.fetch.error",
      message: "boom",
    });
  });

  it("falls back to fetch when sendBeacon reports failure", async () => {
    const sendBeacon = vi.fn<(url: string, data?: BodyInit | null) => boolean>(() => false);
    stubBrowser(sendBeacon);
    const fetchSpy = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(
      async () => new Response(null, { status: 204 }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const { recordTiming, flush } = await import("./telemetry");

    recordTiming("reader.load", 5);
    flush();

    expect(sendBeacon).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("batches multiple events into a single flush", async () => {
    const sendBeacon = vi.fn<(url: string, data?: BodyInit | null) => boolean>(() => true);
    stubBrowser(sendBeacon);
    const { recordTiming, recordError, flush } = await import("./telemetry");

    recordTiming("reader.load", 1);
    recordTiming("observatory.query.fetch", 2);
    recordError("observatory.fetch.error", new Error("x"));
    flush();

    expect(sendBeacon).toHaveBeenCalledTimes(1);
    const [, blob] = sendBeacon.mock.calls[0]!;
    const body = JSON.parse(await (blob as Blob).text()) as { events: unknown[] };
    expect(body.events).toHaveLength(3);
  });

  it("auto-flushes once the batch reaches the size ceiling", async () => {
    const sendBeacon = vi.fn<(url: string, data?: BodyInit | null) => boolean>(() => true);
    stubBrowser(sendBeacon);
    const { recordTiming } = await import("./telemetry");

    for (let i = 0; i < 50; i += 1) recordTiming("reader.load", i);

    expect(sendBeacon).toHaveBeenCalledTimes(1);
    const [, blob] = sendBeacon.mock.calls[0]!;
    const body = JSON.parse(await (blob as Blob).text()) as { events: unknown[] };
    expect(body.events).toHaveLength(50);
  });

  it("never throws even when sendBeacon itself throws", async () => {
    stubBrowser(() => {
      throw new Error("beacon exploded");
    });
    const { recordTiming, flush } = await import("./telemetry");
    expect(() => {
      recordTiming("reader.load", 1);
      flush();
    }).not.toThrow();
  });
});

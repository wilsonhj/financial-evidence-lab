import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

const ORIGINAL_ENV = process.env.FEL_WEB_TELEMETRY;

function postRequest(body: unknown): Request {
  return new Request("https://app.example.test/api/telemetry", {
    method: "POST",
    body: typeof body === "string" ? body : JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  process.env.FEL_WEB_TELEMETRY = ORIGINAL_ENV;
  vi.restoreAllMocks();
});

describe("POST /api/telemetry", () => {
  it("returns 404 when the feature flag is unset", async () => {
    delete process.env.FEL_WEB_TELEMETRY;
    const response = await POST(
      postRequest({ events: [{ type: "timing", name: "reader.load", ts: 1, ms: 2 }] }),
    );
    expect(response.status).toBe(404);
  });

  it("returns 404 when the feature flag is set to something other than 1", async () => {
    process.env.FEL_WEB_TELEMETRY = "true";
    const response = await POST(postRequest({ events: [] }));
    expect(response.status).toBe(404);
  });

  describe("with the feature flag enabled", () => {
    beforeEach(() => {
      process.env.FEL_WEB_TELEMETRY = "1";
    });

    it("returns 204 and logs one structured line per accepted event", async () => {
      const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
      const response = await POST(
        postRequest({
          events: [
            { type: "timing", name: "reader.load", ts: 1, ms: 42, attrs: { documentId: "doc-1" } },
          ],
        }),
      );

      expect(response.status).toBe(204);
      expect(logSpy).toHaveBeenCalledTimes(1);
      const logged = JSON.parse(logSpy.mock.calls[0]![0] as string);
      expect(logged).toEqual({
        level: "info",
        event: "web.telemetry",
        name: "reader.load",
        ms: 42,
        attrs: { documentId: "doc-1" },
      });
    });

    it("logs nothing but still returns 204 when every event fails validation", async () => {
      const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
      const response = await POST(
        postRequest({ events: [{ type: "timing", name: "not.allowed", ts: 1, ms: 1 }] }),
      );
      expect(response.status).toBe(204);
      expect(logSpy).not.toHaveBeenCalled();
    });

    it("returns 400 for a body that is not valid JSON", async () => {
      const response = await POST(postRequest("{not json"));
      expect(response.status).toBe(400);
    });

    it("returns 400 for a body missing an events array", async () => {
      const response = await POST(postRequest({ foo: "bar" }));
      expect(response.status).toBe(400);
    });

    it("returns 400 for an oversized batch", async () => {
      const events = Array.from({ length: 51 }, () => ({
        type: "timing",
        name: "reader.load",
        ts: 1,
        ms: 1,
      }));
      const response = await POST(postRequest({ events }));
      expect(response.status).toBe(400);
    });

    it("never echoes the raw body back on a 400", async () => {
      const response = await POST(postRequest("not-json-at-all"));
      const text = await response.text();
      expect(text).toBe("");
      expect(text).not.toContain("not-json-at-all");
    });
  });
});

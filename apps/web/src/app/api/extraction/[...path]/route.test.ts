import { afterEach, describe, expect, it, vi } from "vitest";
import { GET, POST, DELETE } from "./route";
import { GET as stream } from "../runs/[runId]/events/route";
import { FIXTURE_RUN } from "../../../../lib/extraction/fixture";
afterEach(() => vi.unstubAllEnvs());
describe("mounted extraction proxy", () => {
  it("binds explicit source and refuses missing configuration", async () => {
    vi.stubEnv("FEL_EVIDENCE_SOURCE", "fixture");
    expect(
      (
        await GET(new Request("http://web.test/api/extraction/permissions"), {
          params: Promise.resolve({ path: ["permissions"] }),
        })
      ).status,
    ).toBe(200);
    vi.stubEnv("FEL_EVIDENCE_SOURCE", "");
    for (const handler of [GET, POST, DELETE])
      expect(
        (
          await handler(new Request("http://web.test/api/extraction/permissions"), {
            params: Promise.resolve({ path: ["permissions"] }),
          })
        ).status,
      ).toBe(503);
    expect(
      (
        await stream(new Request("http://web.test/api/extraction/events"), {
          params: Promise.resolve({ runId: FIXTURE_RUN }),
        })
      ).status,
    ).toBe(503);
  });
  it("mounts an incremental stream and releases it on client cancellation", async () => {
    vi.stubEnv("FEL_EVIDENCE_SOURCE", "fixture");
    const response = await stream(
      new Request(`http://web.test/api/extraction/runs/${FIXTURE_RUN}/events`),
      { params: Promise.resolve({ runId: FIXTURE_RUN }) },
    );
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    const reader = response.body!.getReader();
    expect(new TextDecoder().decode((await reader.read()).value)).toContain("review_waiting");
    await reader.cancel();
  });
});

import { describe, expect, it, vi } from "vitest";
import { initialFixture, FIXTURE_WORKSPACE, fixtureId } from "./fixture";
import { requestExtraction } from "./transport";
const config = {
  mode: "http" as const,
  baseUrl: "https://api.example",
  token: "test-only",
  workspaceId: FIXTURE_WORKSPACE,
};
function read(path: string, data: unknown, query = "", headers = {}) {
  return requestExtraction(
    config,
    path,
    new Request(`https://web.example/api/extraction/${path}${query}`),
    vi.fn().mockResolvedValue(Response.json(data, { headers: { etag: '"1"', ...headers } })),
  );
}
const page = (items: unknown[]) => ({ items, next_cursor: null, previous_cursor: null, limit: 50 });
describe("extraction response identity", () => {
  it("accepts equivalent uppercase UUID resource spelling", async () => {
    const run = initialFixture().runs[0]!;
    expect((await read(`runs/${run.id.toUpperCase()}`, run)).status).toBe(200);
  });
  it("rejects a different record in immutable history", async () => {
    const version = initialFixture().versions[0]!;
    expect((await read(`approved/${fixtureId(99)}/versions`, page([version]))).status).toBe(502);
  });
  it("rejects undocumented run filters and mismatched proposal states", async () => {
    const proposal = initialFixture().proposals[0]!;
    expect((await read("proposals", page([proposal]), `?run_id=${fixtureId(99)}`)).status).toBe(
      422,
    );
    expect((await read("proposals", page([proposal]), "?state=accepted")).status).toBe(502);
  });
  it("rejects nonprogressing cursors and mismatched explicit page limits", async () => {
    const proposal = initialFixture().proposals[0]!;
    expect(
      (await read("proposals", { ...page([proposal]), next_cursor: "same" }, "?cursor=same"))
        .status,
    ).toBe(502);
    expect((await read("proposals", page([proposal]), "?limit=1")).status).toBe(502);
  });
  it("rejects duplicate immutable version IDs within one page", async () => {
    const version = initialFixture().versions[0]!;
    expect(
      (await read(`approved/${version.record_id}/versions`, page([version, version]))).status,
    ).toBe(502);
  });
  it("translates only a Location that identifies its returned resource", async () => {
    const run = initialFixture().runs[0]!;
    expect(
      (await read(`runs/${run.id}`, run, "", { location: `/v1/extraction-runs/${fixtureId(99)}` }))
        .status,
    ).toBe(502);
    expect(
      (await read(`runs/${run.id}`, run, "", { location: `/v1/approved-extractions/${run.id}` }))
        .status,
    ).toBe(502);
    const response = await read(`runs/${run.id}`, run, "", {
      location: `/v1/extraction-runs/${run.id}`,
    });
    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBe(`/api/extraction/runs/${run.id}`);
  });
  it("translates a correction's exact immutable-version Location and rejects another version", async () => {
    const version = initialFixture().versions[0]!;
    const location = `/v1/approved-extractions/${version.record_id}/versions/${version.version_id}`;
    const response = await read(`approved/${version.record_id}`, version, "", { location });
    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBe(
      `/api/extraction/approved/${version.record_id}/versions/${version.version_id}`,
    );
    expect(
      (
        await read(`approved/${version.record_id}`, version, "", {
          location: `/v1/approved-extractions/${version.record_id}/versions/${fixtureId(99)}`,
        })
      ).status,
    ).toBe(502);
    const run = initialFixture().runs[0]!;
    expect(
      (
        await read(`runs/${run.id}`, run, "", {
          location: `/v1/extraction-runs/${run.id}/versions/${version.version_id}`,
        })
      ).status,
    ).toBe(502);
  });
});

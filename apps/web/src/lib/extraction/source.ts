import "node:process";
import type { Guard } from "./contracts";
import { guards } from "./contracts";
import { initialFixture, fixtureFetch, FIXTURE_WORKSPACE, type FixtureState } from "./fixture";
import { loadConfig, requestExtraction, type Config } from "./transport";

export class ExtractionFailure extends Error {
  constructor(
    readonly status: number,
    readonly code = "UNAVAILABLE",
  ) {
    super(`Extraction service request failed (HTTP ${status}, ${code})`);
    this.name = "ExtractionFailure";
  }
}
// Fixture mode explicitly shares one synthetic session between server pages and
// same-origin routes. No production state or financial approvals live here.
const fixtureRuntime = globalThis as typeof globalThis & { felExtractionFixture?: FixtureState };
function sharedFixture() {
  return (fixtureRuntime.felExtractionFixture ??= initialFixture());
}
export function createSource(config: Config, fetcher: typeof fetch = fetch) {
  const serverConfig =
    config.mode === "fixture"
      ? {
          mode: "http" as const,
          baseUrl: "http://fixture.invalid",
          token: "synthetic-fixture-only",
          workspaceId: FIXTURE_WORKSPACE,
        }
      : config;
  const transport = config.mode === "fixture" ? fixtureFetch(sharedFixture()) : fetcher;
  const request = (path: string, incoming: Request) =>
    requestExtraction(serverConfig, path, incoming, transport);
  return {
    mode: config.mode,
    request,
    async read<T>(
      path: string,
      guard: Guard<T>,
      query = new URLSearchParams(),
    ): Promise<{ data: T; etag: string | null }> {
      const response = await request(
        path,
        new Request(
          `http://extraction.local/api/extraction/${path}${query.size ? `?${query}` : ""}`,
        ),
      );
      const data: unknown = await response.json();
      if (!response.ok)
        throw new ExtractionFailure(
          response.status,
          guards.error(data) ? data.error.code : "INVALID_RESPONSE",
        );
      if (!guard(data)) throw new ExtractionFailure(502, "INVALID_RESPONSE");
      return { data, etag: response.headers.get("etag") };
    },
  };
}
export function getExtractionSource() {
  return createSource(loadConfig());
}

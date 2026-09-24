import { afterEach, expect, it, vi } from "vitest";
import { getEvidenceSource } from "./data/server";
import { getObservatorySource } from "./observatory/server";
import { getExtractionSource } from "./extraction/source";
import { rerunAction, sendFeedbackAction, submitQueryAction } from "./observatory/actions";
vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(url);
  },
}));
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});
it.each([undefined, "public", "typo"])(
  "makes zero upstream calls from real factories/actions in mode %s",
  async (mode) => {
    const id = "11111111-1111-4111-8111-111111111111";
    const env = {
      FEL_DEPLOYMENT_MODE: mode,
      FEL_EVIDENCE_SOURCE: "http",
      FEL_API_BASE_URL: "https://api.example.test",
      FEL_API_BEARER_TOKEN: `mock.${Buffer.from(JSON.stringify({ org_id: id, sub: id, role: "owner" })).toString("base64url")}`,
      FEL_ENTITY_IDS: id,
      FEL_WORKSPACE_ID: id,
      FEL_AUTH_MODE: "mock",
      FEL_READER_SMOKE_TARGET: "test-reader",
    };
    for (const [key, value] of Object.entries(env)) vi.stubEnv(key, value);
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    for (const factory of [getEvidenceSource, getObservatorySource, getExtractionSource])
      expect(() => factory()).toThrow("PUBLIC_AUTH_NOT_READY");
    const form = new FormData();
    for (const [key, value] of Object.entries({
      question: "What was revenue?",
      lanes: "lexical",
      topK: "10",
      queryId: id,
      runId: id,
      itemId: id,
      label: "relevant",
    }))
      form.set(key, value);
    for (const action of [submitQueryAction, rerunAction, sendFeedbackAction])
      await expect(action(form)).rejects.toThrow("unavailable");
    expect(fetcher).not.toHaveBeenCalled();
  },
);

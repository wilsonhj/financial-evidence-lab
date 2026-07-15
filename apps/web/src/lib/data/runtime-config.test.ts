import { describe, expect, it } from "vitest";

import { EvidenceConfigurationError, loadEvidenceRuntimeConfig } from "./runtime-config";

const HTTP_ENV = {
  FEL_EVIDENCE_SOURCE: "http",
  FEL_API_BASE_URL: "https://api.example.test/",
  FEL_API_BEARER_TOKEN: "server-secret",
  FEL_ENTITY_IDS:
    "11111111-1111-4111-8111-111111111111, 22222222-2222-4222-8222-222222222222",
};

describe("loadEvidenceRuntimeConfig", () => {
  it("requires an explicit fixture or http mode", () => {
    expect(() => loadEvidenceRuntimeConfig({})).toThrow(EvidenceConfigurationError);
    expect(() => loadEvidenceRuntimeConfig({ FEL_EVIDENCE_SOURCE: "auto" })).toThrow(
      EvidenceConfigurationError,
    );
    expect(loadEvidenceRuntimeConfig({ FEL_EVIDENCE_SOURCE: "fixture" })).toEqual({
      mode: "fixture",
    });
  });

  it("fails closed when HTTP mode is missing server-only configuration", () => {
    for (const key of ["FEL_API_BASE_URL", "FEL_API_BEARER_TOKEN", "FEL_ENTITY_IDS"] as const) {
      const env = { ...HTTP_ENV };
      delete env[key];
      expect(() => loadEvidenceRuntimeConfig(env)).toThrow(EvidenceConfigurationError);
    }
  });

  it("normalizes HTTP configuration and optional scope", () => {
    expect(
      loadEvidenceRuntimeConfig({
        ...HTTP_ENV,
        FEL_AS_OF: "2026-07-01T00:00:00Z",
        FEL_CORPUS_VERSION_ID: "33333333-3333-4333-8333-333333333333",
      }),
    ).toEqual({
      mode: "http",
      baseUrl: "https://api.example.test",
      token: "server-secret",
      entityIds: [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
      ],
      asOf: "2026-07-01T00:00:00Z",
      corpusVersionId: "33333333-3333-4333-8333-333333333333",
    });
  });

  it("rejects unsafe URLs, naive cutoffs, and invalid UUID scope values", () => {
    expect(() =>
      loadEvidenceRuntimeConfig({ ...HTTP_ENV, FEL_API_BASE_URL: "file:///etc/passwd" }),
    ).toThrow(EvidenceConfigurationError);
    expect(() => loadEvidenceRuntimeConfig({ ...HTTP_ENV, FEL_AS_OF: "2026-07-01" })).toThrow(
      EvidenceConfigurationError,
    );
    expect(() =>
      loadEvidenceRuntimeConfig({ ...HTTP_ENV, FEL_CORPUS_VERSION_ID: "not-a-uuid" }),
    ).toThrow(EvidenceConfigurationError);
  });
});

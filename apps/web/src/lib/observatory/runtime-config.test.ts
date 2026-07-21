import { describe, expect, it } from "vitest";

import { EvidenceConfigurationError } from "../data/runtime-config";
import { loadObservatoryRuntimeConfig } from "./runtime-config";

const WORKSPACE = "dddddddd-0000-4000-8000-000000000001";

describe("loadObservatoryRuntimeConfig", () => {
  it("requires FEL_EVIDENCE_SOURCE to be set explicitly (fail closed)", () => {
    expect(() => loadObservatoryRuntimeConfig({})).toThrow(EvidenceConfigurationError);
    expect(() => loadObservatoryRuntimeConfig({ FEL_EVIDENCE_SOURCE: "auto" })).toThrow(
      EvidenceConfigurationError,
    );
  });

  it("selects mock mode for the fixture switch", () => {
    expect(loadObservatoryRuntimeConfig({ FEL_EVIDENCE_SOURCE: "fixture" })).toEqual({
      mode: "mock",
    });
  });

  it("builds an HTTP config from complete environment", () => {
    const config = loadObservatoryRuntimeConfig({
      FEL_EVIDENCE_SOURCE: "http",
      FEL_API_BASE_URL: "https://api.example.test/",
      FEL_API_BEARER_TOKEN: "token",
      FEL_WORKSPACE_ID: WORKSPACE,
    });
    expect(config).toEqual({
      mode: "http",
      baseUrl: "https://api.example.test",
      token: "token",
      workspaceId: WORKSPACE,
    });
  });

  it("rejects HTTP mode that is missing the token, base url, or workspace id", () => {
    const base = {
      FEL_EVIDENCE_SOURCE: "http",
      FEL_API_BASE_URL: "https://api.example.test",
      FEL_API_BEARER_TOKEN: "token",
      FEL_WORKSPACE_ID: WORKSPACE,
    };
    for (const key of ["FEL_API_BASE_URL", "FEL_API_BEARER_TOKEN", "FEL_WORKSPACE_ID"] as const) {
      expect(() => loadObservatoryRuntimeConfig({ ...base, [key]: "" })).toThrow(
        EvidenceConfigurationError,
      );
    }
  });

  it("rejects a non-UUID workspace id and a credentialed base url", () => {
    expect(() =>
      loadObservatoryRuntimeConfig({
        FEL_EVIDENCE_SOURCE: "http",
        FEL_API_BASE_URL: "https://api.example.test",
        FEL_API_BEARER_TOKEN: "token",
        FEL_WORKSPACE_ID: "not-a-uuid",
      }),
    ).toThrow(EvidenceConfigurationError);
    expect(() =>
      loadObservatoryRuntimeConfig({
        FEL_EVIDENCE_SOURCE: "http",
        FEL_API_BASE_URL: "https://user:pass@api.example.test",
        FEL_API_BEARER_TOKEN: "token",
        FEL_WORKSPACE_ID: WORKSPACE,
      }),
    ).toThrow(EvidenceConfigurationError);
  });
});

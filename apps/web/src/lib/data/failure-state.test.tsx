import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { EvidenceFailureState } from "../../components/EvidenceFailureState";
import { evidenceFailureState } from "./failure-state";
import { EvidenceApiError, EvidenceContractError } from "./http-source";
import { EvidenceConfigurationError } from "./runtime-config";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

describe("evidenceFailureState", () => {
  it("preserves typed auth, scope, conflict, and outage states", () => {
    for (const kind of [
      "authentication",
      "forbidden",
      "conflict",
      "invalid_scope",
      "unavailable",
    ] as const) {
      expect(evidenceFailureState(new EvidenceApiError(503, "/reader", kind))).toBe(kind);
    }
    expect(evidenceFailureState(new EvidenceConfigurationError("secret env name"))).toBe(
      "configuration",
    );
    expect(evidenceFailureState(new EvidenceContractError("upstream detail"))).toBe("integrity");
    expect(evidenceFailureState(new Error("unexpected"))).toBeNull();
  });

  it("renders public-safe copy without upstream messages or envelopes", () => {
    const markup = renderToStaticMarkup(<EvidenceFailureState kind="authentication" />);
    expect(markup).toContain("Sign in required");
    expect(markup).not.toContain("secret env name");
    expect(markup).not.toContain("upstream detail");
  });

  it("offers retry only for transient and integrity states", () => {
    expect(renderToStaticMarkup(<EvidenceFailureState kind="unavailable" />)).toContain(
      "Try again",
    );
    expect(renderToStaticMarkup(<EvidenceFailureState kind="authentication" />)).not.toContain(
      "Try again",
    );
  });
});

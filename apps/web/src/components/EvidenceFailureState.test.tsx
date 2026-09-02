import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import { EvidenceFailureState, type EvidenceFailureStateKind } from "./EvidenceFailureState";

const RETRYABLE: EvidenceFailureStateKind[] = ["conflict", "unavailable", "integrity"];
const NOT_RETRYABLE: EvidenceFailureStateKind[] = [
  "authentication",
  "forbidden",
  "invalid_scope",
  "configuration",
];

describe("EvidenceFailureState rendering", () => {
  it("renders every kind as an alert region with a heading and description", () => {
    for (const kind of [...RETRYABLE, ...NOT_RETRYABLE]) {
      const markup = renderToStaticMarkup(<EvidenceFailureState kind={kind} />);
      expect(markup).toContain('role="alert"');
      expect(markup).toContain('aria-labelledby="evidence-failure-heading"');
      expect(markup).toContain('id="evidence-failure-heading"');
    }
  });

  it("offers a retry control only for retryable failure kinds", () => {
    for (const kind of RETRYABLE) {
      const markup = renderToStaticMarkup(<EvidenceFailureState kind={kind} />);
      expect(markup).toContain("Try again");
    }
    for (const kind of NOT_RETRYABLE) {
      const markup = renderToStaticMarkup(<EvidenceFailureState kind={kind} />);
      expect(markup).not.toContain("Try again");
    }
  });

  it("never leaks raw API details: each kind's copy is a fixed, public-safe message", () => {
    const markup = renderToStaticMarkup(<EvidenceFailureState kind="authentication" />);
    expect(markup).toContain("Sign in required");
    expect(markup).not.toContain("undefined");
  });
});

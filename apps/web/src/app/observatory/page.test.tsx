import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/observatory/runtime-config", () => ({
  loadObservatoryRuntimeConfig: () => ({ mode: "mock" }),
}));

import ObservatoryPage from "./page";

describe("ObservatoryPage ?error= allowlist", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders allowlisted action-failure slugs in the alert", async () => {
    const element = await ObservatoryPage({
      searchParams: Promise.resolve({ error: "invalid_scope" }),
    });
    const markup = renderToStaticMarkup(element);
    expect(markup).toContain('role="alert"');
    expect(markup).toContain("invalid_scope");
  });

  it("does not render unknown or injected query strings", async () => {
    const element = await ObservatoryPage({
      searchParams: Promise.resolve({
        error: "<script>alert(1)</script>",
      }),
    });
    const markup = renderToStaticMarkup(element);
    expect(markup).not.toContain("alert(1)");
    expect(markup).not.toContain('role="alert"');
    expect(markup).not.toContain("Action failed:");
  });
});

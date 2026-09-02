import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { RetryEvidenceButton } from "./RetryEvidenceButton";

describe("RetryEvidenceButton rendering", () => {
  it('renders a named "Try again" button', () => {
    const markup = renderToStaticMarkup(<RetryEvidenceButton />);
    expect(markup).toContain("Try again");
    expect(markup).toContain('<button type="button"');
  });
});

describe("RetryEvidenceButton callback", () => {
  it("clicking retries by refreshing the router", () => {
    refresh.mockClear();
    const element = RetryEvidenceButton();
    element.props.onClick();
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});

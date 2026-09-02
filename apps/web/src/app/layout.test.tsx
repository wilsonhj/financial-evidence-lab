import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import RootLayout from "./layout";

describe("RootLayout skip link", () => {
  it("renders a 'Skip to main content' link as the first focusable element in the body", () => {
    const markup = renderToStaticMarkup(RootLayout({ children: <p>page content</p> }));
    const skipLinkIndex = markup.indexOf('class="skip-link"');
    const headerIndex = markup.indexOf('class="site-header"');
    expect(skipLinkIndex).toBeGreaterThan(-1);
    expect(headerIndex).toBeGreaterThan(-1);
    // The skip link precedes the repeated header/nav chrome it exists to
    // let a keyboard user bypass.
    expect(skipLinkIndex).toBeLessThan(headerIndex);
  });

  it("targets the main-content landmark", () => {
    const markup = renderToStaticMarkup(RootLayout({ children: <p>page content</p> }));
    expect(markup).toContain('href="#main-content"');
    expect(markup).toContain("Skip to main content");
  });

  it("is visually hidden until focused (not permanently visible chrome)", () => {
    const markup = renderToStaticMarkup(RootLayout({ children: <p>page content</p> }));
    // Hidden by default via the shared .skip-link rule, revealed on :focus —
    // asserted at the CSS layer below, not by inspecting inline styles here.
    expect(markup).toContain('class="skip-link"');
  });
});

describe("RootLayout skip-link stylesheet contract", async () => {
  const { readFileSync } = await import("node:fs");
  const css = readFileSync(new URL("./globals.css", import.meta.url), "utf8");

  it("hides the skip link by default and restores it on focus", () => {
    expect(css).toMatch(/\.skip-link\s*\{[^}]*clip:\s*rect\(0,\s*0,\s*0,\s*0\)/);
    expect(css).toMatch(/\.skip-link:focus\s*\{[^}]*clip:\s*auto/);
  });
});

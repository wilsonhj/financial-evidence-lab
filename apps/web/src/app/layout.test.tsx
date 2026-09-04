import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

// `RootLayout` is an async Server Component: it reads the persisted Desk theme
// out of a cookie before rendering. These tests invoke it directly rather than
// through Next's request pipeline, so they have to supply a cookie store and
// await the returned element. Passing the un-awaited promise to
// `renderToStaticMarkup` makes React report "a component suspended while
// responding to synchronous input", which is a test-harness artefact rather
// than anything wrong with the layout.
let storedTheme: string | undefined;

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      name === "fel-theme" && storedTheme !== undefined ? { value: storedTheme } : undefined,
  }),
}));

import RootLayout from "./layout";

const renderLayout = async () =>
  renderToStaticMarkup(await RootLayout({ children: <p>page content</p> }));

beforeEach(() => {
  storedTheme = undefined;
});

describe("RootLayout skip link", () => {
  it("renders a 'Skip to main content' link as the first focusable element in the body", async () => {
    const markup = await renderLayout();
    const skipLinkIndex = markup.indexOf('class="skip-link"');
    const headerIndex = markup.indexOf('class="site-header"');
    expect(skipLinkIndex).toBeGreaterThan(-1);
    expect(headerIndex).toBeGreaterThan(-1);
    // The skip link precedes the repeated header/nav chrome it exists to
    // let a keyboard user bypass.
    expect(skipLinkIndex).toBeLessThan(headerIndex);
  });

  it("targets the main-content landmark", async () => {
    const markup = await renderLayout();
    expect(markup).toContain('href="#main-content"');
    expect(markup).toContain("Skip to main content");
  });

  it("is visually hidden until focused (not permanently visible chrome)", async () => {
    const markup = await renderLayout();
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

// The skip-link tests above run with no cookie, so on their own they would
// still pass if theme resolution were broken. These pin the cookie-driven
// theme that trunk's async layout added in PR #176, so the mock cannot quietly
// become the only path exercised.
describe("RootLayout theme from cookie", () => {
  it("stamps the stored theme on the html element", async () => {
    // "oled" is a real DeskTheme; "dark" is not, which is what the
    // unknown-value case below covers.
    storedTheme = "oled";
    expect(await renderLayout()).toContain('data-fel-theme="oled"');
  });

  it("falls back to system when the cookie is absent", async () => {
    expect(await renderLayout()).toContain('data-fel-theme="system"');
  });

  it("falls back to system when the cookie holds an unknown value", async () => {
    storedTheme = "chartreuse";
    expect(await renderLayout()).toContain('data-fel-theme="system"');
  });
});

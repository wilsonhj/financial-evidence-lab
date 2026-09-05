/**
 * Measures the stylesheet instead of eyeballing it (#136).
 *
 * Two properties, both of which have already regressed in this repo at least
 * once, and neither of which a linter or typechecker can see:
 *
 * 1. An interactive element that sets `font: inherit` and never sets `color`
 *    falls back to the user-agent default (`buttontext` on a button,
 *    `fieldtext` on a form control). Those defaults are near-black and do not
 *    participate in the theme tokens, so they do not follow a dark ground.
 *    This is the absence of a declaration, so a sweep for hard-coded hex or
 *    `rgb()` literals cannot find it — the audit that produced the review
 *    branch's fixes missed all six live instances.
 *
 * 2. `--color-border-strong` marks the boundary of interactive controls and
 *    must clear WCAG 2.2 SC 1.4.11's 3:1 minimum against every ground it is
 *    painted on, in every theme. The review branch calibrated it against a
 *    #ffffff/#f6f7f9 ground that trunk no longer uses, which is exactly how a
 *    token silently stops meeting the ratio it was chosen for.
 */
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

// Comments are stripped before parsing. Without that, a declaration that
// follows a comment block is preceded by "/" rather than ";" and the anchor
// below never matches it — which is how the first version of this test
// reported `--color-border-strong` as "defined nowhere" while it sat six
// lines above. Stripping also stops prose inside a comment being read as a
// declaration.
const css = readFileSync(new URL("./globals.css", import.meta.url), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);

type Rule = { selector: string; body: string };

function rules(source: string): Rule[] {
  const found: Rule[] = [];
  const pattern = /([^{}]+)\{([^{}]*)\}/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(source)) !== null) {
    found.push({ selector: (match[1] ?? "").trim().replace(/\s+/g, " "), body: match[2] ?? "" });
  }
  return found;
}

function declaration(body: string, property: string): string | null {
  const match = new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*([^;]+)`).exec(body);
  const value = match?.[1];
  return value === undefined ? null : value.trim();
}

/** Relative luminance per WCAG 2.x. */
function luminance(hex: string): number {
  const value = hex.replace("#", "");
  const channels = [0, 2, 4].map((i) => parseInt(value.slice(i, i + 2), 16) / 255);
  const [r = 0, g = 0, b = 0] = channels.map((c) =>
    c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi = 0, lo = 0] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** The value of `token` in the block introduced by `selector`, or the :root value. */
function tokenIn(selector: string, token: string): string {
  const blocks = rules(css).filter((r) => r.selector.endsWith(selector));
  for (const block of blocks) {
    const value = declaration(block.body, token);
    if (value) return value;
  }
  const root = rules(css).find((r) => r.selector === ":root");
  const inherited = root ? declaration(root.body, token) : null;
  if (!inherited) throw new Error(`${token} is defined nowhere reachable from ${selector}`);
  return inherited;
}

describe("interactive controls never fall back to a user-agent colour", () => {
  it("every rule that sets `font: inherit` also sets a colour", () => {
    const offenders = rules(css)
      .filter((r) => /font\s*:\s*inherit/.test(r.body) && declaration(r.body, "color") === null)
      .map((r) => r.selector);
    expect(offenders).toEqual([]);
  });
});

describe("SC 1.4.11: interactive-control borders clear 3:1 in every theme", () => {
  // Each theme's own block, plus :root for the default light theme.
  const themes = [":root", 'html[data-fel-theme="oled"]'];

  for (const theme of themes) {
    for (const ground of ["--color-bg", "--color-surface"]) {
      it(`${theme} — border-strong against ${ground}`, () => {
        const border = tokenIn(theme, "--color-border-strong");
        const behind = tokenIn(theme, ground);
        expect(contrast(border, behind)).toBeGreaterThanOrEqual(3);
      });
    }
  }
});

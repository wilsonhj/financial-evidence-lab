import { readFileSync } from "node:fs";

import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { EvidenceFailureState } from "./EvidenceFailureState";
import { FeedbackControl } from "./FeedbackControl";
import { ObservatoryControls } from "./ObservatoryControls";
import { ObservatoryTrace } from "./ObservatoryTrace";
import { describeRunState } from "../lib/observatory/trace-view";
import {
  MOCK_ABSTAINED_TRACE,
  MOCK_QUERY_SNAPSHOT,
  MOCK_RUN_ID,
  MOCK_TRACE,
} from "../lib/observatory/fixtures/synthetic-trace";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const DOC_MAP = {};

describe("describeRunState (typed run states)", () => {
  it("distinguishes abstained, failed and cancelled and stays silent for succeeded", () => {
    expect(describeRunState("abstained")?.heading).toBe("Run abstained");
    expect(describeRunState("failed")?.heading).toBe("Run failed");
    expect(describeRunState("cancelled")?.heading).toBe("Run cancelled");
    expect(describeRunState("succeeded")).toBeNull();
    expect(describeRunState("retrieving")).toBeNull();
  });
});

describe("Observatory typed states are distinct", () => {
  it("renders abstention as its own alert, separate from contradiction and error", () => {
    const abstained = renderToStaticMarkup(
      <ObservatoryTrace trace={MOCK_ABSTAINED_TRACE} documentIdByVersionId={DOC_MAP} />,
    );
    expect(abstained).toContain("Run abstained");
    expect(abstained).toContain('role="alert"');

    // Contradiction is a claim-level outcome on a succeeded run — different text.
    const succeeded = renderToStaticMarkup(
      <ObservatoryTrace
        trace={MOCK_TRACE}
        snapshot={MOCK_QUERY_SNAPSHOT}
        documentIdByVersionId={DOC_MAP}
      />,
    );
    expect(succeeded).toContain("contradicted");
    expect(succeeded).not.toContain("Run abstained");

    // A transport/auth error is a different surface again.
    const error = renderToStaticMarkup(<EvidenceFailureState kind="authentication" />);
    expect(error).toContain("Sign in required");
    expect(error).not.toContain("Run abstained");
    expect(error).not.toContain("contradicted");
  });
});

describe("Observatory accessibility", () => {
  it("gives every data table a caption and row/column header scopes (table alternative)", () => {
    const markup = renderToStaticMarkup(
      <ObservatoryTrace
        trace={MOCK_TRACE}
        snapshot={MOCK_QUERY_SNAPSHOT}
        documentIdByVersionId={DOC_MAP}
      />,
    );
    expect(markup).toContain("<caption");
    expect(markup).toContain('scope="col"');
    expect(markup).toContain('scope="row"');
  });

  it("associates every control with a label and conveys status by text, not colour alone", () => {
    const controls = renderToStaticMarkup(<ObservatoryControls />);
    // Labels reference inputs by id.
    expect(controls).toContain('for="obs-question"');
    expect(controls).toContain('id="obs-question"');
    expect(controls).toContain("<legend>Lanes</legend>");

    const feedback = renderToStaticMarkup(
      <FeedbackControl runId={MOCK_RUN_ID} itemId="10101010-0000-4000-8000-000000000001" />,
    );
    expect(feedback).toContain("<label");

    // Status is spelled out, so it does not depend on badge colour.
    const trace = renderToStaticMarkup(
      <ObservatoryTrace trace={MOCK_TRACE} documentIdByVersionId={DOC_MAP} />,
    );
    expect(trace).toContain("supported");
    expect(trace).toContain("rejected");
  });

  it("ships a reduced-motion stylesheet rule", () => {
    const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
    expect(css).toContain("prefers-reduced-motion");
  });

  // WCAG 2.2 SC 1.4.11 (Non-text Contrast), audited in ACCESSIBILITY.md: the
  // plain --color-border grey is ~1.4:1 against white/surface, well under
  // the 3:1 floor for an interactive control's visual boundary. Form
  // controls (question/filter inputs, the lanes fieldset, the note
  // textarea) use the ~4.5:1 --color-border-strong token instead.
  it("gives interactive control borders a non-text contrast token, not the ~1.4:1 decorative border", () => {
    const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
    expect(css).toContain("--color-border-strong: #6b7789");
    expect(css).toMatch(
      /\.obs-controls input\[type="text"\][\s\S]*?border: 1px solid var\(--color-border-strong\)/,
    );
    expect(css).toMatch(
      /\.obs-controls fieldset \{[\s\S]*?border: 1px solid var\(--color-border-strong\)/,
    );
    expect(css).toMatch(
      /\.note-form textarea \{[\s\S]*?border: 1px solid var\(--color-border-strong\)/,
    );
  });

  // WCAG 2.2 SC 2.5.8 (Target Size, Minimum): standalone actionable controls
  // that are not inline text need a 24x24 CSS px hit area. The notes-list
  // "Remove" button and the unclassed feedback "Send" submit button used to
  // rely on horizontal-only padding / browser defaults that render under
  // 24px tall.
  it("floors non-inline interactive controls at a 24x24 CSS px target size", () => {
    const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
    expect(css).toMatch(/\.note-list button \{[\s\S]*?min-height: 24px/);
    expect(css).toMatch(/\.obs-feedback button \{[\s\S]*?min-height: 24px/);
  });
});

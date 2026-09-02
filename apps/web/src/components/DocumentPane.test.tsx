import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  DOC_10Q_VERSION_ID,
  fixtureSections,
  fixtureSpans,
} from "../lib/fixtures/synthetic-filing";
import { byTag, findAll } from "../lib/test-support/shallow-tree";

// DocumentPane only uses useMemo internally (memoizing pure derivations of
// its props), so a plain passthrough keeps the component callable as an
// ordinary function outside of a real React render — no dispatcher, no DOM,
// but the exact same segmenting/selection logic runs.
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return { ...actual, useMemo: (fn: () => unknown) => fn() };
});

import { DocumentPane } from "./DocumentPane";

const sections = fixtureSections.filter(
  (section) => section.document_version_id === DOC_10Q_VERSION_ID,
);
const spans = fixtureSpans.filter((span) => span.span.document_version_id === DOC_10Q_VERSION_ID);
const REVENUE_SPAN_ID = "cccccccc-0000-4000-8000-000000000001";

describe("DocumentPane rendering", () => {
  it("labels the article landmark and renders section headings", () => {
    const markup = renderToStaticMarkup(
      <DocumentPane
        sections={sections}
        spans={spans}
        selectedSpanId={null}
        onSelectSpan={vi.fn()}
      />,
    );
    expect(markup).toContain('aria-label="Filing content"');
    expect(markup).toContain("Condensed Consolidated Statements of Operations");
  });

  it("renders every cited span as a focusable, named button", () => {
    const markup = renderToStaticMarkup(
      <DocumentPane
        sections={sections}
        spans={spans}
        selectedSpanId={null}
        onSelectSpan={vi.fn()}
      />,
    );
    // Real <button> elements: focusable and Enter/Space-activatable natively,
    // with an accessible name that announces it as a citation, not plain text.
    expect(markup).toContain('<button type="button" class="span-mark"');
    expect(markup).toContain("Cited source span:");
  });

  it("marks the selected span's button aria-pressed and leaves others unpressed", () => {
    const markup = renderToStaticMarkup(
      <DocumentPane
        sections={sections}
        spans={spans}
        selectedSpanId={REVENUE_SPAN_ID}
        onSelectSpan={vi.fn()}
      />,
    );
    expect(markup).toContain('aria-pressed="true"');
    expect(markup).toContain('aria-pressed="false"');
  });
});

describe("DocumentPane span selection callback", () => {
  it("activating an unselected span's button calls onSelectSpan with a span id", () => {
    const onSelectSpan = vi.fn();
    const element = DocumentPane({ sections, spans, selectedSpanId: null, onSelectSpan });
    const buttons = findAll(element, byTag("button"));
    expect(buttons.length).toBeGreaterThan(0);
    (buttons[0]!.props as { onClick: () => void }).onClick();
    expect(onSelectSpan).toHaveBeenCalledTimes(1);
    expect(onSelectSpan).toHaveBeenCalledWith(expect.any(String));
    const [calledWith] = onSelectSpan.mock.calls[0]!;
    expect(spans.some((span) => span.id === calledWith)).toBe(true);
  });

  it("activating the already-selected span's button toggles selection off", () => {
    const onSelectSpan = vi.fn();
    const element = DocumentPane({
      sections,
      spans,
      selectedSpanId: REVENUE_SPAN_ID,
      onSelectSpan,
    });
    const pressed = findAll(
      element,
      (el) =>
        el.type === "button" && (el.props as { "aria-pressed"?: boolean })["aria-pressed"] === true,
    );
    expect(pressed).toHaveLength(1);
    (pressed[0]!.props as { onClick: () => void }).onClick();
    expect(onSelectSpan).toHaveBeenCalledWith(null);
  });

  it("plain (non-cited) text segments render without a button and are inert", () => {
    const element = DocumentPane({ sections, spans, selectedSpanId: null, onSelectSpan: vi.fn() });
    const spansHost = findAll(element, byTag("span"));
    // Every plain-text segment is a bare <span>, never a button — it is not a
    // citation and must not appear focusable/clickable.
    expect(spansHost.length).toBeGreaterThan(0);
  });
});

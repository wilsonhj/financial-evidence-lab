import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MOCK_TRACE } from "../lib/observatory/fixtures/synthetic-trace";
import { EventReplay } from "./EventReplay";

describe("EventReplay rendering", () => {
  it("names the replay region and renders every event in ascending seq order", () => {
    const markup = renderToStaticMarkup(<EventReplay trace={MOCK_TRACE} />);
    expect(markup).toContain('aria-labelledby="obs-replay-heading"');
    expect(markup).toContain("Stored replay");
    const seqPositions = [...markup.matchAll(/#(\d+)/g)].map((match) => Number(match[1]));
    expect(seqPositions.length).toBeGreaterThan(1);
    expect(seqPositions).toEqual([...seqPositions].sort((a, b) => a - b));
  });

  it("shows the empty state when a trace has no persisted events", () => {
    const markup = renderToStaticMarkup(<EventReplay trace={{ ...MOCK_TRACE, events: [] }} />);
    expect(markup).toContain("No persisted events for this run.");
  });
});

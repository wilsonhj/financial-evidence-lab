import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { sendFeedbackAction } from "../lib/observatory/actions";
import { MOCK_RUN_ID } from "../lib/observatory/fixtures/synthetic-trace";
import { FeedbackControl } from "./FeedbackControl";

const ITEM_ID = "10101010-0000-4000-8000-000000000001";

describe("FeedbackControl rendering", () => {
  it("submits to the feedback server action and carries the run and item ids as hidden fields", () => {
    const markup = renderToStaticMarkup(<FeedbackControl runId={MOCK_RUN_ID} itemId={ITEM_ID} />);
    expect(markup).toContain(`value="${MOCK_RUN_ID}"`);
    expect(markup).toContain(`value="${ITEM_ID}"`);
    expect(markup).toContain('name="runId"');
    expect(markup).toContain('name="itemId"');
  });

  it("labels the label and reason controls, including for assistive tech only", () => {
    const markup = renderToStaticMarkup(<FeedbackControl runId={MOCK_RUN_ID} itemId={ITEM_ID} />);
    expect(markup).toContain(`for="feedback-${ITEM_ID}"`);
    expect(markup).toContain(`id="feedback-${ITEM_ID}"`);
    expect(markup).toContain(`for="reason-${ITEM_ID}"`);
    expect(markup).toContain("visually-hidden");
  });

  it("offers exactly the four contract feedback labels", () => {
    const markup = renderToStaticMarkup(<FeedbackControl runId={MOCK_RUN_ID} itemId={ITEM_ID} />);
    for (const label of ["relevant", "irrelevant", "duplicate", "temporally_invalid"]) {
      expect(markup).toContain(`value="${label}"`);
    }
  });

  it("is wired to the shared feedback server action", () => {
    const element = FeedbackControl({ runId: MOCK_RUN_ID, itemId: ITEM_ID });
    expect(element.props.action).toBe(sendFeedbackAction);
  });
});

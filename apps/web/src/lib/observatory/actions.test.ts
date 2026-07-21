import { describe, expect, it, vi, beforeEach } from "vitest";

import type { EvidenceFeedback, QueryAccepted } from "./query-source";

/**
 * redirect() throws in Next.js to unwind the action; the mock keeps that shape
 * so the actions stop at the same point they do in production. Tests await the
 * action and inspect the Idempotency-Key captured by the fake source below.
 */
vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  },
}));

const createQuery = vi.fn<(input: unknown, key: string) => Promise<QueryAccepted>>();
const createRerun = vi.fn<(queryId: string, key: string) => Promise<QueryAccepted>>();
const submitFeedback =
  vi.fn<(runId: string, feedback: EvidenceFeedback, key: string) => Promise<void>>();

vi.mock("./server", () => ({
  getObservatorySource: () => ({ createQuery, createRerun, submitFeedback }),
}));

import { rerunAction, sendFeedbackAction, submitQueryAction } from "./actions";

/** Swallow the redirect the action throws on its success path. */
async function run(action: () => Promise<void>): Promise<void> {
  await expect(action()).rejects.toThrow(/NEXT_REDIRECT/);
}

function feedbackForm(fields: Record<string, string>): FormData {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) form.set(key, value);
  return form;
}

beforeEach(() => {
  createQuery.mockReset().mockResolvedValue({ query_id: "q", run_id: "r" } as QueryAccepted);
  createRerun.mockReset().mockResolvedValue({ query_id: "q", run_id: "r" } as QueryAccepted);
  submitFeedback.mockReset().mockResolvedValue();
});

describe("per-endpoint Idempotency-Key derivation", () => {
  it("dedupes feedback: same (run_id, item_id, label) yields the same key", async () => {
    const form = feedbackForm({ runId: "run-1", itemId: "item-1", label: "relevant" });
    await run(() => sendFeedbackAction(form));
    await run(() => sendFeedbackAction(form));

    const [firstKey, secondKey] = submitFeedback.mock.calls.map((call) => call[2]);
    expect(firstKey).toBe(secondKey);
  });

  it("distinguishes feedback when the label or item differs", async () => {
    await run(() =>
      sendFeedbackAction(feedbackForm({ runId: "r", itemId: "i", label: "relevant" })),
    );
    await run(() =>
      sendFeedbackAction(feedbackForm({ runId: "r", itemId: "i", label: "irrelevant" })),
    );
    await run(() =>
      sendFeedbackAction(feedbackForm({ runId: "r", itemId: "other", label: "relevant" })),
    );

    const keys = submitFeedback.mock.calls.map((call) => call[2]);
    expect(new Set(keys).size).toBe(3);
  });

  it("mints a fresh key for each createQuery call", async () => {
    const form = feedbackForm({ question: "What changed?" });
    await run(() => submitQueryAction(form));
    await run(() => submitQueryAction(form));

    const [firstKey, secondKey] = createQuery.mock.calls.map((call) => call[1]);
    expect(firstKey).not.toBe(secondKey);
  });

  it("mints a fresh key for each createRerun call", async () => {
    const form = feedbackForm({ queryId: "query-1" });
    await run(() => rerunAction(form));
    await run(() => rerunAction(form));

    const [firstKey, secondKey] = createRerun.mock.calls.map((call) => call[1]);
    expect(firstKey).not.toBe(secondKey);
  });
});

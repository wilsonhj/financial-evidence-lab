import { describe, expect, it, vi, beforeEach } from "vitest";

import { ObservatoryApiError, ObservatoryContractError } from "./errors";
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

/** Capture the redirect URL the action throws. */
async function redirectUrl(action: () => Promise<void>): Promise<string> {
  try {
    await action();
    throw new Error("expected redirect");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const match = /^NEXT_REDIRECT:(.+)$/.exec(message);
    if (!match) throw error;
    return match[1]!;
  }
}

/** Swallow the redirect the action throws on its success path. */
async function run(action: () => Promise<void>): Promise<void> {
  await expect(action()).rejects.toThrow(/NEXT_REDIRECT/);
}

function feedbackForm(fields: Record<string, string>): FormData {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) form.set(key, value);
  return form;
}

const PARENT_UUID = "aaaaaaaa-0000-4000-8000-000000000001";

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

describe("action field bounds and failure redirects", () => {
  it("redirects validation failure to /observatory?error=invalid_scope", async () => {
    const url = await redirectUrl(() =>
      submitQueryAction(feedbackForm({ question: "", topK: "999" })),
    );
    expect(url).toBe("/observatory?error=invalid_scope");
    expect(createQuery).not.toHaveBeenCalled();
  });

  it("UUID-validates parentQueryId and rejects a non-UUID before the API call", async () => {
    const url = await redirectUrl(() =>
      submitQueryAction(
        feedbackForm({ question: "What changed?", parentQueryId: "not-a-uuid" }),
      ),
    );
    expect(url).toBe("/observatory?error=invalid_scope");
    expect(createQuery).not.toHaveBeenCalled();
  });

  it("threads a UUID parentQueryId onto the createQuery request", async () => {
    await run(() =>
      submitQueryAction(
        feedbackForm({ question: "What changed?", parentQueryId: PARENT_UUID }),
      ),
    );
    expect(createQuery.mock.calls[0]![0]).toMatchObject({ parent_query_id: PARENT_UUID });
  });

  it("rejects empty queryId before createRerun", async () => {
    const url = await redirectUrl(() =>
      rerunAction(feedbackForm({ queryId: "", runId: "run-1" })),
    );
    expect(url).toBe("/observatory/runs/run-1?error=invalid_scope");
    expect(createRerun).not.toHaveBeenCalled();
  });

  it("rejects empty itemId and overlong reason before submitFeedback", async () => {
    const emptyItem = await redirectUrl(() =>
      sendFeedbackAction(feedbackForm({ runId: "run-1", itemId: "", label: "relevant" })),
    );
    expect(emptyItem).toBe("/observatory/runs/run-1?error=invalid_scope");
    expect(submitFeedback).not.toHaveBeenCalled();

    const overlong = await redirectUrl(() =>
      sendFeedbackAction(
        feedbackForm({
          runId: "run-1",
          itemId: "item-1",
          label: "relevant",
          reason: "x".repeat(2001),
        }),
      ),
    );
    expect(overlong).toBe("/observatory/runs/run-1?error=invalid_scope");
    expect(submitFeedback).not.toHaveBeenCalled();
  });

  it("maps API failures to typed error slugs on landing and run pages", async () => {
    createQuery.mockRejectedValueOnce(
      new ObservatoryApiError(401, "/q", "authentication"),
    );
    expect(await redirectUrl(() => submitQueryAction(feedbackForm({ question: "Q?" })))).toBe(
      "/observatory?error=authentication",
    );

    createRerun.mockRejectedValueOnce(new ObservatoryApiError(503, "/r", "unavailable"));
    expect(
      await redirectUrl(() =>
        rerunAction(feedbackForm({ queryId: "query-1", runId: "run-9" })),
      ),
    ).toBe("/observatory/runs/run-9?error=unavailable");

    submitFeedback.mockRejectedValueOnce(new ObservatoryContractError("bad body"));
    expect(
      await redirectUrl(() =>
        sendFeedbackAction(
          feedbackForm({ runId: "run-2", itemId: "item-1", label: "relevant" }),
        ),
      ),
    ).toBe("/observatory/runs/run-2?error=integrity");
  });
});

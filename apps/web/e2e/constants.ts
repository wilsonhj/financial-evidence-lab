import type { Page } from "@playwright/test";

// Ids come straight from the committed synthetic trace/filing fixtures
// (src/lib/observatory/fixtures/synthetic-trace.ts and
// src/lib/fixtures/synthetic-filing.ts). Fixture mode serves these verbatim,
// so the E2E suite asserts against them exactly.
export const RUN_ID = "ffffffff-0000-4000-8000-000000000001";
export const RERUN_ID = "ffffffff-0000-4000-8000-000000000002";
export const ABSTAINED_RUN_ID = "ffffffff-0000-4000-8000-000000000003";
// A well-formed but unknown run id: the mock source rejects it as unavailable.
export const MISSING_RUN_ID = "ffffffff-0000-4000-8000-00000000dead";

export const RUN_PATH = `/observatory/runs/${RUN_ID}`;
export const RERUN_PATH = `/observatory/runs/${RERUN_ID}`;
export const ABSTAINED_PATH = `/observatory/runs/${ABSTAINED_RUN_ID}`;
export const MISSING_PATH = `/observatory/runs/${MISSING_RUN_ID}`;
export const COMPARE_PATH = `/observatory/compare?a=${RUN_ID}&b=${RERUN_ID}`;

// The revenue passage: the highest-ranked dense candidate. Its reader deep link
// resolves to this document id and pre-selects this exact source span.
export const REVENUE_RAW_SCORE = "0.8123";
export const REVENUE_DOC_ID = "aaaaaaaa-0000-4000-8000-000000000001";
export const REVENUE_SPAN_ID = "cccccccc-0000-4000-8000-000000000001";

// Rejected candidates that must never render as supported: one published after
// the effective cutoff, one from a different document version. Each row is
// identified by its unique dense raw score.
export const FUTURE_RAW_SCORE = "0.6001";
export const CROSS_VERSION_RAW_SCORE = "0.5900";

export const QUESTION = "What was total revenue for Q1 2026?";

/**
 * Presses Tab (bounded) until the focused element's accessible text contains
 * `text`, proving the element is reachable by keyboard alone. Returns true on
 * success. No arbitrary sleeps: each Tab settles synchronously.
 */
export async function tabUntilFocusContains(
  page: Page,
  text: string,
  maxTabs = 25,
): Promise<boolean> {
  for (let i = 0; i < maxTabs; i += 1) {
    await page.keyboard.press("Tab");
    const focusedText = await page.evaluate(() => document.activeElement?.textContent ?? "");
    if (focusedText.includes(text)) return true;
  }
  return false;
}

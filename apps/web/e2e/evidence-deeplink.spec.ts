import { expect, test } from "@playwright/test";

import {
  REVENUE_DOC_ID,
  REVENUE_RAW_SCORE,
  REVENUE_SPAN_ID,
  RUN_PATH,
  tabUntilFocusContains,
} from "./constants";

test("candidate 'Open evidence' deep-links to the reader with the exact span preselected", async ({
  page,
}) => {
  await page.goto(RUN_PATH);

  const lanes = page.locator("section", {
    has: page.getByRole("heading", { name: "Retrieval lanes" }),
  });
  const revenueRow = lanes.locator("tr", { hasText: REVENUE_RAW_SCORE });
  await revenueRow.getByRole("link", { name: /Open evidence/ }).click();

  // The deep link carries the exact document id and source span in the URL.
  await expect(page).toHaveURL(new RegExp(`/reader/${REVENUE_DOC_ID}\\?span=${REVENUE_SPAN_ID}`));

  // The reader pre-selects precisely that span (aria-pressed), and only it.
  const pressed = page.locator('button.span-mark[aria-pressed="true"]');
  await expect(pressed).toHaveCount(1);
  await expect(pressed).toBeVisible();
});

test("the trace view is keyboard navigable: focus reaches a candidate and Enter activates it", async ({
  page,
}) => {
  await page.goto(RUN_PATH);

  // Tab from the top of the document; focus must reach a candidate's
  // "Open evidence" link without a pointer.
  const reached = await tabUntilFocusContains(page, "Open evidence");
  expect(reached).toBe(true);

  // Keyboard activation follows the deep link, just like a click would.
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/reader\/.*\?span=/);
  await expect(page.locator('button.span-mark[aria-pressed="true"]')).toBeVisible();
});

test("the skip link is the first focusable element and Tab reaches the first cited span", async ({
  page,
}) => {
  await page.goto(`/reader/${REVENUE_DOC_ID}`);

  // The very first Tab from a fresh page must land on the skip link, before
  // any repeated header/nav chrome.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();

  // Activating it jumps focus to the main reader landmark, past the header.
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();

  // Continuing to Tab from the top reaches a real, focusable citation span
  // button — proving the DocumentPane spans are keyboard-operable, not just
  // clickable. Bounded so the check stays fast even if the outline grows.
  await page.goto(`/reader/${REVENUE_DOC_ID}`);
  let reachedSpan = false;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    await page.keyboard.press("Tab");
    const isSpan = await page.evaluate(
      () => document.activeElement?.classList.contains("span-mark") ?? false,
    );
    if (isSpan) {
      reachedSpan = true;
      break;
    }
  }
  expect(reachedSpan).toBe(true);
});

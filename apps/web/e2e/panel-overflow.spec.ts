import { expect, test } from "@playwright/test";

import { REVENUE_DOC_ID } from "./constants";

/**
 * The reader's evidence panel is a sticky column that scrolls VERTICALLY
 * (`.evidence-panel { overflow-y: auto }`). It was never meant to scroll
 * horizontally — but per CSS overflow rules, declaring one axis `auto` while
 * the other stays `visible` promotes that other axis to `auto` too. So a
 * single unbreakable token is enough to silently turn the panel into a
 * horizontal scroller, and every block child then stretches to the widened
 * content box, slicing headings and quotes mid-word at the panel edge.
 *
 * The trigger here is the XBRL concept name (`us-gaap:RevenueFrom...`), a
 * ~59-character string with no break opportunity. `.obs-meta dd` already
 * guards the same hazard with `word-break: break-word`; the reader's fact
 * list did not.
 *
 * Asserting scrollWidth <= clientWidth fails on the layout itself, so it
 * cannot be satisfied by a stylesheet edit that does not actually reflow.
 */
test("the reader evidence panel does not overflow horizontally", async ({ page }) => {
  await page.goto(`/reader/${REVENUE_DOC_ID}`);

  const panel = page.locator(".evidence-panel");
  await expect(panel).toBeVisible();

  const { clientWidth, scrollWidth } = await panel.evaluate((el) => ({
    clientWidth: el.clientWidth,
    scrollWidth: el.scrollWidth,
  }));

  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1);
});

test("a long XBRL concept name wraps instead of widening the panel", async ({ page }) => {
  await page.goto(`/reader/${REVENUE_DOC_ID}`);

  // The concept value is the widest unbreakable token in the panel.
  const concept = page.locator(".fact-card dd", { hasText: /^us-gaap:/ }).first();
  await expect(concept).toBeVisible();

  const panelRight = await page
    .locator(".evidence-panel")
    .evaluate((el) => el.getBoundingClientRect().left + el.clientWidth);
  const conceptRight = await concept.evaluate((el) => el.getBoundingClientRect().right);

  // Its right edge must sit inside the panel's visible content box.
  expect(conceptRight).toBeLessThanOrEqual(panelRight + 1);
});

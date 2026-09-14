import { expect, test } from "@playwright/test";

import { RUN_PATH } from "./constants";

/**
 * WCAG 2.2 SC 1.4.10 (Reflow): no horizontal document scrolling at 320px CSS
 * width. The filings table cannot honour that by wrapping — its min-content
 * width is 525px in a 350px content box, and the Status badge alone claims
 * 191px because `.badge` is `white-space: nowrap`. Forcing every column to
 * wrap still left 22px over at 320px while crushing five columns to equal
 * widths.
 *
 * A data table is explicitly exempt from reflow ("content requiring
 * two-dimensional layout"). The defect is therefore not that the table is
 * wide, but that its scroll landed on the DOCUMENT instead of on a contained
 * region. This asserts the scroll is contained, mirroring `.obs-lane`.
 */
for (const width of [320, 390]) {
  test(`filings index does not scroll the document at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/");

    // A width assertion alone is satisfied by an error page or an empty
    // render, so pin the content first: the defect only exists when the
    // filings table is actually populated.
    await expect(page.locator("table.doc-table tbody tr").first()).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
}

test("the filings table scrolls inside its own region, and that region is keyboard reachable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const region = page.getByRole("region", { name: "Filings" });
  await expect(region).toBeVisible();

  // The region, not the document, absorbs the overflow.
  const scrollable = await region.evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(scrollable).toBeGreaterThan(0);

  /**
   * Chromium only auto-focuses a scroller that has NO focusable children.
   * Every filings row contains a link, so without an explicit tabIndex the
   * region is skipped and the Period/Published/Status columns — which hold no
   * focusable content — become unreachable without a pointer (SC 2.1.1).
   */
  // Reach the region by ACTUAL Tab navigation, never region.focus().
  // Programmatic focus succeeds on tabIndex={-1} too, so a focus() based
  // assertion passes even when a keyboard user can never get here — the exact
  // regression this test exists to catch.
  await page.keyboard.press("Tab");
  let reached = false;
  for (let i = 0; i < 30; i += 1) {
    if (await region.evaluate((el) => el === document.activeElement)) {
      reached = true;
      break;
    }
    await page.keyboard.press("Tab");
  }
  expect(reached).toBe(true);
  expect(await region.evaluate((el) => el.scrollLeft)).toBe(0);

  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");

  // Keyboard scrolling is asynchronous, so poll the condition rather than
  // reading scrollLeft synchronously after the keypress.
  await expect
    .poll(async () => region.evaluate((el) => el.scrollLeft), { timeout: 5000 })
    .toBeGreaterThan(0);

  // Tab must continue onward out of the region, not trap focus inside it.
  await page.keyboard.press("Tab");
  expect(await region.evaluate((el) => el === document.activeElement)).toBe(false);
});

/**
 * The retrieval-run page scrolled the whole document sideways at every
 * viewport (34px at 1440 rising to 298px at 320). The cause was not a grid
 * track or a wide table: `.visually-hidden` is position: absolute with no
 * inset, so it painted at its static position inside a lane table scrolled up
 * to 600px right, while its containing block resolved past the static
 * `.obs-lane` to the initial containing block. A scroll container cannot clip
 * a descendant it does not contain, so that right edge became the DOCUMENT's
 * overflow. A screen-reader-only helper was causing a Reflow failure.
 */
for (const width of [320, 390, 768, 1024, 1440]) {
  test(`retrieval run page does not scroll the document at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(RUN_PATH);

    // Pin the content: an error page would satisfy the width check.
    await expect(page.getByRole("heading", { name: "Retrieval lanes" })).toBeVisible();
    await expect(page.locator(".obs-lane").first()).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
}

test("lanes still scroll inside their own box after the containing-block fix", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(RUN_PATH);

  // The fix must confine the escaping boxes WITHOUT disabling the deliberate
  // per-lane horizontal scrolling, which is how wide lane tables stay usable.
  const lanes = await page.locator(".obs-lane").evaluateAll((els) =>
    els.map((el) => ({
      overflowX: getComputedStyle(el).overflowX,
      scrollable: el.scrollWidth - el.clientWidth,
    })),
  );

  expect(lanes.length).toBeGreaterThan(0);
  expect(lanes.every((l) => l.overflowX === "auto")).toBe(true);
  expect(lanes.some((l) => l.scrollable > 0)).toBe(true);
});

/**
 * The Update Desk scrolled the document at every width from 320 to ~455px.
 * A bare `1fr` is `minmax(auto, 1fr)`, and that auto floor resolves to
 * `.desk-sidebar`'s min-content — 455.7px once the sidebar becomes a row
 * (12 + brand 110.7 + gap 12 + nav 309 + 12). The floor outran the viewport,
 * so BOTH grid items stretched to 455.7px.
 *
 * The `overflow: auto` already on `.desk-sidebar nav` could not absorb it:
 * overflow zeroes a flex item's automatic MINIMUM size, not its container's
 * intrinsic min-content size, so the nav was never asked to shrink and that
 * scroller had never once engaged. Asserting it now scrolls pins the real
 * mechanism, so this fails on the layout rather than on a stylesheet edit
 * that does not actually reflow.
 */
for (const width of [320, 390]) {
  test(`update desk does not scroll the document at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/desk");

    // Pin the content: an error page would satisfy the width check.
    await expect(
      page.locator(".desk-sidebar nav").getByRole("button", { name: "Coverage" }),
    ).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
}

test("the desk sidebar nav absorbs the overflow and every tab stays keyboard reachable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto("/desk");

  const nav = page.locator(".desk-sidebar nav");
  const scrollable = await nav.evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(scrollable).toBeGreaterThan(0);

  /**
   * Unlike the filings table, this scroller needs no tabIndex: it contains
   * nothing but focusable buttons and no non-focusable content, so Tab alone
   * reaches every tab. Reach them by REAL Tab presses — `.focus()` would pass
   * even if the tab order skipped the nav entirely.
   *
   * Deliberately NOT asserted: that each focused tab is fully inside the nav's
   * visible box. Chromium's scroll-into-view stops short of maximum scroll by
   * a varying amount (measured 13px at 320, 30px at 360, 0 at 390, 26px at
   * 430), so a pixel-visibility assertion would be flaky and would be testing
   * the browser rather than this layout. Reachable and activatable is the
   * property SC 2.1.1 actually requires, and it holds at every width.
   */
  const reached: string[] = [];
  for (let i = 0; i < 25 && reached.length < 4; i += 1) {
    await page.keyboard.press("Tab");
    const label = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el.tagName !== "BUTTON" || !el.closest(".desk-sidebar nav")) return null;
      return el.textContent?.trim() ?? null;
    });
    if (label && !reached.includes(label)) reached.push(label);
  }

  expect(reached).toEqual(["Coverage", "Research", "Review", "Model"]);
});

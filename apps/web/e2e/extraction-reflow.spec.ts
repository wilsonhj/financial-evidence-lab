import { expect, test } from "@playwright/test";

/**
 * WCAG 2.2 SC 1.4.10 (Reflow) across the extraction surface. Two distinct
 * causes, both already solved elsewhere in this stylesheet:
 *
 *  - Wide data tables (up to 587px against a 350px content box). A data table
 *    is exempt from reflow because it needs two-dimensional layout, so the
 *    scroll belongs to a contained region, not the document. Same remedy as
 *    the filings table's `.doc-scroll`.
 *  - A 71-character `sha256:...` evidence-manifest digest with no break
 *    opportunity, which sets its paragraph's min-content width. Same shape as
 *    the XBRL concept name in the reader's fact panel.
 *
 * Measured before the fix, document overflow at 320 / 390:
 *   /extractions                    287 / 217
 *   /extractions/{id}               241 / 171
 *   /extraction-runs                153 /  83
 *   /extraction-runs/{id}           130 /  60
 *   /approved-extractions/{id}      368 / 298
 */
const PROPOSAL_ID = "eeeeeeee-0000-4000-8000-000000000003";
const RUN_ID = "eeeeeeee-0000-4000-8000-000000000002";
const APPROVED_ID = "eeeeeeee-0000-4000-8000-000000000007";

/**
 * Each route carries a content sentinel. A width assertion alone is satisfied
 * by an error page or an empty render, so the sentinel proves the page that
 * actually exhibited the overflow is the page under test.
 */
const ROUTES = [
  ["review queue", "/extractions", "Proposals on this page"],
  ["proposal detail", `/extractions/${PROPOSAL_ID}`, "Proposals on this page"],
  ["run history", "/extraction-runs", "Run history"],
  ["run detail", `/extraction-runs/${RUN_ID}`, "Execution steps in order"],
  ["approved record", `/approved-extractions/${APPROVED_ID}`, "Evidence manifest"],
] as const;

for (const [name, path, sentinel] of ROUTES) {
  for (const width of [320, 390]) {
    test(`${name} does not scroll the document at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(path);

      await expect(page.getByText(sentinel, { exact: false }).first()).toBeVisible();

      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }
}

test("extraction tables scroll inside a keyboard-reachable region", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto("/extractions");

  const region = page.getByRole("region", { name: "Proposals on this page" });
  await expect(region).toBeVisible();
  expect(await region.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeGreaterThan(0);

  /**
   * Reach it by real Tab presses. `.focus()` would pass with tabIndex={-1},
   * where a keyboard user can never get here — and these tables carry columns
   * with no focusable content, so a skipped scroller strands them.
   */
  let reached = false;
  for (let i = 0; i < 40 && !reached; i += 1) {
    await page.keyboard.press("Tab");
    reached = await region.evaluate((el) => el === document.activeElement);
  }
  expect(reached).toBe(true);
});

test("the evidence manifest digest wraps instead of widening the page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/approved-extractions/${APPROVED_ID}`);

  const digest = page.locator("p", { hasText: /^Evidence manifest: sha256:/ }).first();
  await expect(digest).toBeVisible();

  // Its own content must fit; a 71-char token otherwise sets min-content.
  const contained = await digest.evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(contained).toBeLessThanOrEqual(1);
});

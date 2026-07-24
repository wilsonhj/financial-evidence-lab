import { expect, test } from "@playwright/test";

import {
  ABSTAINED_PATH,
  CROSS_VERSION_RAW_SCORE,
  FUTURE_RAW_SCORE,
  MISSING_PATH,
  REVENUE_RAW_SCORE,
  RUN_PATH,
} from "./constants";

test("future and cross-version candidates render rejected, never supported", async ({ page }) => {
  await page.goto(RUN_PATH);

  const lanes = page.locator("section", {
    has: page.getByRole("heading", { name: "Retrieval lanes" }),
  });

  // The supported baseline: the in-cutoff revenue passage is labelled supported.
  const supportedRow = lanes.locator("tr", { hasText: REVENUE_RAW_SCORE });
  await expect(supportedRow.getByText("supported", { exact: true })).toBeVisible();

  // Future-dated candidate: rejected, and its row never says "supported".
  const futureRow = lanes.locator("tr", { hasText: FUTURE_RAW_SCORE });
  await expect(futureRow.getByText("rejected", { exact: true })).toBeVisible();
  await expect(futureRow.getByText("supported", { exact: true })).toHaveCount(0);

  // Cross-version candidate: same guarantee.
  const crossRow = lanes.locator("tr", { hasText: CROSS_VERSION_RAW_SCORE });
  await expect(crossRow.getByText("rejected", { exact: true })).toBeVisible();
  await expect(crossRow.getByText("supported", { exact: true })).toHaveCount(0);

  // Both appear in the rejection timeline with their reason codes.
  const timeline = page.locator("section", {
    has: page.getByRole("heading", { name: "Filter and rejection timeline" }),
  });
  await expect(timeline.getByText("temporal_after_cutoff").first()).toBeVisible();
  await expect(timeline.getByText("cross_version").first()).toBeVisible();
});

test("abstention is a distinct state from contradiction and from a transport error", async ({
  page,
}) => {
  // Abstained run: its own typed run-state banner, not a claim contradiction.
  await page.goto(ABSTAINED_PATH);
  await expect(page.getByRole("heading", { name: "Run abstained" })).toBeVisible();
  await expect(page.getByText("Run status:")).toContainText("abstained");
  // No claims, so no contradiction badge, and it is not an error state.
  await expect(page.getByText("contradicted")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Evidence service unavailable" })).toHaveCount(0);

  // Contradiction is a claim-level outcome on an otherwise succeeded run —
  // distinct from the run abstaining.
  await page.goto(RUN_PATH);
  await expect(page.getByText("Run status:")).toContainText("succeeded");
  const claims = page.locator("section", {
    has: page.getByRole("heading", { name: "Claims and citations" }),
  });
  await expect(claims.getByText("contradicted").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Run abstained" })).toHaveCount(0);

  // Transport/availability error: the public-safe failure state, distinct from
  // both abstention and contradiction.
  await page.goto(MISSING_PATH);
  await expect(page.getByRole("heading", { name: "Evidence service unavailable" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Run abstained" })).toHaveCount(0);
  await expect(page.getByText("contradicted")).toHaveCount(0);
});

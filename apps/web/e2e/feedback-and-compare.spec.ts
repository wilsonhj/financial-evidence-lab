import { expect, test } from "@playwright/test";

import { RERUN_ID, RUN_ID, RUN_PATH } from "./constants";

test("submitting evidence feedback shows a recorded confirmation", async ({ page }) => {
  await page.goto(RUN_PATH);

  const feedback = page.locator("section", {
    has: page.getByRole("heading", { name: "Evidence feedback" }),
  });
  // One feedback form per candidate; submit the first.
  await feedback.getByRole("button", { name: "Send" }).first().click();

  await expect(page).toHaveURL(/feedback=recorded/);
  await expect(page.getByRole("status")).toContainText("Feedback recorded.");
});

test("run comparison view renders both runs side by side", async ({ page }) => {
  await page.goto(RUN_PATH);

  // Reach the comparison via the in-page link the run view offers.
  await page.getByRole("link", { name: /Compare with run/ }).click();
  await expect(page).toHaveURL(new RegExp(`a=${RUN_ID}&b=${RERUN_ID}`));

  const comparison = page.locator("section", {
    has: page.getByRole("heading", { name: "Run comparison" }),
  });
  await expect(
    comparison.getByRole("columnheader", { name: `Run A (${RUN_ID.slice(0, 8)})` }),
  ).toBeVisible();
  await expect(
    comparison.getByRole("columnheader", { name: `Run B (${RERUN_ID.slice(0, 8)})` }),
  ).toBeVisible();

  // Metric rows both runs report (identical fixture data => equal values).
  const statusRow = comparison.locator("tr", { hasText: "Status" });
  await expect(statusRow).toContainText("succeeded");
  const supportedRow = comparison.locator("tr", { hasText: "Supported candidates" });
  await expect(supportedRow).toContainText("3");
});

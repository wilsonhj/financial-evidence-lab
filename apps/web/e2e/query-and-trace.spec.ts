import { expect, test } from "@playwright/test";

import { QUESTION, REVENUE_RAW_SCORE, RUN_ID } from "./constants";

test("query form creates a run and renders the trace view", async ({ page }) => {
  await page.goto("/observatory");
  await expect(page.getByRole("heading", { level: 1, name: "Search Observatory" })).toBeVisible();

  await page.getByLabel("Question").fill(QUESTION);
  await page.getByRole("button", { name: "Run query" }).click();

  // The server action creates the run and redirects to its trace view.
  await expect(page).toHaveURL(new RegExp(`/observatory/runs/${RUN_ID}$`));
  await expect(page.getByRole("heading", { level: 1, name: "Retrieval run" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Query plan" })).toBeVisible();
  await expect(page.getByText(QUESTION)).toBeVisible();
});

test("renders four retrieval lanes with raw, RRF, fused and rerank ranks/scores", async ({
  page,
}) => {
  await page.goto(`/observatory/runs/${RUN_ID}`);

  const lanes = page.locator("section", {
    has: page.getByRole("heading", { name: "Retrieval lanes" }),
  });
  await expect(lanes.getByRole("heading", { level: 3, name: "Dense" })).toBeVisible();
  await expect(lanes.getByRole("heading", { level: 3, name: "Lexical" })).toBeVisible();
  await expect(lanes.getByRole("heading", { level: 3, name: "Facts" })).toBeVisible();
  await expect(lanes.getByRole("heading", { level: 3, name: "Tables" })).toBeVisible();

  // Tables has no candidates in the fixture: the empty state distinguishes the
  // fourth lane column from the three populated ones.
  await expect(lanes.getByText("No candidates in this lane.")).toBeVisible();

  // Every ranking column the acceptance calls for is present.
  await expect(lanes.getByRole("columnheader", { name: "Raw" }).first()).toBeVisible();
  await expect(lanes.getByRole("columnheader", { name: "RRF" }).first()).toBeVisible();
  await expect(
    lanes.getByRole("columnheader", { name: "Fused (rank / score)" }).first(),
  ).toBeVisible();
  await expect(
    lanes.getByRole("columnheader", { name: "Rerank (rank / score)" }).first(),
  ).toBeVisible();

  // The top dense candidate carries its raw score plus fused/rerank rank+score.
  const revenueRow = lanes.locator("tr", { hasText: REVENUE_RAW_SCORE });
  await expect(revenueRow).toContainText("0.0164"); // RRF contribution
  await expect(revenueRow).toContainText("1 / 0.0325"); // fused rank / score
  await expect(revenueRow).toContainText("1 / 0.9910"); // rerank rank / score
});

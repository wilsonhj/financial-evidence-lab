import { expect, test } from "@playwright/test";
import { REVENUE_DOC_ID, REVENUE_SPAN_ID, RUN_PATH } from "./constants";

test("filing pages expose entity and direction without claiming complete amendment history", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByLabel("Entity", { exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Filing pages" })).toBeVisible();
  await expect(page.getByText("Current", { exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "Newest first", exact: true }).click();
  await expect(page).toHaveURL(/order=desc/);
  const accessions = await page.locator("tbody tr td:nth-child(2)").allTextContents();
  expect(accessions.length).toBeGreaterThan(0);
});

test("related history loads explicitly and preserves the target version cutoff and selected span", async ({
  page,
}) => {
  await page.goto(`/reader/${REVENUE_DOC_ID}?span=${REVENUE_SPAN_ID}`);
  await expect(page.getByText(/Related history incomplete\./).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Load related filings", exact: true })).toBeVisible();
  await expect(page.locator('button.span-mark[aria-pressed="true"]')).toHaveCount(1);
  await page.getByRole("link", { name: "Load related filings", exact: true }).click();
  await expect(page).toHaveURL(/document_version_id=/);
  const url = new URL(page.url());
  expect(url.searchParams.get("document_version_id")).toBeTruthy();
  expect(url.searchParams.get("as_of")).toBeTruthy();
  expect(url.searchParams.get("span")).toBe(REVENUE_SPAN_ID);
  await expect(page.getByRole("navigation", { name: "Related filing pages" })).toBeVisible();
  await expect(page.getByText(/Related history incomplete\./)).toHaveCount(0);
  await expect(page.locator('button.span-mark[aria-pressed="true"]')).toHaveCount(1);
});

test("run and persisted event histories have independent navigation", async ({ page }) => {
  await page.goto(RUN_PATH);
  await expect(page.getByRole("navigation", { name: "Run history pages" })).toBeVisible();
  await page.getByRole("link", { name: "Inspect event history", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Persisted event history" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Event history pages" })).toBeVisible();
  await page.getByRole("link", { name: "Newest first", exact: true }).click();
  await expect(page.locator("ol li").first()).toContainText("run_completed");
});

import { expect, test } from "@playwright/test";

test("claim filtering keeps the visible evidence aligned", async ({ page }) => {
  await page.goto("/desk");
  await page.getByTestId("nav-section-research").click();
  await page.getByTestId("input-search-claims").fill("guidance");

  await expect(page.getByTestId("button-claim-nrr")).toHaveCount(0);
  await expect(page.getByTestId("evidence-claim-guidance")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Revenue guidance narrowed" })).toBeVisible();

  await page.getByTestId("nav-section-review").click();
  await page.getByTestId("nav-section-research").click();
  await expect(page.getByTestId("button-claim-guidance")).toHaveAttribute("aria-pressed", "true");
});

test("review requires an explicit source, saved decision, and both approvals", async ({ page }) => {
  await page.goto("/desk");
  await page.getByTestId("nav-section-review").click();

  const saveResolution = page.getByTestId("button-save-resolution");
  const applyFacts = page.getByTestId("button-apply-facts");
  await expect(saveResolution).toBeDisabled();
  await expect(applyFacts).toBeDisabled();

  await page.getByTestId("button-source-filing").click();
  await page
    .getByTestId("input-rationale")
    .fill("Filed 10-Q disclosure is the authoritative modeled metric.");
  await expect(saveResolution).toBeEnabled();
  await saveResolution.click();

  await page.getByTestId("checkbox-approval-1").check();
  await page.getByTestId("checkbox-approval-2").check();
  await expect(applyFacts).toBeEnabled();
  await applyFacts.click();

  await page.getByTestId("nav-section-model").click();
  await expect(page.getByTestId("text-packet-readiness")).toHaveText("Ready for PM review");
  await expect(page.getByTestId("button-packet-readiness")).toBeEnabled();
});

test("OLED appearance restores before interaction and persists", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("fel-theme", "oled"));
  await page.goto("/desk");

  await expect(page.locator("html")).toHaveAttribute("data-fel-theme", "oled");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-fel-theme", "oled");

  await page.getByTestId("button-theme-menu").click();
  await page.getByTestId("button-theme-light").click();
  await expect(page.locator("html")).toHaveAttribute("data-fel-theme", "light");
  await expect
    .poll(() => page.evaluate(() => window.localStorage.getItem("fel-theme")))
    .toBe("light");
});

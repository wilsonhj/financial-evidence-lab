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
  await expect(page.getByTestId("text-fy27-caption")).toHaveText(
    "Facts staged in this session · preview figures unchanged",
  );
  await expect(page.getByTestId("text-packet-readiness")).toHaveText(
    "Session gates complete · packet export is not available",
  );
  await expect(page.getByTestId("button-packet-readiness")).toBeDisabled();
});

function relativeLuminance(rgb: string): number {
  const match = rgb.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (!match) return 0;
  const [r, g, b] = match.slice(1).map((part) => {
    const channel = Number(part) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(first: string, second: string): number {
  const a = relativeLuminance(first);
  const b = relativeLuminance(second);
  const lighter = Math.max(a, b);
  const darker = Math.min(a, b);
  return (lighter + 0.05) / (darker + 0.05);
}

test("system dark mode keeps desk text readable", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/desk");
  await expect(page.getByTestId("desk-shell")).toBeVisible();
  const shell = page.getByTestId("desk-shell");
  const color = await shell.evaluate((el) => getComputedStyle(el).color);
  const background = await shell.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(contrastRatio(color, background)).toBeGreaterThanOrEqual(4.5);
  await page.getByTestId("nav-section-review").click();
  const apply = page.getByTestId("button-apply-facts");
  const applyColor = await apply.evaluate((el) => getComputedStyle(el).color);
  const applyBackground = await apply.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(contrastRatio(applyColor, applyBackground)).toBeGreaterThanOrEqual(4.5);
});

test("blocked localStorage still renders the desk", async ({ page }) => {
  await page.addInitScript(() => {
    const blocked = {
      getItem() {
        throw new Error("The operation is insecure.");
      },
      setItem() {
        throw new Error("The operation is insecure.");
      },
      removeItem() {
        throw new Error("The operation is insecure.");
      },
      clear() {
        throw new Error("The operation is insecure.");
      },
      key() {
        return null;
      },
      length: 0,
    };
    Object.defineProperty(window, "localStorage", { configurable: true, value: blocked });
  });
  await page.goto("/desk");
  await expect(page.getByTestId("desk-shell")).toBeVisible();
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

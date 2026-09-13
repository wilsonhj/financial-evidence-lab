import { test, expect } from "@playwright/test";

const proposal = "eeeeeeee-0000-4000-8000-000000000003";
const alternative = "eeeeeeee-0000-4000-8000-000000000004";
const invalid = "eeeeeeee-0000-4000-8000-000000000005";
const run = "eeeeeeee-0000-4000-8000-000000000002";
const record = "eeeeeeee-0000-4000-8000-000000000007";

test.describe.serial("extraction review fixture browser acceptance", () => {
  test.describe.configure({ retries: 0 });
  test("reads exact candidate text, evidence pins and keyboard queue navigation", async ({
    page,
  }) => {
    await page.goto(`/extractions/${invalid}`);
    await expect(page.getByRole("heading", { name: "Read-only candidate fields" })).toBeVisible();
    await expect(page.getByText("9007199254740993", { exact: true })).toBeVisible();
    await expect(page.getByText('"<script>alert(1)</script>"', { exact: true })).toBeVisible();
    await expect(
      page.getByText("No evidence edges recorded. Approval still requires verified evidence."),
    ).toBeVisible();
    await page.goto(`/extractions/${proposal}`);
    const evidence = page.getByRole("link", { name: /Read evidence span/ });
    await expect(evidence).toHaveAttribute(
      "href",
      /document_version_id=aaaaaaaa-0000-4000-8000-000000001001/,
    );
    await expect(evidence).toHaveAttribute("href", /as_of=2026-07-01T00%3A00%3A00Z/);
    await evidence.click();
    await expect(page.getByRole("heading", { name: "10-Q — 0000111111-26-000123" })).toBeVisible();
    await page.goto("/extractions?limit=1");
    await page.getByRole("link", { name: "Next page" }).focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/cursor=/);
    await expect(page.getByRole("checkbox", { name: `Select arr ${alternative}` })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: `Select arr ${proposal}` })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Previous page" })).toBeVisible();
  });

  test("accepts an explicit winner and leaves the unselected alternative unchanged", async ({
    page,
  }) => {
    await page.goto("/extractions");
    await page.getByRole("checkbox", { name: `Select arr ${proposal}` }).check();
    await page.getByRole("button", { name: "Load complete conflict context" }).click();
    await expect(
      page.getByText("Complete conflict membership loaded. Choose the winners explicitly."),
    ).toBeVisible();
    await page.getByRole("checkbox", { name: "Explicit winner" }).check();
    await page
      .getByLabel("Reason", { exact: true })
      .fill("Reviewed synthetic source and selected this winner");
    await page.getByRole("button", { name: "Submit atomic review" }).click();
    await expect(page.getByRole("status")).toContainText(
      "Atomic accept completed for 1 selected proposals",
    );
    await expect(page.getByRole("link", { name: "Approved version 1" })).toBeVisible();
    const untouched = await (
      await page.request.get(`/api/extraction/proposals/${alternative}`)
    ).json();
    expect(untouched.state).toBe("needs_review");
    expect(untouched.version).toBe(1);
  });

  test("preserves a stale correction draft and appends immutable history after comparison", async ({
    page,
    context,
  }) => {
    const original = await (await page.request.get(`/api/extraction/approved/${record}`)).json();
    const body = {
      reason: "First synthetic correction",
      payload: original.payload,
      evidence: original.evidence,
    };
    await page.goto(`/approved-extractions/${record}`);
    await page
      .getByLabel("Full correction JSON (reason, strict payload and evidence)")
      .fill(JSON.stringify(body));
    const second = await context.newPage();
    await second.goto(`/approved-extractions/${record}`);
    const draft = JSON.stringify({ ...body, reason: "Preserved second correction" });
    await second
      .getByLabel("Full correction JSON (reason, strict payload and evidence)")
      .fill(draft);
    await page.getByRole("button", { name: "Submit full correction" }).click();
    await expect(page.getByRole("link", { name: "Open approved version 2" })).toBeVisible();
    await second.getByRole("button", { name: "Submit full correction" }).click();
    await expect(second.getByRole("status")).toContainText("Your draft is preserved");
    await expect(
      second.getByLabel("Full correction JSON (reason, strict payload and evidence)"),
    ).toHaveValue(draft);
    await second.getByRole("button", { name: "Refresh current version for comparison" }).click();
    await expect(second.getByRole("heading", { name: "Current version 2" })).toBeVisible();
    await second.getByRole("button", { name: "Use refreshed version" }).click();
    await second.getByRole("button", { name: "Submit full correction" }).click();
    await expect(second.getByRole("link", { name: "Open approved version 3" })).toBeVisible();
    await second.getByRole("link", { name: "Open approved version 3" }).click();
    await second.getByRole("link", { name: "Previous immutable version" }).click();
    await expect(second.getByText("Reason: First synthetic correction")).toBeVisible();
    const previous = await (
      await page.request.get(`/api/extraction/approved/${record}/versions/${original.version_id}`)
    ).json();
    expect(previous).toEqual(original);
    await second.close();
  });

  test("keeps waiting-review stream open for review completion and starts a child rerun", async ({
    page,
    context,
  }) => {
    await page.goto(`/extraction-runs/${run}`);
    await expect(
      page
        .getByRole("region", { name: "Live extraction events" })
        .getByRole("cell", { name: "review_waiting", exact: true }),
    ).toBeVisible();
    const reviewPage = await context.newPage();
    await reviewPage.goto("/extractions");
    await reviewPage.getByRole("checkbox", { name: `Select arr ${alternative}` }).check();
    await reviewPage.getByRole("checkbox", { name: `Select arr ${invalid}` }).check();
    await reviewPage.getByRole("button", { name: "Load complete conflict context" }).click();
    await expect(
      reviewPage.getByText("Complete conflict membership loaded. Choose the winners explicitly."),
    ).toBeVisible();
    await reviewPage.getByLabel("Review action").selectOption("reject");
    await reviewPage
      .getByLabel("Reason", { exact: true })
      .fill("Reject remaining synthetic alternatives");
    await reviewPage.getByRole("button", { name: "Submit atomic review" }).click();
    await expect(reviewPage.getByRole("status")).toContainText(
      "Atomic reject completed for 2 selected proposals",
    );
    await expect(
      page
        .getByRole("region", { name: "Live extraction events" })
        .getByRole("cell", { name: "run_succeeded", exact: true }),
    ).toBeVisible();
    await page.getByLabel("Rerun reason").fill("Start unchanged child after adjudication");
    await page.getByRole("button", { name: "Create unchanged child run" }).click();
    const childLink = page.getByRole("link", { name: /^Open run / });
    await expect(childLink).toBeVisible();
    await childLink.click();
    await expect(page.getByRole("link", { name: "Original parent run" })).toHaveAttribute(
      "href",
      `/extraction-runs/${run}`,
    );
    await page.getByRole("button", { name: "Request cancellation" }).click();
    await expect(
      page
        .getByRole("region", { name: "Live extraction events" })
        .getByRole("cell", { name: "run_cancelled", exact: true }),
    ).toBeVisible();
    await reviewPage.close();
  });
});

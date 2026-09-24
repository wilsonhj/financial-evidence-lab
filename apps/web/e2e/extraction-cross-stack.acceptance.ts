import { execFile } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { test, expect } from "@playwright/test";

const manifestPath = process.env.CROSS_STACK_MANIFEST!;
const seed = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, string>;
const root = fileURLToPath(new URL("../../..", import.meta.url));
const execute = promisify(execFile);

async function harness(action: "work" | "verify", ...args: string[]) {
  await execute(
    process.env.FEL_ACCEPTANCE_PYTHON ?? "python",
    ["-m", "evals.harness.extraction_cross_stack", action, "--manifest", manifestPath, ...args],
    { cwd: root, timeout: 60_000, env: process.env },
  );
}

test("real HTTP API, durable worker, browser review, correction and live SSE", async ({
  page,
  context,
}) => {
  // No page.route, API interception or fixture source: every request reaches
  // the production Next proxy and authenticated, mounted FastAPI router.
  await page.goto("/extraction-runs");
  await page
    .getByLabel(
      "Run request JSON (entity_id, as_of, modes, source_span_ids; optional corpus_version_id)",
    )
    .fill(
      JSON.stringify({
        entity_id: seed.entity,
        as_of: "2026-12-31T00:00:00Z",
        modes: ["kpi"],
        source_span_ids: [seed.span],
        corpus_version_id: seed.corpus,
      }),
    );
  await page.getByRole("button", { name: "Create bounded run" }).click();
  const link = page.getByRole("link", { name: /^Open run / });
  await expect(link).toBeVisible();
  const runId = (await link.getAttribute("href"))!.split("/").at(-1)!;
  const queuedResponse = await page.request.get(`/api/extraction/runs/${runId}`);
  expect(queuedResponse.status()).toBe(200);
  const queued = await queuedResponse.json();
  expect(queued.status).toBe("queued");
  expect(queued.as_of).toMatch(/^2026-07-01T00:00:00/);
  expect(queued.corpus_version_id).toBe(seed.corpus);
  await link.click();
  const stream = page.getByRole("region", { name: "Live extraction events" });
  await expect(stream.getByRole("cell", { name: "run_queued", exact: true })).toBeVisible();

  // The stream is already open when another process claims the job, runs the
  // real workflow, persists proposals and publishes review_waiting.
  await harness("work");
  await expect(stream.getByRole("cell", { name: "review_waiting", exact: true })).toBeVisible();
  const proposalsResponse = await page.request.get("/api/extraction/proposals");
  expect(proposalsResponse.status()).toBe(200);
  const proposals = (await proposalsResponse.json()).items;
  expect(proposals).toHaveLength(1);
  const proposal = proposals[0];
  expect(proposal.run_id).toBe(runId);
  expect(proposal.record_confidence).toBeNull();
  expect(proposal.evidence[0].source_span_id).toBe(seed.span);
  expect(proposal.evidence[0].document_version_id).toBe(seed.version);

  const reviewer = await context.newPage();
  await reviewer.goto(`/extractions/${proposal.id}`);
  const evidenceLink = reviewer.getByRole("link", { name: `Read evidence span ${seed.span}` });
  await expect(evidenceLink).toHaveAttribute(
    "href",
    new RegExp(`document_version_id=${seed.version}`),
  );
  await evidenceLink.click();
  await expect(reviewer.getByRole("heading", { name: `10-Q — ${seed.document}` })).toBeVisible();
  await expect(
    reviewer.getByRole("button", {
      name: "Cited source span: Annual recurring revenue was $100 million at June 30, 2026.",
    }),
  ).toBeVisible();
  await reviewer.goto("/extractions");
  await reviewer.getByRole("checkbox", { name: `Select arr ${proposal.id}` }).check();
  await reviewer.getByRole("button", { name: "Load complete conflict context" }).click();
  await expect(
    reviewer.getByText("Complete conflict membership loaded. Choose the winners explicitly."),
  ).toBeVisible();
  await reviewer
    .getByLabel("Reason", { exact: true })
    .fill("Verified synthetic canonical evidence");
  await reviewer.getByRole("button", { name: "Submit atomic review" }).click();
  await expect(reviewer.getByRole("status")).toContainText(
    "Atomic accept completed for 1 selected proposals",
  );
  const approvedLink = reviewer.getByRole("link", { name: "Approved version 1" });
  await expect(approvedLink).toBeVisible();
  const recordId = (await approvedLink.getAttribute("href"))!.split("/")[2]!;
  await expect(stream.getByRole("cell", { name: "review_completed", exact: true })).toBeVisible();
  await expect(stream.getByRole("cell", { name: "run_succeeded", exact: true })).toBeVisible();

  const originalResponse = await reviewer.request.get(`/api/extraction/approved/${recordId}`);
  expect(originalResponse.status()).toBe(200);
  const original = await originalResponse.json();
  expect(original.version).toBe(1);
  await reviewer.goto(`/approved-extractions/${recordId}`);
  await reviewer.getByLabel("Full correction JSON (reason, strict payload and evidence)").fill(
    JSON.stringify({
      reason: "Reconfirmed evidence in immutable correction",
      payload: original.payload,
      evidence: original.evidence,
    }),
  );
  await reviewer.getByRole("button", { name: "Submit full correction" }).click();
  await expect(reviewer.getByRole("link", { name: "Open approved version 2" })).toBeVisible();
  await reviewer.getByRole("link", { name: "Open approved version 2" }).click();
  await expect(
    reviewer.getByText("Reason: Reconfirmed evidence in immutable correction"),
  ).toBeVisible();
  await reviewer.getByRole("link", { name: "Previous immutable version" }).click();
  await expect(reviewer.getByText("Reason: Verified synthetic canonical evidence")).toBeVisible();
  const historical = await reviewer.request.get(
    `/api/extraction/approved/${recordId}/versions/${original.version_id}`,
  );
  expect(historical.status()).toBe(200);
  expect(await historical.json()).toEqual(original);
  await harness("verify", "--run", runId, "--record", recordId);
});

import { execFile, spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { test, expect } from "@playwright/test";

const manifestPath = process.env.READER_SMOKE_MANIFEST!;
const seed = JSON.parse(readFileSync(manifestPath, "utf8"));
const api = process.env.READER_SMOKE_API_URL ?? "http://127.0.0.1:8218";
const root = fileURLToPath(new URL("../../..", import.meta.url));
const execute = promisify(execFile);
const token = (user: string) =>
  `mock.${Buffer.from(JSON.stringify({ org_id: seed.org, sub: user, role: "owner" })).toString("base64url")}`;
const headers = { Authorization: `Bearer ${token(seed.user)}` };
const target = seed.documents.amendment2;
const params = (pin?: string) =>
  new URLSearchParams({ as_of: seed.as_of, ...(pin ? { corpus_version_id: pin } : {}) });
const reader = (id: string, pin?: string) => `${api}/v1/documents/${id}/reader?${params(pin)}`;
const pagePath = (doc = target, pin = "") =>
  `/reader/${doc.id}?${new URLSearchParams({ as_of: seed.as_of, span: doc.span, document_version_id: doc.version, corpus_version_id: pin })}`;

// Trace only the browser context. The separate authenticated API request
// fixture is outside this trace; the browser never receives the API bearer.
test.beforeEach(async ({ context }) => {
  await context.tracing.start({ screenshots: true, snapshots: true });
});
test.afterEach(async ({ context }, info) => {
  await context.tracing.stop({ path: info.outputPath("browser-trace.zip") });
});

// Native fetch keeps authenticated requests outside Playwright's diagnostic
// steps, which otherwise retain Authorization headers on connection failures.
async function httpGet(
  url: string,
  options: { headers?: Record<string, string>; timeout?: number } = {},
) {
  try {
    const response = await fetch(url, {
      headers: options.headers,
      signal: AbortSignal.timeout(options.timeout ?? 10_000),
    });
    return { status: () => response.status, ok: () => response.ok, json: () => response.json() };
  } catch {
    throw new Error("Evidence HTTP request failed before a response");
  }
}

async function fault(action: "corrupt" | "restore") {
  // This command runs beside the API storage. Hosted execution must provide a
  // reviewed remote transport executable; no shell command strings are eval'd.
  const remote = process.env.READER_SMOKE_REMOTE_EXEC;
  const argv = [
    "-m",
    "evals.harness.reader_prod_smoke",
    action,
    "--manifest",
    manifestPath,
    "--dedicated-target",
    process.env.FEL_READER_SMOKE_TARGET!,
  ];
  await execute(remote ?? process.env.FEL_ACCEPTANCE_PYTHON ?? "python", argv, {
    cwd: root,
    env: process.env,
    timeout: 60_000,
  });
}

test("real ingestion yields stable reader selections and terminal amendment authority", async ({
  page,
  request,
}, info) => {
  for (const pin of [undefined, seed.corpus]) {
    const first = await httpGet(reader(target.id, pin), { headers });
    expect(first.status()).toBe(200);
    const body = await first.json();
    expect(body.document.document_version_id).toBe(target.version);
    expect(body.corpus_version_id).toBe(pin ?? null);
    expect(await (await httpGet(reader(target.id, pin), { headers })).json()).toEqual(body);
    const section = body.document.sections.find(
      (item: { id: string }) => item.id === target.section,
    );
    expect(section.start_char).toBeGreaterThan(0);
    const quote = section.content.slice(
      target.start_char - section.start_char,
      target.end_char - section.start_char,
    );
    expect(quote).toBe(target.quote);
    expect(`sha256:${createHash("sha256").update(quote).digest("hex")}`).toBe(target.text_hash);
  }
  const excluded = await httpGet(reader(target.id, seed.pinned_corpus), { headers });
  expect(excluded.status()).toBe(404);
  const pinnedOriginal = await httpGet(reader(seed.documents.original.id, seed.pinned_corpus), {
    headers,
  });
  expect(pinnedOriginal.status()).toBe(200);
  expect((await pinnedOriginal.json()).document.document_version_id).toBe(
    seed.documents.original.version,
  );
  await page.goto(pagePath());
  const selected = page.locator('button.span-mark[aria-pressed="true"]');
  await expect(selected).toHaveAccessibleName(`Cited source span: ${target.quote}`);
  await expect(selected).toBeVisible();
  await page.screenshot({ path: info.outputPath("valid-non-first-section.png"), fullPage: true });
  await page.goto(pagePath(seed.documents.original));
  await page.getByRole("link", { name: "Load related filings", exact: true }).click();
  await expect(page.getByText(/Related history incomplete\./)).toHaveCount(0);
  const notice = page.getByLabel("Amendment notice");
  await expect(notice).toContainText("Superseded.");
  await expect(notice.getByRole("link")).toHaveAttribute("href", new RegExp(target.id));
  for (const pin of [seed.corpus, "", seed.corpus, ""]) {
    await page.goto(pagePath(target, pin));
    await expect(page.locator('button.span-mark[aria-pressed="true"]')).toHaveAccessibleName(
      `Cited source span: ${target.quote}`,
    );
  }
});

test("future filings and absent IDs share the same not-found result; auth stays typed", async ({
  page,
  request,
}) => {
  const missing = randomUUID();
  const future = await httpGet(reader(seed.documents.future.id), { headers });
  const absent = await httpGet(reader(missing), { headers });
  expect(future.status()).toBe(404);
  expect(absent.status()).toBe(404);
  const hiddenBody = await future.json();
  const missingBody = await absent.json();
  expect(hiddenBody.error.request_id).toMatch(/^req-/);
  expect(missingBody.error.request_id).toMatch(/^req-/);
  delete hiddenBody.error.request_id;
  delete missingBody.error.request_id;
  expect(hiddenBody).toEqual(missingBody);
  for (const id of [seed.documents.future.id, missing]) {
    await page.goto(`/reader/${id}?as_of=${encodeURIComponent(seed.as_of)}&corpus_version_id=`);
    await expect(page.getByText("404", { exact: true })).toBeVisible();
    await expect(page.locator("button.span-mark")).toHaveCount(0);
  }
  for (const [auth, status] of [
    [undefined, 401],
    ["Bearer invalid", 401],
    [`Bearer ${token(seed.denied_user)}`, 403],
  ] as const) {
    const result = await httpGet(reader(target.id), {
      headers: auth ? { Authorization: auth } : {},
    });
    expect(result.status()).toBe(status);
    expect((await result.json()).error.code).toBeTruthy();
  }
});

test("canonical byte corruption fails closed and is restored", async ({ page }, info) => {
  if (process.env.READER_SMOKE_HOSTED === "1" && !process.env.READER_SMOKE_REMOTE_EXEC) {
    throw new Error("Hosted corruption requires the dedicated API/storage remote executor");
  }
  try {
    await fault("corrupt");
    const response = await httpGet(reader(target.id), { headers });
    expect(response.status()).toBe(500);
    expect((await response.json()).error.code).toBe("INTEGRITY_ERROR");
    await page.goto(pagePath());
    await expect(page.getByRole("alert", { name: "Evidence response rejected" })).toContainText(
      "No verified quote is shown.",
    );
    await expect(page.locator("button.span-mark")).toHaveCount(0);
    await page.screenshot({ path: info.outputPath("invalid-canonical-blob.png"), fullPage: true });
  } finally {
    await fault("restore");
  }
  const recovered = await httpGet(reader(target.id), { headers });
  expect(recovered.status()).toBe(200);
});

test("real dedicated API outage shows unavailable and recovers", async ({
  page,
  request,
}, info) => {
  const hosted = process.env.READER_SMOKE_HOSTED === "1";
  const remote = process.env.READER_SMOKE_REMOTE_EXEC;
  if (hosted && !remote) throw new Error("Hosted outage requires dedicated service control");
  async function control(action: "stop" | "start") {
    await execute(
      remote ?? process.env.FEL_ACCEPTANCE_PYTHON ?? "python",
      [
        "-m",
        "evals.harness.reader_prod_smoke_service",
        action,
        "--manifest",
        manifestPath,
        "--dedicated-target",
        process.env.FEL_READER_SMOKE_TARGET!,
      ],
      { cwd: root, env: process.env, timeout: 60_000 },
    );
  }
  try {
    await control("stop");
    let observed: number | "connection-failed" = 200;
    await expect
      .poll(async () => {
        try {
          observed = (await httpGet(`${api}/health`, { timeout: 5000 })).status();
        } catch {
          observed = "connection-failed";
        }
        return observed;
      })
      .not.toBe(200);
    if (hosted) expect([502, 503]).toContain(observed);
    await info.attach("outage-observation.json", {
      body: JSON.stringify({ hosted, observed }),
      contentType: "application/json",
    });
    await page.goto(pagePath());
    await expect(page.getByRole("alert", { name: "Evidence service unavailable" })).toBeVisible();
    await expect(page.getByText("404", { exact: true })).toHaveCount(0);
    await expect(page.locator("button.span-mark")).toHaveCount(0);
  } finally {
    await control("start");
    await expect
      .poll(async () => {
        try {
          return (await httpGet(`${api}/health`)).status();
        } catch {
          return 0;
        }
      })
      .toBe(200);
  }
  await page.goto(pagePath());
  await expect(page.locator('button.span-mark[aria-pressed="true"]')).toHaveAccessibleName(
    `Cited source span: ${target.quote}`,
  );
});

test("real upstream authentication failures remain typed in the browser", async ({
  page,
  request,
}) => {
  const hosted = process.env.READER_SMOKE_HOSTED === "1";
  const variants = [
    {
      port: 3219,
      token: "invalid",
      heading: "Sign in required",
      url: process.env.READER_SMOKE_UNAUTHORIZED_WEB_URL,
    },
    {
      port: 3220,
      token: token(seed.denied_user),
      heading: "Access denied",
      url: process.env.READER_SMOKE_FORBIDDEN_WEB_URL,
    },
  ];
  for (const variant of variants) {
    if (hosted && !variant.url?.startsWith("https://"))
      throw new Error("Hosted auth UI variants must be explicit dedicated HTTPS deployments");
    const child = hosted
      ? undefined
      : spawn("pnpm", ["exec", "next", "start", "--port", String(variant.port)], {
          cwd: `${root}/apps/web`,
          stdio: "ignore",
          detached: true,
          env: {
            ...process.env,
            FEL_EVIDENCE_SOURCE: "http",
            FEL_API_BASE_URL: api,
            FEL_API_BEARER_TOKEN: variant.token,
            FEL_ENTITY_IDS: seed.entity,
            FEL_AS_OF: seed.as_of,
          },
        });
    const url = variant.url ?? `http://127.0.0.1:${variant.port}`;
    try {
      await expect
        .poll(async () => {
          if (child && child.exitCode !== null)
            throw new Error("Owned auth web service failed startup");
          try {
            return (await httpGet(`${url}${pagePath()}`)).ok();
          } catch {
            return false;
          }
        })
        .toBe(true);
      await page.goto(`${url}${pagePath()}`);
      await expect(page.getByRole("alert", { name: variant.heading })).toBeVisible();
      await expect(page.getByText("404", { exact: true })).toHaveCount(0);
      await expect(page.locator("button.span-mark")).toHaveCount(0);
    } finally {
      if (child?.pid && child.exitCode === null) {
        process.kill(-child.pid, "SIGTERM");
        await new Promise<void>((resolve) => child.once("exit", () => resolve()));
      }
    }
  }
});

test("HTTP transport failure diagnostics contain no bearer", async () => {
  await expect(httpGet("http://127.0.0.1:1", { headers })).rejects.toThrow(
    "Evidence HTTP request failed before a response",
  );
});

// Dependency audit against npm's bulk advisory endpoint.
// Replaces `pnpm audit`: npm retired the audits/quick endpoint (HTTP 410,
// 2026-07) and pnpm (<= 11.13) still calls it. Reads every resolved
// package@version from pnpm-lock.yaml and fails on any advisory affecting
// a resolved version — same gate semantics as the old `pnpm audit`.
//
// A triage allowlist (audit-allowlist.json) suppresses individual advisories
// that have no non-breaking fix yet, but fails closed: an expired or malformed
// entry breaks the gate rather than silently disabling it. See evaluate().
// Transient registry failures (HTTP 429/502/503/504 and network errors) are
// retried up to three attempts; exhausted retries still fail closed. A 410 is
// not retried — that is the retired-endpoint contract break this script exists
// to replace.
import { readFileSync } from "node:fs";
import { setTimeout as sleepMs } from "node:timers/promises";
import { pathToFileURL } from "node:url";

// The GitHub advisory id (GHSA-...) is what an allowlist entry keys on. The
// bulk endpoint returns it inconsistently across packages, so probe the fields
// it may appear in before falling back to extracting it from the advisory url.
function ghsaId(advisory) {
  if (typeof advisory.github_advisory_id === "string") return advisory.github_advisory_id;
  const fromUrl = (advisory.url ?? "").match(/GHSA-\w{4}-\w{4}-\w{4}/i);
  if (fromUrl) return fromUrl[0];
  return typeof advisory.id === "string" && advisory.id.startsWith("GHSA-") ? advisory.id : null;
}

// A fail-closed result carrying a config/response error (exit 2), no findings.
const empty = (configError) => ({
  ok: false,
  blocking: [],
  allowlisted: [],
  expired: [],
  malformed: [],
  configError,
});

// Pure gate evaluation. `advisories` is the bulk endpoint response (an object
// mapping package name -> array of advisory objects); `allowlist` is the parsed
// audit-allowlist.json array; `now` is the reference Date for expiry checks.
// Returns the gate outcome without printing or exiting so it stays testable.
export function evaluate(advisories, allowlist, now) {
  // Fail closed on a malformed advisory response. The bulk endpoint returns an
  // object map (package -> advisory[]); a null / array / primitive body means
  // the API contract broke or the body was truncated — that is NOT "zero
  // advisories", so it must not read as a clean pass.
  if (advisories === null || typeof advisories !== "object" || Array.isArray(advisories)) {
    return empty("malformed advisory response body");
  }
  // Fail closed on a non-array allowlist (broken config) instead of crashing on
  // a non-iterable in the loop below.
  if (allowlist != null && !Array.isArray(allowlist)) {
    return empty("audit-allowlist.json is not an array");
  }

  const malformed = [];
  const active = []; // well-formed, unexpired entries usable for suppression
  const expired = [];
  for (const entry of allowlist ?? []) {
    const missing = ["id", "package", "reason", "reviewBy"].filter((k) => !entry?.[k]);
    const reviewBy = new Date(entry?.reviewBy);
    if (missing.length > 0 || Number.isNaN(reviewBy.getTime())) {
      malformed.push({ entry, missing });
      continue;
    }
    if (reviewBy < now) {
      expired.push({ id: entry.id, package: entry.package, reviewBy: entry.reviewBy });
      continue;
    }
    active.push(entry);
  }

  const allowlisted = [];
  const blocking = [];
  for (const [name, list] of Object.entries(advisories ?? {})) {
    for (const advisory of list) {
      const id = ghsaId(advisory);
      const match = active.find((e) => e.id === id && e.package === name);
      if (match) {
        allowlisted.push({ name, id, reviewBy: match.reviewBy, reason: match.reason });
      } else {
        blocking.push({ name, id, advisory });
      }
    }
  }

  const ok = blocking.length === 0 && expired.length === 0 && malformed.length === 0;
  return { ok, blocking, allowlisted, expired, malformed, configError: null };
}

const BULK_ADVISORY_URL = "https://registry.npmjs.org/-/npm/v1/security/advisories/bulk";
const TRANSIENT_ADVISORY_STATUS = new Set([429, 502, 503, 504]);
const ADVISORY_ATTEMPTS = 3;

// POST the lockfile package map to npm's bulk advisory endpoint. Transient
// registry failures (429/502/503/504) are retried; a 410 or other 4xx is not —
// that is a contract break, not a blip. Exhausted retries still fail closed.
export async function fetchBulkAdvisories(
  payload,
  {
    fetchImpl = fetch,
    sleep = (ms) => sleepMs(ms),
    attempts = ADVISORY_ATTEMPTS,
    log = console.error,
  } = {},
) {
  const init = {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  };
  let lastStatus = 0;
  for (let i = 1; i <= attempts; i++) {
    let res;
    try {
      res = await fetchImpl(BULK_ADVISORY_URL, init);
    } catch (err) {
      if (i === attempts) throw err;
      log(
        `audit-bulk: bulk advisory endpoint request failed — ${err.message}; retrying (${i}/${attempts})`,
      );
      await sleep(1000 * 2 ** (i - 1));
      continue;
    }
    if (res.ok) return await res.json();
    lastStatus = res.status;
    if (!TRANSIENT_ADVISORY_STATUS.has(res.status) || i === attempts) break;
    log(`audit-bulk: bulk advisory endpoint responded ${res.status}; retrying (${i}/${attempts})`);
    await sleep(1000 * 2 ** (i - 1));
  }
  const err = new Error(`bulk advisory endpoint responded ${lastStatus}`);
  err.status = lastStatus;
  throw err;
}

async function main() {
  const lock = readFileSync("pnpm-lock.yaml", "utf8");
  const section = lock.split(/^packages:$/m)[1]?.split(/^\S/m)[0] ?? "";
  const pkgs = {};
  for (const m of section.matchAll(/^ {2}'?((?:@[^@'\s/]+\/)?[^@'\s/]+)@([^'():\s]+)'?:$/gm)) {
    (pkgs[m[1]] ??= new Set()).add(m[2]);
  }
  const names = Object.keys(pkgs);
  if (names.length === 0) {
    console.error("audit-bulk: no packages parsed from pnpm-lock.yaml");
    process.exit(2);
  }
  const body = Object.fromEntries(names.map((n) => [n, [...pkgs[n]]]));
  let advisories;
  try {
    advisories = await fetchBulkAdvisories(body);
  } catch (err) {
    const detail =
      err.status != null
        ? `bulk advisory endpoint responded ${err.status}`
        : `bulk advisory endpoint request failed — ${err.message}`;
    console.error(`audit-bulk: ${detail}`);
    process.exit(2);
  }

  let allowlist;
  try {
    allowlist = JSON.parse(readFileSync(new URL("audit-allowlist.json", import.meta.url), "utf8"));
  } catch (err) {
    console.error(`audit-bulk: cannot read audit-allowlist.json — ${err.message}`);
    process.exit(2);
  }

  const { ok, blocking, allowlisted, expired, malformed, configError } = evaluate(
    advisories,
    allowlist,
    new Date(),
  );

  // A malformed response body or a non-array allowlist is a broken-config
  // failure (exit 2), not a clean pass and not a live-advisory failure.
  if (configError) {
    console.error(`audit-bulk: ${configError}`);
    process.exit(2);
  }

  for (const a of allowlisted) {
    console.log(`allowlisted until ${a.reviewBy}: ${a.id} ${a.name} — ${a.reason}`);
  }
  for (const m of malformed) {
    console.error(
      `audit-bulk: malformed allowlist entry (missing ${m.missing.join(", ") || "valid reviewBy"}): ${JSON.stringify(m.entry)}`,
    );
  }
  for (const e of expired) {
    console.error(
      `audit-bulk: audit allowlist entry expired, re-review required: ${e.id} ${e.package} (reviewBy ${e.reviewBy})`,
    );
  }
  for (const { name, advisory } of blocking) {
    console.error(
      `${advisory.severity ?? "unknown"}: ${name} ${advisory.vulnerable_versions ?? ""} — ${advisory.title ?? ""} (${advisory.url ?? ""})`,
    );
  }

  if (ok) {
    console.log(
      `No blocking vulnerabilities found (audited ${names.length} packages via bulk advisory endpoint; ${allowlisted.length} allowlisted)`,
    );
    return;
  }
  if (blocking.length > 0) {
    console.error(`audit-bulk: ${blocking.length} package(s) with known vulnerabilities`);
  }
  // A malformed allowlist is a broken-config failure (exit 2); an expired entry
  // or a live advisory is a security-gate failure (exit 1).
  process.exit(malformed.length > 0 ? 2 : 1);
}

// Run main() only when invoked as a script. Guard against an undefined
// argv[1] (e.g. `node --eval`, which would otherwise crash pathToFileURL).
const invokedPath = process.argv[1];
if (invokedPath && import.meta.url === pathToFileURL(invokedPath).href) {
  await main();
}

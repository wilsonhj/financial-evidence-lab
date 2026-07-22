// Dependency audit against npm's bulk advisory endpoint.
// Replaces `pnpm audit`: npm retired the audits/quick endpoint (HTTP 410,
// 2026-07) and pnpm (<= 11.13) still calls it. Reads every resolved
// package@version from pnpm-lock.yaml and fails on any advisory affecting
// a resolved version — same gate semantics as the old `pnpm audit`.
//
// A triage allowlist (audit-allowlist.json) suppresses individual advisories
// that have no non-breaking fix yet, but fails closed: an expired or malformed
// entry breaks the gate rather than silently disabling it. See evaluate().
import { readFileSync } from "node:fs";
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

// Pure gate evaluation. `advisories` is the bulk endpoint response (an object
// mapping package name -> array of advisory objects); `allowlist` is the parsed
// audit-allowlist.json array; `now` is the reference Date for expiry checks.
// Returns the gate outcome without printing or exiting so it stays testable.
export function evaluate(advisories, allowlist, now) {
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
  return { ok, blocking, allowlisted, expired, malformed };
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
  const res = await fetch("https://registry.npmjs.org/-/npm/v1/security/advisories/bulk", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    console.error(`audit-bulk: bulk advisory endpoint responded ${res.status}`);
    process.exit(2);
  }
  const advisories = await res.json();

  let allowlist;
  try {
    allowlist = JSON.parse(readFileSync(new URL("audit-allowlist.json", import.meta.url), "utf8"));
  } catch (err) {
    console.error(`audit-bulk: cannot read audit-allowlist.json — ${err.message}`);
    process.exit(2);
  }

  const { ok, blocking, allowlisted, expired, malformed } = evaluate(
    advisories,
    allowlist,
    new Date(),
  );

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

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}

// Dependency audit against npm's bulk advisory endpoint.
// Replaces `pnpm audit`: npm retired the audits/quick endpoint (HTTP 410,
// 2026-07) and pnpm (<= 11.13) still calls it. Reads every resolved
// package@version from pnpm-lock.yaml and fails on any advisory affecting
// a resolved version — same gate semantics as the old `pnpm audit`.
import { readFileSync } from "node:fs";

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
const hits = Object.entries(advisories);
if (hits.length > 0) {
  for (const [name, list] of hits) {
    for (const a of list) {
      console.error(
        `${a.severity ?? "unknown"}: ${name} ${a.vulnerable_versions ?? ""} — ${a.title ?? ""} (${a.url ?? ""})`,
      );
    }
  }
  console.error(`audit-bulk: ${hits.length} package(s) with known vulnerabilities`);
  process.exit(1);
}
console.log(`No known vulnerabilities found (audited ${names.length} packages via bulk advisory endpoint)`);

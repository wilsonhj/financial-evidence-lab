# SEC golden-file fixture manifest (EXT-2, issue #72)

Curated manifest of parser-stressing SEC filings across the canonical
20-issuer cohort (`evals/datasets/issuer-cohort.json`), feeding M1
ingestion test-writing (T0103 / T0111).

## STATUS: BLOCKED — zero verified entries in this checkpoint

**`manifest.jsonl` and `excerpts/` are intentionally absent.** The EXT-2
integrity rule is absolute: every accession, URL, date, and sha256 must
come from data actually fetched from SEC EDGAR, and every URL must be
verified to resolve (HTTP 200) at authoring time. In the authoring
session, ALL outbound HTTPS egress was denied at the gateway — CONNECT
to `data.sec.gov`, `www.sec.gov`, and `efts.sec.gov` was rejected, and a
control fetch of `example.com` failed identically, confirming a
session-wide policy denial rather than SEC-side throttling. Zero entries
could be verified; per the brief ("do NOT fabricate"), nothing was
authored by hand. **Shortfall: 40/40 entries.**

### Blocker evidence (captured 2026-07-13)

```text
$ curl -sS -o /dev/null -w "%{http_code}" --cacert /root/.ccr/ca-bundle.crt \
    -H "User-Agent: financial-evidence-lab research (sordidsunday@icloud.com)" \
    https://data.sec.gov/submissions/CIK0001108524.json
curl: (56) CONNECT tunnel failed, response 403
000

$ curl -sS http://127.0.0.1:38655/__agentproxy/status | jq '.recentRelayFailures[-1]'
{
  "ts": "2026-07-13T00:25:59.885Z",
  "kind": "connect_rejected",
  "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)",
  "host": "data.sec.gov:443"
}
```

Attempted remedies, all failed the same way: `curl` with the proxy CA
bundle against all three SEC hosts (CONNECT 403 from the egress
gateway); the harness WebFetch tool against the same URLs and against
`example.com` (HTTP 403 for all). The egress-proxy runbook instructs
reporting policy denials rather than routing around them, and no mirror
or third-party dataset can satisfy the "URL resolves at authoring time"
and "sha256 of actually fetched bytes" requirements — so no workaround
preserves integrity.

### Exact next action

1. Grant a rerun session egress to `www.sec.gov:443` and
   `data.sec.gov:443`.
2. Execute the pipeline specified below (it is fully deterministic given
   the cohort file), regenerate `manifest.jsonl` + `excerpts/`, and
   commit them together with the pipeline script.
3. Run the validation gate (bottom of this file), paste its output into
   the PR, and mark the PR ready for review.

## Selection methodology (ready to execute once egress is granted)

**Inputs.** The canonical cohort file (read-only) and, per issuer, the
full EDGAR submissions index
`https://data.sec.gov/submissions/CIK{10-digit}.json`, following the
`filings.files` pagination blocks so pre-2018 history is included. All
requests send `User-Agent: financial-evidence-lab research
(sordidsunday@icloud.com)` and are rate-limited to **< 2 req/s** (SEC
fair-access ceiling is 10 req/s; stay far below).

**Selection, per issuer, in priority order** (target 40–60 total,
deliberately over-sampling ugly cases):

1. **Amendments** — every `10-K/A` / `10-Q/A` on file
   (restatement/versioning pressure).
2. **Restatement triggers** — every `8-K` whose `items` field includes
   `4.02` (non-reliance on previously issued financial statements).
3. **Fiscal-year transition reports** — `10-KT` / `10-QT` (+ `/A`),
   which stress fiscal-period normalization.
4. **Pre-2018 filings** — the two oldest `10-K`/`10-Q` per issuer
   (legacy, non-iXBRL formatting); cohort-wide floor of 3.
5. **Recent periodic reports** — the latest `10-K` and latest `10-Q`
   per issuer for iXBRL-era coverage, capped so the total stays <= 60.

De-duplicate by accession, keep only rows with a `primaryDocument`, and
build each URL as
`https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession-without-dashes}/{primaryDocument}`.

**Verification per entry.** Fetch each selected primary document exactly
once. Emit a manifest line only on HTTP 200; compute `sha256` from the
fetched bytes. If an issuer lacks a category (e.g. no amendments on
file), record the gap here rather than substituting issuers — cohort
changes are an integration-lead decision.

**Stress features are detected in the fetched bytes, never asserted:**

| feature | detection |
| --- | --- |
| `ixbrl_continuation` | `<ix:continuation` present |
| `ixbrl_dimensional_facts` | `<xbrldi:explicitMember` or `<xbrldi:typedMember` |
| `nested_tables` | a `<table>` opened before the enclosing `<table>` closes |
| `rotated_tables` | `writing-mode:` or `transform: rotate` in styles |
| `unusual_scale_markers` | "in thousands/millions, except …" variants |
| `multi_currency` | `€`/`£`/`¥` or `iso4217:` non-USD unit refs |
| `legacy_html_no_ixbrl` | no `<ix:` tags in an HTML primary document |
| `amended_filing` | form ends `/A` (from the fetched index) |
| `restatement_nonreliance` | selected via 8-K `items` containing `4.02` |
| `fiscal_year_transition` | form is `10-KT`/`10-QT` (+ `/A`) |
| `pre_2018_formatting` | `filingDate` < 2018-01-01 (from the fetched index) |

Eleven possible values — comfortably above the required >= 8 distinct.

## Manifest schema

One JSON object per line in `manifest.jsonl` (JSONL, not a JSON array):

```json
{
  "id": "FX-0001",
  "issuer": {"ticker": "CRM", "cik": "0001108524"},
  "form": "10-K",
  "accession": "0001108524-24-000012",
  "filed_at": "2024-03-06",
  "primary_document": "crm-20240131.htm",
  "url": "https://www.sec.gov/Archives/edgar/data/1108524/000110852424000012/crm-20240131.htm",
  "sha256": "<64 hex chars of the primary document bytes>",
  "why_selected": "…",
  "stress_features": ["nested_tables", "ixbrl_continuation"]
}
```

## Excerpts

Up to 10 fixtures with detected `nested_tables` get a verbatim byte
slice (< 50 KB) under `excerpts/`, each prefixed with a comment header
recording the source URL, the exact byte range within the full
document, and the full document's sha256 — so every excerpt can be
re-verified against upstream bytes.

## How M1 ingestion consumes this manifest

- **Do not** look for full filings in this repository — they are never
  committed. Iterate `manifest.jsonl` line-by-line (`json.loads` per
  line).
- Fetch `url` with a compliant User-Agent and conservative rate limit.
- **Verify `sha256` of the fetched bytes before parsing.** A mismatch
  means EDGAR re-disseminated the document; treat the fixture as stale,
  fail the test loudly, and regenerate the manifest — never silently
  accept drifted bytes as golden.
- Use `stress_features` to parameterize parser test cases (e.g. run the
  table-extraction suite over every fixture tagged `nested_tables`).
- `accession` + `filed_at` are authoritative for temporal-cutoff tests;
  `filed_at` is the EDGAR `filingDate` (ET, date-only).
- Excerpts are for human inspection and fast unit tests only; byte
  offsets in their headers refer to the full upstream document.

## Validation gate (must pass before the PR leaves draft)

```bash
python3 - <<'EOF'
import json, re, pathlib
lines = pathlib.Path("manifest.jsonl").read_text().splitlines()
feats = set()
for i, l in enumerate(lines, 1):
    o = json.loads(l)
    assert re.fullmatch(r"[0-9a-f]{64}", o["sha256"]), i
    for k in ("id", "issuer", "form", "accession", "filed_at",
              "primary_document", "url", "why_selected", "stress_features"):
        assert k in o, (i, k)
    feats.update(o["stress_features"])
assert len(lines) >= 40 and len(feats) >= 8, (len(lines), len(feats))
for p in pathlib.Path("excerpts").glob("*"):
    assert p.stat().st_size < 50_000, p
print(f"OK: {len(lines)} entries, {len(feats)} distinct stress features")
EOF
```

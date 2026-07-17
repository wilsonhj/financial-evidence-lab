# Reader cross-stack verification (issue #96 / READER-CROSS-STACK)

Child package **E** of #87. Independent verification that the ADR-0005
composite reader holds end-to-end after READER-API and READER-WEB-HTTP merge.

## Mock-first policy

**CI and local default path require no credentials and no hosted services.**

| Mode | Trigger | What runs |
|---|---|---|
| **mock** (default) | always | Committed fixtures under `fixtures/` + pure Python ADR-0005 / citation-integrity / HttpEvidenceSource policy checks in `evals/harness/reader_cross_stack.py` |
| **stack** (optional) | `TEST_DATABASE_URL` set to a disposable migrated Postgres | Seeds a synthetic corpus and hits the real FastAPI `/v1/documents/{id}/reader` via TestClient |
| **hosted smoke** | separately authorized | Production worker → API → Next.js HTTP mode. Out of scope for this package until credentials are authorized |

Fixtures are labeled synthetic / derived from the frozen
`packages/contracts/fixtures/reader-response.json` contract artifact. They are
not live EDGAR bytes and never substitute for a hosted smoke.

## Required flow (hosted / full stack)

```text
committed synthetic filing
  -> real worker consumer
  -> Postgres
  -> authenticated FastAPI
  -> HttpEvidenceSource
  -> production Next.js reader
```

This package owns only `evals/**`. Product defects discovered in `apps/**`
must stop and escalate — they are not patched here.

The mock and FastAPI paths are a partial, credential-free gate. They do not
complete issue #96 by themselves: only the separately authorized production
smoke can verify the required worker -> API -> `HttpEvidenceSource` -> Next.js
path and provide the browser/log/trace artifacts.

## Acceptance mapping

| Acceptance bullet | Mock path | Stack path (`TEST_DATABASE_URL`) | Deferred |
|---|---|---|---|
| Document ID ≠ selected version ID | yes | yes | — |
| Exact-cutoff visible; future hidden | partial (fixture cutoff invariants) | yes | — |
| Pinned / unpinned selection match ADR-0005 | yes | yes | — |
| Non-first-section citation hash-verifies | yes | yes | browser highlight screenshot |
| Corrupt range/hash → integrity alert, no quote | yes (client verifier) | yes (API `INTEGRITY_ERROR`) | UI alert screenshot |
| Facts resolve to same-version spans | yes | yes | — |
| Amendments → terminal authoritative filing | yes (port of web amendment rules) | partial | — |
| 401/403/5xx never false 404 | yes (mock HTTP transport) | yes | — |
| HTTP mode cannot fall back to fixtures | yes (policy harness) | — | — |
| Repeated request → identical selection | yes | yes | — |
| Full CI + production smoke + artifacts | CI mock+stack | — | hosted smoke |
| Independent `/code-review` … `/pr-review` | — | — | post-PR process |

## Layout

```text
evals/datasets/reader-cross-stack/
  README.md
  scenarios.json
  fixtures/
    latest_parsed_ok.json
    corpus_pinned_ok.json
    integrity_corrupt_hash.json
    integrity_out_of_range.json
    amendment_chain_documents.json
    error_envelopes.json
```

## Running

```bash
# Mock-first (no DB, no credentials)
PYTHONPATH=evals:workers/src:packages/providers:apps/api \
  pytest evals/tests/test_reader_cross_stack.py -q

# Optional stack path
TEST_DATABASE_URL="postgresql://.../fel_test" \
  PYTHONPATH=evals:workers/src:packages/providers:apps/api \
  pytest evals/tests/test_reader_cross_stack.py -q
```

Refs: ADR-0005, issue #96.

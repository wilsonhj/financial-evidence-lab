# @fel/web — Evidence Reader (T0110)

Next.js (App Router) front end for browsing the evidence corpus.

## Run

```sh
pnpm --filter @fel/web dev     # http://localhost:3000
pnpm --filter @fel/web build   # production build (Turbopack)
pnpm --filter @fel/web start   # serve the production build
pnpm --filter @fel/web test    # vitest unit suites
pnpm --filter @fel/web typecheck
```

`GET /api/health` mirrors the API health contract for platform probes.

## What the reader does (spec 8.3)

- Filing outline / section navigation (keyboard: ArrowUp/Down, Home/End, Enter).
- Rendered document content synchronized with extracted sections.
- Source-span citation highlights (background + dotted underline + dagger glyph
  — never color alone); clicking a span focuses the facts it supports.
- Fact panel: raw cited source text, normalized value, unit, scale, period,
  dimensions, reported/derived basis, confidence.
- Duplicate-fact comparison with inconsistent values flagged (scale-aware,
  string-decimal comparison — no binary floats, spec 11.4).
- Amendment/restatement indicators linking 10-Q and 10-Q/A versions.
- Analyst notes attached to sections or spans in client-side state; notes never
  modify source content (invariant enforced by `src/lib/notes.test.ts`).

## Data access

The UI talks only to the `EvidenceSource` interface (`src/lib/data`). Runtime
selection is explicit and server-only:

- `FEL_EVIDENCE_SOURCE=fixture` serves the committed synthetic
  filing in `src/lib/fixtures/synthetic-filing.ts` — a fictional issuer with a
  10-Q, a restating 10-Q/A, a conflicting duplicate fact pair, a consistent
  duplicate pair, and a dimensioned segment fact. Fixture spans and facts are
  validated against the frozen @fel/contracts JSON Schemas, and every span's
  `text_hash` is recomputed in tests.
- `FEL_EVIDENCE_SOURCE=http` uses ADR-0005's authenticated composite reader
  endpoint. It requires `FEL_API_BASE_URL`, `FEL_API_BEARER_TOKEN`, and the
  comma-separated `FEL_ENTITY_IDS` used by the filing list. Optional
  `FEL_AS_OF` and `FEL_CORPUS_VERSION_ID` pin the temporal/corpus scope. The
  bearer token is read only by `src/lib/data/server.ts`; do not use a
  `NEXT_PUBLIC_` variable for it.

No mode is inferred. Missing or incomplete configuration fails closed and
never falls back to fixtures. Both the filing list and reader routes are
dynamic and issue uncached requests.

`DocumentMeta`, `SourceSpan`, `FinancialFact`, and `ReaderResponse` are
generated from `@fel/contracts` and never redefined here. The HTTP adapter
validates target identity, effective cutoff/corpus scope, selected-version
consistency, same-entity siblings, and fact/span references before the reader
can render. Target citations are then hash-verified against canonical-global
section offsets and fail closed on mismatch.

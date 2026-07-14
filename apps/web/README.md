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

The UI talks only to the `EvidenceSource` interface (`src/lib/data`):

- `FixtureEvidenceSource` (current binding) serves the committed synthetic
  filing in `src/lib/fixtures/synthetic-filing.ts` — a fictional issuer with a
  10-Q, a restating 10-Q/A, a conflicting duplicate fact pair, a consistent
  duplicate pair, and a dimensioned segment fact. Fixture spans and facts are
  validated against the frozen @fel/contracts JSON Schemas, and every span's
  `text_hash` is recomputed in tests.
- `HttpEvidenceSource` is stubbed against the frozen OpenAPI document
  endpoints; section/span/fact listing fills in when the ingestion API
  (M1-INGESTION) publishes those contracts. Swap the binding in
  `src/lib/data/index.ts`.

Contract shapes (`DocumentMeta`, `SourceSpan`, financial fact) are consumed
from `@fel/contracts` and never redefined here (see `src/lib/contracts.ts`).

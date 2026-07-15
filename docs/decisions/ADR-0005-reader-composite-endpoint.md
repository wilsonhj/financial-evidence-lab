# ADR-0005: Composite version-pinned evidence reader endpoint

Status: Proposed
Date: 2026-07-15
Occasioned by: issue #87 (M1-READER-INTEGRATION) / child issue #89 (READER-CONTRACT)

## Decision

Add one authenticated composite read endpoint to the v1 surface as an
additive minor contract change (OpenAPI `info.version` 0.1.0 → 0.2.0):

```http
GET /v1/documents/{documentId}/reader?as_of=&corpus_version_id=
```

The endpoint returns, in a single snapshot-consistent response, everything
the production web reader needs to render a document and compare it against
its sibling filings: the effective cutoff, the (possibly null) corpus pin,
the target document with exactly one selected parsed
`document_version_id`, its sections (canonical **global** character
offsets plus sliced content), the source spans and normalized facts of
exactly that selected version, and fact-level evidence for every
same-entity sibling document visible at the cutoff.

The response schema is `ReaderResponse` in
`packages/contracts/openapi/openapi.yaml`, with a canonical JSON Schema at
`packages/contracts/schemas/reader-response.schema.json`
(`$id https://contracts.fel.dev/schemas/reader-response/v1`) and a
CI-validated fixture `packages/contracts/fixtures/reader-response.json`.

The frozen `financial-fact/v1` JSON Schema joins the OpenAPI component
surface as `components.schemas.FinancialFact` via a file `$ref` to
`schemas/financial-fact.schema.json`, so the generated TypeScript client
exposes the fact type and `apps/web` can delete its hand-maintained mirror
(`apps/web/src/lib/contracts.ts`, `TODO(contract-change)`). The `$ref`
approach means the OpenAPI fact component **cannot drift** from the frozen
JSON Schema: there is exactly one definition.

## 1. Cutoff semantics (`as_of`)

- The reader **always** operates under a cutoff. If `as_of` is provided it
  must be an RFC 3339 timestamp with an explicit UTC offset
  (timezone-naive values are rejected with 422). If it is omitted, the
  server uses the request time. The response's required `as_of` field is
  the **effective** cutoff the server actually enforced, normalized to
  UTC; clients must treat it, not their request parameter, as
  authoritative.
- The boundary is **inclusive**: a document is visible iff
  `published_at <= as_of`. This matches the existing
  `GET /v1/entities/{entityId}/documents` filter.
- The cutoff is enforced server-side on the **target document itself**,
  not only on listings. A direct URL to a document whose `published_at`
  is after the cutoff returns a 404 that is **byte-for-byte identical in
  status, error `code` (`NOT_FOUND`), `message`, and `details` shape** to
  the 404 for a document id that does not exist. The response must not
  provide any oracle (timing aside) distinguishing "hidden by cutoff"
  from "never existed"; in particular `TEMPORAL_SCOPE_VIOLATION` is
  **not** used here, because it would leak existence.
- The cutoff also bounds nested evidence: every sibling document in the
  response satisfies `published_at <= as_of`. Sections, spans, and facts
  are not independently time-filtered — they belong to the selected
  parsed version of a visible document, and version selection (section 3)
  is where parse-state filtering happens.

## 2. Authentication and error envelopes

- Authentication and org membership remain mandatory, exactly as for the
  existing corpus reads (ADR-0004 layer 2): anonymous → 401, authenticated
  non-member → 403, both with the frozen typed error envelope
  (`error.schema.json` / `components.schemas.Error`).
- 401, 403, 409, 422, and 5xx are **never** converted to 404 and never
  rendered as not-found. Only the two cases in section 1 (missing target,
  cutoff-hidden target) and the corpus-pin cases in section 3 produce 404.
- The endpoint declares a `bearerAuth` (HTTP bearer) security scheme in
  the OpenAPI document. Adding `components.securitySchemes` is additive;
  existing operations are unchanged (their enforcement is already
  server-side and documented by ADR-0004).

## 3. Deterministic version selection

Exactly one parsed `document_version_id` is selected per returned document
(target and every sibling), under one of two policies, echoed in the
response's required `selection_policy` field:

**`corpus_pinned`** — when `corpus_version_id` is supplied:

- The corpus version must exist and have status `active` or `superseded`.
  `draft` corpus versions are not addressable by the reader (publication
  is atomic; drafts are not published evidence). An unknown or draft
  `corpus_version_id` returns 404 with `details.resource =
  "corpus_version"` (corpus versions are public metadata, ADR-0004, so
  this is not an information leak).
- For each document, the selected version is the one pinned by
  `corpus_version_documents` for that corpus version. A visible document
  with **no** pinned parsed version is excluded from `siblings`; if the
  **target** has no pinned parsed version, the reader returns the same
  404 as a missing target (within that corpus snapshot the document has
  no readable form).
- If data corruption ever yields more than one pinned parsed version of
  the same document in one corpus version, the server must fail closed
  with a 5xx typed envelope (`code = "INTEGRITY_ERROR"`), never pick one
  arbitrarily.

**`latest_parsed`** — when `corpus_version_id` is absent:

- Candidate set: `document_versions` rows of the document with
  `status = 'parsed'`. Quarantined versions are never candidates.
- The selected version is the **maximum of the candidate set under the
  following total order** (equivalently, `ORDER BY` these keys and take
  the first row):

  1. `created_at` **descending** — a later parse supersedes an earlier
     one (re-parses with newer toolchains produce newer rows; rows are
     immutable, so `created_at` is stable);
  2. `parser_version` **descending**, compared **bytewise** (PostgreSQL
     `COLLATE "C"`), as a tie-break within identical timestamps;
  3. `normalizer_version` **descending**, bytewise, same rationale;
  4. `id` (UUID) **descending**, compared bytewise on the canonical
     lowercase hex text form — a final tie-break that makes the order
     **total**, since `id` is unique.

  Bytewise text comparison is chosen over semver parsing because
  `parser_version` / `normalizer_version` are free-form text columns; the
  compare is only a tie-break within a single `created_at` instant, and
  bytewise collation is deterministic across locales and platforms.
  `(document_id, parser_version, normalizer_version)` is unique, so keys
  2–4 fire only for genuinely concurrent re-parses with distinct
  toolchain versions.
- A target document with no parsed version at all returns the same 404
  as a missing target (there is nothing readable; distinguishing "exists
  but unparsed" would add an existence oracle for quarantined content).
  Sibling documents with no parsed version are excluded.

Both policies are pure functions of the database state and the request
parameters: the same request against the same corpus state always selects
the same version. Document id and version id are distinct identifiers and
are never compared with each other.

## 4. Offset coordinate system

- Source-span `start_char` / `end_char` are and remain **canonical
  document-global offsets** into the immutable canonical text identified
  by `document_versions.canonical_text_key` (migration 0002 invariants).
  Persisted provenance is **never rewritten** into any other coordinate
  system.
- Sections likewise carry canonical global `start_char` / `end_char`,
  plus `content`, which must be exactly the canonical text slice
  `canonical_text[start_char:end_char]` (so
  `content.length === end_char - start_char`).
- The web derives section-local coordinates on the fly as
  `span.start_char - section.start_char`; it never mutates the
  `SourceSpan` object. A span in any non-first section therefore has a
  global `start_char` that can exceed its section's content length —
  contract fixtures encode exactly this case so a section-local
  misreading fails tests immediately.
- Integrity invariants the server must guarantee for every span in the
  response: `section_id` belongs to the selected version;
  `section.start_char <= span.start_char <= span.end_char <=
  section.end_char`; and `span.text_hash` is the sha256 of the canonical
  text slice `[span.start_char, span.end_char)` (equivalently of
  `section.content[span.start_char - section.start_char : span.end_char -
  section.start_char]`). Clients re-verify and fail closed with an
  integrity alert on mismatch (issue #87 package B).

## 5. Response shape and size posture

Top level (`ReaderResponse`, all fields required):

| Field | Meaning |
|---|---|
| `as_of` | Effective cutoff enforced (section 1). |
| `corpus_version_id` | The pin used, or `null` when unpinned. |
| `selection_policy` | `corpus_pinned` \| `latest_parsed` (section 3). |
| `document` | The target: `meta` (`DocumentMeta`, whose `id` is the target document id), `document_version_id`, `sections`, `spans`, `facts`. |
| `siblings` | Same-entity documents visible at the cutoff, excluding the target: each with `meta`, `document_version_id`, `spans`, `facts` — **no sections**. |

- Spans are `{ id, span }` records (`span` is the frozen
  `source-span/v1` shape, untouched); facts are `{ id,
  document_version_id, duplicate_of?, restates?, fact }` records (`fact`
  is the frozen `financial-fact/v1` shape, untouched). Record wrappers
  carry the server-side row ids so citations and `source_span_id` /
  `duplicate_of` / `restates` references resolve within the response.
- Every span and fact in a document block belongs to exactly that block's
  selected `document_version_id` (no dangling or cross-version evidence),
  and every `fact.source_span_id` resolves to a span **in the same
  block**.
- `duplicate_of` / `restates` expose the ingestion-computed duplicate and
  restatement linkage (migration 0002), which together with sibling
  `meta` (`form`, `accession`, `published_at`, `filed_at`, period fields)
  and sibling facts/spans is the evidence base for duplicate and
  amendment comparison — e.g. resolving a chain of 10-K/A amendments to
  the terminal authoritative one by `published_at` under the cutoff.

**Size posture.** Exactly one document's canonical section content is
returned per response (the target's). This is the dominant payload term
(a large 10-K canonical text is single-digit MB) and is irreducible for a
reader that must render and hash-verify exact text. Siblings deliberately
omit sections/content, so sibling cost is O(facts + referenced spans),
small per filing; opening a sibling is another reader call for that
document id. v0.2.0 defines **no pagination**: one issuer's visible
filing history at fact granularity is modest (hundreds of filings ×
tens–hundreds of facts), and cursor pagination added later (query
parameters plus optional response fields) would be additive under
VERSIONING.md. If a pathological corpus makes sibling fan-out a problem
before then, the correct mitigation is server-side response streaming or
compression, not a contract change. Servers should apply HTTP compression
(transport concern; not part of this contract).

## 6. Compatibility

- Additive minor bump per `packages/contracts/VERSIONING.md`: OpenAPI
  `info.version` 0.1.0 → 0.2.0; new path, new component schemas, new
  `securitySchemes`; **no existing path, schema, field, enum, or fixture
  changes**. `CONTRACT_VERSION` in `packages/contracts/src/index.ts`
  becomes `0.2.0` (used nowhere outside the package today).
- New JSON Schema `reader-response/v1` (`x-fel-version` 1.0.0) `$ref`s
  the frozen `source-span/v1` and `financial-fact/v1` schemas rather than
  copying them.
- `selection_policy` is declared `x-fel-open-enum: true` (consumers must
  tolerate unknown values), so a future policy (e.g. a workspace-level
  pin) is a minor bump. Error `code` values remain the frozen envelope
  contract.
- The reader is a pure read composite over existing tables; **no DB
  migration is expected or authorized** by this ADR (issue #87: any
  migration need stops the work and returns here).
- Follow-up for the integration lead (path not writable by package A):
  add the v0.2.0 row / reader-response artifacts to
  `docs/handoff/CONTRACTS.md`'s frozen-artifact table.

## Decision points requiring integration-lead ruling

1. The `latest_parsed` total order (section 3): `created_at` DESC, then
   bytewise `parser_version` DESC, `normalizer_version` DESC, `id` DESC.
2. Sibling documents carry facts + referenced spans but **no sections**
   (section 5) — the response-size posture, including "no pagination in
   v0.2.0".
3. Unknown/draft `corpus_version_id` → 404 with
   `details.resource = "corpus_version"`; unparsed-in-corpus or
   never-parsed target → plain missing-target 404 (sections 1, 3).
4. `selection_policy` as an open enum; `as_of` defaulting to request time
   with the effective value echoed (sections 1, 6).

## Consequences

- Package C (`feat/reader-evidence-api`) implements exactly this
  contract; packages B/D can build against the frozen fixture
  immediately.
- `apps/web` replaces its hand-mirrored `NormalizedFinancialFact` with
  the generated `components["schemas"]["FinancialFact"]` type and keys
  reader rendering off `ReaderResponse` (package D).
- Contract drift is caught three ways in CI: `check:generated`
  (regeneration diff), the vitest regeneration-equality test, and ajv
  fixture validation of `reader-response.json` (which exercises the
  global-offset and cross-reference invariants above).

# Reader API Integrity Classification Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this bounded plan task-by-task after the integration lead registers and releases the child workstream. Implementation is released only after the reviewed workstream registration merges.

**Goal:** A typed API INTEGRITY_ERROR renders the existing explicit integrity failure state with no verified quote, rather than generic service unavailability.

**Architecture:** Reuse the current validated error fields and existing failure-state/UI path. Add one code-aware5xx classification, adjust the existing public integrity copy to cover both API integrity and reader-contract failures, and align the offline eval mirror. No new validator, dependency, endpoint, error enum on the wire, route control flow, or generic abstraction.

**Tech Stack:** Existing TypeScript/React/Next, Vitest, Python stdlib/pytest; immutable locked tools.

**Spec:** #108 accepted design addendum item9 (dedicated integrity prerequisite), existing `packages/contracts/schemas/error.schema.json`, ADR0005/ADR0021, and the parent's explicit instruction to preserve all404/anti-oracle semantics. Source inspected at e6e24b0; before implementation recheck current-main source and overlapping ownership. Issue #301 and branch `agent/301-reader-integrity` own the seven files below; the lead releases implementation after this registration merges.

## Global constraints and decision

- No shared contracts, schemas, locks/configuration, API, worker, migration, hosted workflow or credential edits. No provider/hosted calls. #108/#96/#87 remain open.
- All404 behavior is frozen for this change, including invalid/draft corpus pins currently becoming null. The historical pin-classification question is deliberately not included.
- Preserve401 authentication,403 forbidden,409 conflict,413 too_large,422 invalid_scope,429 unavailable, ordinary500/502/503 outage behavior, transport failures and all existing metadata handling.
- Existing `parseErrorEnvelope` already checks non-null/non-array root/error objects and string code/message/request_id. Reuse it **unchanged**. Classify integrity only from its returned result with exact code INTEGRITY_ERROR and HTTP500–599.
- This validates fields used by classification; it is **not full schema validation**. The frozen schema is closed, but the existing runtime parser tolerates unknown root/error properties and does not validate details. Preserve that compatibility explicitly rather than silently tightening all errors. Unknown properties/details cannot select a kind, override status/code, or render in UI. Missing/wrong-type required fields continue to yield no parsed envelope and therefore unavailable for5xx.
- An AJV schema import was considered and rejected for this prerequisite: it would change existing malformed-envelope/metadata compatibility or require a second integrity-only parser, with no additional authority granted by the new fixed-copy state. No cast of raw unparsed JSON into an integrity decision.
- Existing `EvidenceFailureState` already supports integrity; `evidenceFailureState` returns `EvidenceApiError.kind`; ReaderPage already catches and renders this component before any reader evidence. Do not edit those routing/adapter functions.

## Exact proposed seven-file allowlist

1. `apps/web/src/lib/data/http-source.ts` — add internal integrity kind and pass validated code to status classifier; leave parseErrorEnvelope/getReader/null handling untouched.
2. `apps/web/src/lib/data/http-source.test.ts` — actual HTTP source classification, malformed fields, compatibility/status preservation and public-safe errors.
3. `apps/web/src/components/EvidenceFailureState.tsx` — only the existing integrity description string; heading/retry behavior unchanged.
4. `apps/web/src/components/EvidenceFailureState.test.tsx` — fixed integrity copy and retry/public-safety assertions.
5. `apps/web/src/app/reader/reader-pagination.test.tsx` — one cross-layer regression from real HttpEvidenceSource with a mocked HTTP error response through existing ReaderPage rendering; no reader/route production edit.
6. `evals/harness/reader_cross_stack.py` — integrity Literal and equivalent code-aware classification with the same minimal parsed-envelope field checks at mirror call sites.
7. `evals/tests/test_reader_cross_stack.py` — integrity/ordinary-outage matrix, malformed/extra-property compatibility, existing404 behavior, and one added assertion on the real API corruption response when stack tests execute.

No dataset fixture change is necessary: `error_envelopes.json` already contains a valid INTEGRITY_ERROR fixture. Existing modules exceed/approach500 lines; this is a small additive correction, not authorization for a module split. Expected production delta approximately20–35 lines total plus one copy string, with bounded regression tests. Return to lead if unexpected source changes are needed.

## Task1 — HTTP classification and actual reader failure rendering

Interfaces: `EvidenceFailureKind` gains `"integrity"`. Internal classifier becomes `failureKind(status: number, code?: string): EvidenceFailureKind`; toApiError supplies only the already parsed `envelope?.error.code`. No exported signatures or HTTP wire schema change.

- [ ] Add failing HttpEvidenceSource tests using `new Response(JSON.stringify(envelope), {status:500,headers:{"Content-Type":"application/json"}})`. Assert `getReader(documentId)` rejects `EvidenceApiError` with kind integrity, status500, code INTEGRITY_ERROR and requestId retained; error.message never contains upstream message/details/token. Confirm expected RED is current unavailable classification.
- [ ] Test500/502/503 valid INTEGRITY_ERROR→integrity;500/502/503 other code, missing/HTML/malformed JSON→unavailable. Required-field invalid cases: null/array root, null/array error, missing or nonstring code/message/request_id, case-variant code. Test nested arbitrary INTEGRITY_ERROR text does not count when the actual error.code differs.
- [ ] Lock existing tolerance: extra root/error fields and arbitrary details with the three correct string fields retain integrity classification but do not render. State in test names that these are tolerated envelopes, not schema-valid examples. Valid code/message/request_id with empty message/request_id retains existing string-only acceptance.
- [ ] Lock status precedence using INTEGRITY_ERROR envelopes at401/403/409/413/422/429 and404. Expect the existing corresponding kinds;404 still resolves null regardless of body. Retain existing missing/cutoff/draft-pin paths untouched. A200 success body resembling an error must still fail reader contract validation, never enter the new HTTP-error branch.
- [ ] Implement the minimal code:

```ts
// Add "integrity" to EvidenceFailureKind.
function failureKind(status: number, code?: string): EvidenceFailureKind {
  if (status === 401) return "authentication";
  if (status === 403) return "forbidden";
  if (status === 409) return "conflict";
  if (status === 413) return "too_large";
  if (status === 422) return "invalid_scope";
  if (status >= 500 && status < 600 && code === "INTEGRITY_ERROR") return "integrity";
  return "unavailable";
}
// In existing toApiError, after unchanged parseErrorEnvelope:
return new EvidenceApiError(response.status, path,
  failureKind(response.status, envelope?.error.code), envelope);
```

- [ ] Keep heading `Evidence response rejected` and retry enabled. Replace only description with: `The evidence failed an integrity or reader-contract check. No verified quote is shown.` This is truthful for both the new API failure and existing EvidenceContractError; do not render upstream details to explain the difference.
- [ ] Add a route-level test in the existing reader-pagination suite: return an actual HttpEvidenceSource from mocked getEvidenceSource, whose fetchImpl returns the valid500 INTEGRITY_ERROR envelope; call `ReaderPage({params:Promise.resolve({documentId:DOC_10Q_ID})})` and renderToStaticMarkup. Assert role alert, fixed heading/description, retry control; no EvidenceReader/verified citation content, no private envelope text and no NOT_FOUND exception. Keep the existing contract-error, not-found and unexpected-error cases.
- [ ] Run focused Vitest tests below; confirm GREEN. Commit the bounded HTTP/UI change and tests. Draft PR uses Related #108, never Closes #108/#96/#87.

## Task2 — Keep eval mirror truthful

The mirror must receive body/parsed code rather than classify only by status. Minimal interface: `classify_http_failure(status: int, envelope: Any = None) -> EvidenceFailureKind`. Preserve the existing404→not_found function result and MockHttpEvidenceTransport's404→None early return.

- [ ] Add RED assertions: the existing integrity fixture must classify as integrity; ordinary500/502/503 remain unavailable. Update the old aggregate test that currently expects integrity fixture to yield unavailable; add ordinary outage cases so outage coverage is retained.
- [ ] Use the same required-field checks, without a new schema dependency:

```python
error = envelope.get("error") if isinstance(envelope, dict) else None
valid = isinstance(error, dict) and all(
    isinstance(error.get(field), str) for field in ("code", "message", "request_id")
)
if 500 <= status < 600 and valid and error["code"] == "INTEGRITY_ERROR":
    return "integrity"
```

Insert after existing explicit status branches. Add integrity to EvidenceFailureKind. Pass actual `envelope` from `assert_auth_errors_are_not_404` and actual `body` from MockHttpEvidenceTransport; retain all404 paths and missing-route failure logic. Unknown fields/details remain ignored as in the web parser. No web imports or duplicated financial/source validation.

- [ ] Mirror malformed/extra-property/status cases from task1 using focused parametrized tests. Add `assert rcs.classify_http_failure(response.status_code, response.json()) == "integrity"` to existing `test_stack_corrupt_span_hash_returns_integrity_error_not_404`; retain every existing API status/code assertion. No new DB setup or fixture writes beyond the existing test.
- [ ] Run offline eval tests (three DB-gated skips reported honestly). Full required CI supplies its existing real PostgreSQL path. Commit mirror/tests after GREEN. Do not label these mock/API checks as hosted/browser acceptance.

## Verification and handoff

Use Node24.20.0 and frozen offline workspace dependencies; no install updates. Use immutable `/private/tmp/fel203-dev/bin/python` for Python.

```sh
pnpm exec vitest run apps/web/src/lib/data/http-source.test.ts apps/web/src/components/EvidenceFailureState.test.tsx apps/web/src/app/reader/reader-pagination.test.tsx apps/web/src/lib/data/failure-state.test.tsx
/private/tmp/fel203-dev/bin/python -m pytest evals/tests/test_reader_cross_stack.py
pnpm typecheck
pnpm exec eslint apps/web/src/lib/data/http-source.ts apps/web/src/lib/data/http-source.test.ts apps/web/src/components/EvidenceFailureState.tsx apps/web/src/components/EvidenceFailureState.test.tsx apps/web/src/app/reader/reader-pagination.test.tsx
/private/tmp/fel203-dev/bin/python -m ruff check evals/harness/reader_cross_stack.py evals/tests/test_reader_cross_stack.py
/private/tmp/fel203-dev/bin/python -m black --check evals/harness/reader_cross_stack.py evals/tests/test_reader_cross_stack.py
pnpm exec vitest run --coverage
pnpm --filter @fel/contracts check:generated
git diff --check
```

Format only named changed files, preserve coverage floors, run all required final-head CI and existing extraction browser acceptance. If local DB stack verification is desired, lead assigns a fresh dedicated base using the existing reader QA harness isolation; do not point this eval at another lane or the benchmark DB. No new browser/hosted harness or screenshot is needed for this prerequisite; full #108 proof remains separate.

Final independent review must confirm: parsed-field provenance of code, unchanged404/anti-oracle paths and parser tolerance, public-safe fixed copy, real HTTP-source→ReaderPage regression, mirror parity, exact seven-file scope and exact-head CI. Root alone merges and updates completion ledgers. Implementation starts after independent plan review and the registration merge; hosted acceptance remains separate.

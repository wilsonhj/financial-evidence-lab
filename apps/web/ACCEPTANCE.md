# M2-OBSERVATORY-UI (#59) — acceptance report

The Search Observatory ships on `agent/m2-observatory-ui` as four reviewed
slices (M2-030…033). It consumes the frozen ADR-0006 query/trace/SSE contract
through a server-only source boundary: the UI never sees a bearer token and
never assembles request shapes by hand. Every load-bearing assertion is a
component or unit test in the `apps/web` vitest suite; the correctness fixes
from the two independent reviews (aware-datetime cutoff, citation span
equality, full trace validation) each carry red-green perturbation evidence.
Line references below are to the head of this branch.

## Acceptance criteria — evidence map

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Server-only bearer auth; no fixture fallback in configured HTTP mode | ✅ | `http-source.ts` node-builtin server-only tripwire (import `node:process`); `http-source.test.ts:39` bearer + Idempotency-Key + no-store, `:58` token kept out of the URL via async provider; `server.ts` fails closed (unset `FEL_EVIDENCE_SOURCE` throws, never defaults to fixtures); `runtime-config.test.ts:9` fail-closed when unset, `:37`/`:51` HTTP mode rejects a missing token/base-url/workspace and a non-UUID workspace or credentialed base-url |
| 2 | SSE reconnect (Last-Event-ID) — no missing/duplicate rendered events; heartbeat/terminal/error handled | ✅ | `sse.test.ts:102` mid-run resume with no missing/duplicate events, `:76` strictly-increasing seq rejects duplicate/older, `:61` heartbeat frames surfaced as heartbeats not events, `:74` CRLF (`\r\n\r\n`) mid-stream framing, `:90` stops on terminal and never reconnects after, `:120` stops on abort, `:133` bounds reconnect attempts; `http-source.test.ts:164` `Last-Event-ID` resume header, `:183` typed error when the stream cannot open; `mock-source.test.ts:38` replays only events after `Last-Event-ID`. Parser/reconnect landed and unit-tested; live same-origin SSE proxy remains unmounted (stored-trace M2) — see deferrals |
| 3 | Lane/top-k/time controls stay within contract bounds and create traceable reruns | ✅ | `controls.test.ts:19` top_k 1..100, `:26` unknown lane / required question, `:33` ≤20 form/period filters, `:39` offset-less `datetime-local` normalised to an aware UTC `as_of` (review fix B1), `:51` lanes omitted → server default; `ObservatoryControls.test.tsx:11` inputs bounded to contract ranges, `:24` validation error surfaced and `parentQueryId` threaded for a control-changed rerun; `actions.ts` `rerunAction`/`submitQueryAction` mint a fresh `Idempotency-Key` per run; `compare.test.ts:8` run comparison flags only differing metrics |
| 4 | Candidate opens exact reader span; future/corrupt/cross-version never rendered as supported | ✅ | `trace-view.test.ts:40` temporal integrity guard, `:51` accepted-but-future reclassified rejected, `:64` future & cross-version never supported, `:78` claim citing a non-supported item downgraded, `:102` claim citing the right item but the WRONG span downgraded (review fix B2), `:135` empty-citation supported/partially_supported downgraded to unverifiable, `:158` candidate span deep link, `:167` citation deep-links the citation's span not the candidate's (review fix B2); `ObservatoryTrace.test.tsx:50` candidate links its exact reader span, `:57` future/cross-version render only as rejected; `reader-links.test.ts:13` version→DocumentMeta id resolution; fail-closed contract validation `http-source.test.ts:110` rejects a malformed trace and `:118` rejects malformed `events`/`timings_ms`/`budget_usage`/contribution lane+shape (review fix B3) → typed `integrity` state instead of a raw render crash |
| 5 | 401/403/409/422/5xx, abstention and contradiction are distinct typed states | ✅ | `http-source.test.ts:77` 401/403/409/422/5xx → distinct typed kinds without leaking the body, `:100` transport/bad-token → `unavailable`/`authentication`; `errors.ts` `observatoryFailureKind`/`observatoryFailureState` map to the shared `EvidenceFailureState`; `observatory-a11y.test.tsx:30` abstained/failed/cancelled distinguished and silent for succeeded, `:40` abstention rendered as its own alert separate from contradiction and error; `ObservatoryTrace.test.tsx:66` contradiction rendered distinctly |
| 6 | Keyboard operation, text/table alternatives, WCAG 2.2 AA, reduced motion, component tests, browser E2E | ⚠️ Partial | `observatory-a11y.test.tsx:67` every data table has a caption + row/column header scopes (table alternative), `:80` every control is labelled and status is conveyed by text not colour alone, `:100` reduced-motion rule shipped (`globals.css:442` `prefers-reduced-motion: reduce`); component tests: full `apps/web` vitest suite green; semantic HTML + focusable native controls give baseline keyboard operation. **Committed browser E2E and a full WCAG 2.2 AA / keyboard audit are deferred** — see below |
| 7 | `make ci`, telemetry, docs and acceptance evidence | ✅ | Gates green at head: `vitest run apps/web` (211), repo `typecheck`, `lint`, `format:check`, `@fel/web build`; docs: `apps/web/README.md` + this report; telemetry: web-layer observability is at parity with the reader (see deferral) |

## Required-outcome line

Server-only bearer boundary (no client token, fail-closed config) ✅ · plan /
variants / filters rendered ✅ · four lane candidate lists with raw + RRF +
rerank ranks ✅ · dedupe & rejection reasons ✅ · context budget, latency, cost
✅ · atomic claims with citation status, integrity-downgraded when evidence is
future / cross-version / wrong-span ✅ · candidate → exact reader span deep link
✅ · typed failure / abstention / contradiction states ✅ · bounded controls,
parent-linked reruns, run comparison ✅ · stored event replay ✅ · SSE
reconnect/heartbeat/terminal parsing ✅.

## Defects found and fixed (independent review pass)

- **B1 — offset-less cutoff → 422.** `datetime-local` emits an offset-less
  `YYYY-MM-DDTHH:mm`; controls forwarded it verbatim, which the API's
  `AwareDatetime` `as_of` rejects. Fixed by normalising to an aware UTC
  RFC3339 value (`toAwareCutoff`); test now feeds a value the input can emit.
- **B2 — citation span not enforced.** A claim was downgraded on `item_id`
  membership only, and the reader deep link targeted the candidate's span, so a
  citation with the right item but the wrong span rendered supported and linked
  the wrong span. Fixed: support requires an (`item_id`, `source_span_id`) match
  and the deep link targets the citation's span.
- **B3 — incomplete trace validation.** `validateTrace` skipped `events`,
  `timings_ms`, and the inner shape / `lane` enum of `candidate.contributions`,
  all consumed unguarded downstream — a malformed 2xx crashed render instead of
  raising the typed `ObservatoryContractError`/`integrity` state. Now validated
  (including numeric `budget_usage` fields the BudgetSection dereferences).
- **Minor.** `isRenderableAsSupported` docstring tightened to stop claiming a
  cross-version guard it cannot enforce (candidates carry no per-candidate
  corpus/index version); the reflected `?error=` on the landing and run pages is
  whitelisted to known action-failure slugs instead of rendering arbitrary
  searchParam text; empty-citation "supported" claims downgrade to unverifiable;
  SSE block framing accepts `\r\n\r\n` / `\n\n` / `\r\r`.

## Known deferrals (tracked, non-blocking)

- **Browser E2E execution in CI** — the Playwright specs are committed here
  (`apps/web/e2e/*`, `playwright.config.ts`, `test:e2e` script; this added the
  `@playwright/test` dev-dependency and updated the lockfile) and run in fixture
  mode (`next build && next start`). They are not yet executed in CI — no browser
  stage is wired — so criterion 6 stays Partial: the full keyboard-operation and
  WCAG 2.2 AA audits that ride on that surface remain deferred. Component-level
  a11y (labels, table scopes/captions, text-not-colour status, reduced motion) is
  covered here.
- **Live same-origin SSE proxy** — M2 runs are synchronous-terminal: the UI
  renders the stored event log (`EventReplay`) and the SSE parser/reconnect
  logic is unit-tested against the mock stream, but no live same-origin SSE
  proxy route is wired. It becomes load-bearing only with async runs (M3),
  matching the retrieval package's synchronous-terminal deferral.
- **Web-layer telemetry** — at parity with the reader: neither surface ships
  bespoke client telemetry. Observability in M2 derives from the API request
  middleware (`duration_ms` structured logs) plus the persisted domain trace
  the UI renders verbatim (events / decisions / timings_ms / budget_usage).
  A dedicated web client-telemetry channel is deferred.

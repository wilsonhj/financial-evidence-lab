# Web app (`@fel/web`)

<details>
<summary>Relevant source files</summary>

- [src/proxy.ts](src/proxy.ts) — Next.js Proxy that returns HTTP 503 on business routes unless the deployment mode is valid
- [src/lib/deployment-mode.ts](src/lib/deployment-mode.ts) — `assertDeploymentMode`: the `fixture`, `reader-smoke` and `synthetic-http` checks
- [src/lib/data/](src/lib/data/) — `EvidenceSource` interface, fixture and HTTP readers, `runtime-config.ts`
- [src/lib/observatory/](src/lib/observatory/) — Search Observatory sources, runtime config and server actions
- [src/lib/extraction/](src/lib/extraction/) — extraction review source, route allowlist (`routes.ts`), upstream transport and fixture
- [src/app/api/extraction/\[...path\]/route.ts](src/app/api/extraction/[...path]/route.ts) — same-origin extraction proxy
- [src/app/api/extraction/runs/\[runId\]/events/route.ts](src/app/api/extraction/runs/[runId]/events/route.ts) — extraction run event stream proxy
- [src/app/desk/DeskClient.tsx](src/app/desk/DeskClient.tsx) — Earnings Update Desk, static fixture data
- [src/app/api/telemetry/route.ts](src/app/api/telemetry/route.ts) — opt-in client telemetry sink
- [package.json](package.json) — scripts and dependencies

</details>

Source references verified against commit `f4b1197`.

`@fel/web` is the Next.js (App Router) front end. It hosts the Evidence Reader,
the Search Observatory, the extraction review screens, and the Earnings Update
Desk. Data is read on the server, and every source fails closed: a missing
or invalid configuration never falls back to fixtures.
This page is for developers running or changing the web app. The API it calls
is described in the [API README](../api/README.md); deployment modes are
decided in
[ADR-0027](../../docs/decisions/ADR-0027-deployment-modes.md).

## Run

```sh
pnpm --filter @fel/web dev     # http://localhost:3000
pnpm --filter @fel/web build   # production build (Turbopack)
pnpm --filter @fel/web start   # serve the production build
pnpm --filter @fel/web test    # vitest unit suites
pnpm --filter @fel/web typecheck
```

A local fixture run needs an explicit mode:

```sh
FEL_DEPLOYMENT_MODE=fixture FEL_API_BEARER_TOKEN= FEL_EVIDENCE_SOURCE=fixture \
  corepack pnpm --filter @fel/web dev
```

See [Local development](../../docs/development/local.md) for the HTTP modes.

## Routes

| Route | What it shows | Data source |
| ----- | ------------- | ----------- |
| `/` | Filing list for the configured entities | `EvidenceSource` |
| `/reader/[documentId]` | Evidence Reader for one filing version | `EvidenceSource` |
| `/observatory` | Search Observatory query form | Observatory source |
| `/observatory/runs/[runId]` | One retrieval run, evidence feedback and run history | Observatory and `EvidenceSource` |
| `/observatory/runs/[runId]/history` | Persisted event history of a retrieval run | Observatory source |
| `/observatory/compare` | Comparison of two retrieval runs | Observatory source |
| `/extractions`, `/extractions/[id]` | Extraction review queue and one proposal | Extraction source |
| `/extraction-runs`, `/extraction-runs/[runId]` | Extraction runs and one run with its steps | Extraction source |
| `/extraction-runs/[runId]/events` | Stored extraction events of a run | Extraction source |
| `/approved-extractions/[recordId]` | One approved record | Extraction source |
| `/approved-extractions/[recordId]/versions`, `.../versions/[versionId]` | Immutable approval history | Extraction source |
| `/desk` | Earnings Update Desk | Static fixture data in `DeskClient.tsx`; nothing is computed |
| `GET /api/health` | Mirrors the API health contract for platform probes | none |
| `/api/extraction/...` | Same-origin extraction proxy (see below) | Extraction source |
| `POST /api/telemetry` | Opt-in client telemetry sink | none |

## Evidence Reader (spec 8.3)

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

## Data sources

The app has three server-only sources. All three read the same
`FEL_EVIDENCE_SOURCE` switch, so a deployment cannot serve live reader evidence
while another screen silently uses fixtures. Each one calls
`assertDeploymentMode` before it reads any other setting.

| Source | Module | `fixture` | `http` |
| ------ | ------ | --------- | ------ |
| `EvidenceSource` (filing list, reader) | `src/lib/data` | Synthetic filing in `src/lib/fixtures/synthetic-filing.ts` | ADR-0005 composite reader endpoint |
| Observatory source | `src/lib/observatory` | Synthetic trace in `src/lib/observatory/fixtures/` | Workspace-scoped retrieval API |
| Extraction source | `src/lib/extraction` | In-process synthetic session in `fixture.ts` | Workspace-scoped extraction API |

The fixture filing is a fictional issuer with a 10-Q, a restating 10-Q/A, a
conflicting duplicate fact pair, a consistent duplicate pair, and a dimensioned
segment fact. Fixture spans and facts are validated against the frozen
`@fel/contracts` JSON Schemas, and every span's `text_hash` is recomputed in
tests.

`DocumentMeta`, `SourceSpan`, `FinancialFact`, and `ReaderResponse` are
generated from `@fel/contracts` and never redefined here. The HTTP reader
validates target identity, effective cutoff/corpus scope, selected-version
consistency, same-entity siblings, and fact/span references before the reader
can render. Target citations are then hash-verified against canonical-global
section offsets and fail closed on mismatch.

## Extraction proxy

The browser never calls the API directly for extraction. Client components call
same-origin routes under `/api/extraction/`:

- `src/app/api/extraction/[...path]/route.ts` handles `GET`, `POST` and
  `DELETE`.
- `src/app/api/extraction/runs/[runId]/events/route.ts` relays a run's live
  event stream.

Both pass the request to the extraction source. `src/lib/extraction/routes.ts`
maps the local path to one allowlisted upstream route; the browser names a
local resource, never an upstream URL. The server adds the bearer token and
workspace ID. A deployment-mode refusal returns 503 with
`PUBLIC_AUTH_NOT_READY`; any other failure returns 503 with
`EXTRACTION_UNAVAILABLE`.

## Deployment modes

`FEL_DEPLOYMENT_MODE` is operator configuration; no header, query parameter or
hostname selects it. `src/proxy.ts` runs `assertDeploymentMode` on `/`,
`/desk`, `/reader`, `/observatory`, `/extractions`, `/extraction-runs`,
`/approved-extractions` and `/api/extraction`. Any refusal returns HTTP 503
with `Cache-Control: no-store` before the page, action or stream runs (a JSON
error with code `PUBLIC_AUTH_NOT_READY` on API paths). `/api/health`, static
assets and the telemetry route are not matched.

| Mode | Accepted when |
| ---- | ------------- |
| `fixture` | `FEL_EVIDENCE_SOURCE=fixture` and `FEL_API_BEARER_TOKEN` is empty |
| `reader-smoke` | HTTP source, `FEL_AUTH_MODE=mock`, a valid `FEL_API_BASE_URL` and `FEL_READER_SMOKE_TARGET`, and a mock bearer token (or the literal `invalid`) |
| `synthetic-http` | As `reader-smoke`, plus a loopback API URL, `FEL_ALLOW_MOCK_LLM=1`, `FEL_SYNTHETIC_HTTP_TARGET`, and a `CROSS_STACK_MANIFEST` whose identities match the token, `FEL_WORKSPACE_ID` and `FEL_ENTITY_IDS` |

Any other value, including unset (which ADR-0027 defines as `public`), is
refused with 503 until request-scoped sessions exist. The full policy is in the
[deployment guard contract](../../docs/research/deployment-guard-contract.md).

## Environment variables

All variables except `NEXT_PUBLIC_FEL_WEB_TELEMETRY` are read on the server
only. Never expose the bearer token through a `NEXT_PUBLIC_` variable.

| Variable | Purpose |
| -------- | ------- |
| `FEL_DEPLOYMENT_MODE` | `fixture`, `reader-smoke` or `synthetic-http`; anything else returns 503 |
| `FEL_EVIDENCE_SOURCE` | `fixture` or `http`; no default |
| `FEL_API_BASE_URL` | API origin for `http`; HTTPS required in production except on loopback |
| `FEL_API_BEARER_TOKEN` | Bearer token for `http`; must be empty in `fixture` mode |
| `FEL_ENTITY_IDS` | Comma-separated entity UUIDs for the filing list |
| `FEL_WORKSPACE_ID` | Workspace UUID for the Observatory and extraction sources |
| `FEL_AS_OF` | Optional RFC 3339 cutoff for the reader |
| `FEL_CORPUS_VERSION_ID` | Optional corpus version UUID for the reader |
| `FEL_AUTH_MODE` | Must be `mock` for `reader-smoke` and `synthetic-http` |
| `FEL_READER_SMOKE_TARGET` | Target name for `reader-smoke` |
| `FEL_SYNTHETIC_HTTP_TARGET` | Target name for `synthetic-http` |
| `CROSS_STACK_MANIFEST` | Path to the cross-stack manifest for `synthetic-http` |
| `FEL_ALLOW_MOCK_LLM` | Must be `1` for `synthetic-http` |
| `FEL_WEB_TELEMETRY` | `1` enables the server telemetry route |
| `NEXT_PUBLIC_FEL_WEB_TELEMETRY` | `1` enables browser telemetry; inlined at build time |

## Client telemetry

A dedicated, opt-in channel for web-layer client telemetry — reader load
timing (time to first verified span) and Observatory query/trace fetch
timing and errors — separate from any backend observability pipeline.

- `NEXT_PUBLIC_FEL_WEB_TELEMETRY=1` enables the browser side
  (`src/lib/telemetry.ts`): batches `recordTiming`/`recordError` calls and
  flushes them with `navigator.sendBeacon` (falling back to
  `fetch(..., { keepalive: true })`) to the same-origin `POST /api/telemetry`.
  Unset (the default), every call is a no-op — no timers, no network
  activity.
- `FEL_WEB_TELEMETRY=1` enables the server side (`src/app/api/telemetry/route.ts`):
  the route returns `404` for any request unless set. When enabled, it
  validates and redacts every event via `src/lib/telemetry-validation.ts`
  (allowlisted event names, bounded batch size, numeric bounds, an
  attribute-key allowlist, and redaction of anything that looks like a bearer
  token, API key, or email address) before logging one structured JSON line
  per accepted event and returning `204`. An invalid request body returns
  `400` and the raw body is never echoed back.

Both flags default unset and are independent: the server route can be
enabled without the browser ever sending anything, and vice versa (though
the browser calls will simply get 404s in that case).

## Related pages

- [API](../api/README.md)
- [ADR-0027: deployment modes](../../docs/decisions/ADR-0027-deployment-modes.md)
- [Deployment guard contract](../../docs/research/deployment-guard-contract.md)
- [Local development](../../docs/development/local.md)

# Railway service configuration

Config-as-code for the Railway services. Each service in the Railway
dashboard points its "config file path" at the matching JSON file here.

- `api.json` — FastAPI service (`uvicorn`, `/health` healthcheck).
- `worker.json` — job-queue consumer (`python -m fel_workers run`). No
  healthcheck path: the consumer has no HTTP surface. The `ON_FAILURE`
  restart policy provides crash recovery only — it is not a liveness or
  readiness mechanism. Worker liveness monitoring is a follow-up once
  observability lands.

## Builder

Both files pin `"builder": "RAILPACK"`, per review, following the current
Railway Config-as-Code reference (which lists `RAILPACK` and `DOCKERFILE`).
Flagged as unverifiable from CI: the config schema is platform-validated at
deploy time, not by this repo's checks. If a deploy rejects the value, the
fallback is pinning the legacy `NIXPACKS` builder.

## Worker environment wiring

Variables are set in the Railway service's Variables tab, never in these
JSON files (no secrets in this tree — see `../README.md` and
`docs/handoff/CREDENTIALS.md`). Only variable NAMES are documented here.

| Variable | Required | Purpose |
| --- | --- | --- |
| `FEL_DATABASE_URL` | yes | Postgres connection string for the job queue. The consumer exits with status 2 if unset. |
| `FEL_SEC_LIVE` | to select live mode | When `"1"`, binds the live EDGAR client. Live mode fails closed: the process exits with status 2 unless `FEL_STORAGE_DIR` and `FEL_SEC_USER_AGENT` are also set. |
| `FEL_MOCK_SMOKE` | to select mock mode | When `"1"`, explicitly opts in to the deterministic mock providers. Non-production smoke option ONLY: a mock run claims real queued jobs and completes them with fabricated output, so it must be isolated on a non-production database/queue. Never set on a service pointed at production. |
| `FEL_SEC_USER_AGENT` | when `FEL_SEC_LIVE=1` | SEC fair-access identity sent as the EDGAR `User-Agent`. Value shape: `org-or-app name (contact@example.com)` — must be non-empty and contain a contact marker (`@`), or the process exits with status 2. The in-code default identity remains for library/tests only; the production identity always comes from this variable. |
| `FEL_STORAGE_DIR` | only when `FEL_SEC_LIVE=1` | Durable path for ingested blobs (`LocalDirStorageProvider`). On Railway this must point inside a mounted volume — container disk is ephemeral, and blobs stored outside a volume vanish on redeploy, leaving persisted storage keys (and citations) unresolvable. |
| `FEL_FRED_API_KEY` | for live FRED ingestion | FRED/ALFRED API credential. |
| `FEL_ALPHAVANTAGE_API_KEY` | for live market ingestion | Alpha Vantage API credential. |

## Explicit provider mode (fail closed)

The consumer never guesses a provider mode. Exactly one of
`FEL_SEC_LIVE=1` or `FEL_MOCK_SMOKE=1` must be set; with neither (or
both), `python -m fel_workers run` exits with status 2 — before any
database connection is attempted. A fresh deploy with no mode configured
therefore idles in an exit-2/restart loop (harmless under the
`ON_FAILURE` policy) rather than corrupting work: an implicit mock
default against a real queue would mark real `sec_discovery` jobs
successful with empty output and could persist mock bytes under real
accessions.

Enabling live ingestion is a deliberate, manual step: provision the
credentials per `docs/handoff/CREDENTIALS.md`, mount a Railway volume,
set `FEL_STORAGE_DIR` to a path on that volume, set `FEL_SEC_USER_AGENT`
to the deployment's SEC identity, and only then set `FEL_SEC_LIVE=1`.

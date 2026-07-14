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
deploy time, not by this repo's checks.

Fallback: if the first deploy is rejected outright, or builds but fails at
start with `No module named fel_workers` (worker) or `uvicorn: command not
found` (api), the Railpack provider provisioned a different Python
environment than the one the `buildCommand`'s `pip` installed into. Roll
back by pinning the legacy `NIXPACKS` builder in these files and
redeploying.

## Worker environment wiring

Variables are set in the Railway service's Variables tab, never in these
JSON files (no secrets in this tree — see `../README.md` and
`docs/handoff/CREDENTIALS.md`). Only variable NAMES are documented here.

| Variable | Required | Purpose |
| --- | --- | --- |
| `FEL_DATABASE_URL` | yes | Postgres connection string for the job queue. The consumer exits with status 2 if unset. |
| `FEL_SEC_LIVE` | to select live mode | When set truthy (see "Mode flag values" below), binds the live EDGAR client. Live mode fails closed: the process exits with status 2 unless `FEL_STORAGE_DIR` and `FEL_SEC_USER_AGENT` are also set. |
| `FEL_MOCK_SMOKE` | to select mock mode | When set truthy, explicitly opts in to the deterministic mock providers. Non-production smoke option ONLY: a mock run claims real queued jobs and completes them with fabricated output, so it must be isolated on a non-production database/queue. Never set on a service pointed at production. |
| `FEL_SEC_USER_AGENT` | when live mode is selected | SEC fair-access identity sent as the EDGAR `User-Agent`. Value shape: `org-or-app name (contact@example.com)` — at least 8 characters and containing a plausible contact address (`@` with a dotted domain; degenerate values like `@` or `ops@example` exit with status 2). The in-code default identity remains for library/tests only; the production identity always comes from this variable. |
| `FEL_STORAGE_DIR` | only when live mode is selected | Durable path for ingested blobs (`LocalDirStorageProvider`). On Railway this must point inside a mounted volume — container disk is ephemeral, and blobs stored outside a volume vanish on redeploy, leaving persisted storage keys (and citations) unresolvable. |
| `FEL_FRED_API_KEY` | not yet consumed | Reserved for future FRED/ALFRED job kinds. The deployed consumer today dispatches SEC discovery/fetch jobs only and does NOT read this variable — setting it has no effect until FRED ingestion lands. |
| `FEL_ALPHAVANTAGE_API_KEY` | not yet consumed | Reserved for future market-data (Alpha Vantage) job kinds. NOT read by the deployed consumer today — setting it has no effect until those job kinds land. |

### Mode flag values

`FEL_SEC_LIVE` and `FEL_MOCK_SMOKE` are parsed strictly: after stripping
whitespace, case-insensitive `1`/`true`/`yes`/`on` means set; absent or
empty means unset; ANY other non-empty value — including typos like
`ture` and including `0` — exits with status 2 naming the variable and
the received value. `0`/`false`/`no`/`off` are deliberately rejected
rather than read as unset: the explicit way to unset a mode is to REMOVE
the variable, and refusing "falsy" spellings avoids guessing whether the
operator meant "off" or mistyped an opt-in.

## Explicit provider mode (fail closed)

The consumer never guesses a provider mode. Exactly one of
`FEL_SEC_LIVE` or `FEL_MOCK_SMOKE` must be set truthy; with neither (or
both), `python -m fel_workers run` exits with status 2 — before any
database connection is attempted.

What that means for a fresh deploy with no mode configured: the process
fails fast with exit 2, `worker.json`'s `restartPolicyType: ON_FAILURE`
with `restartPolicyMaxRetries: 3` restarts it at most 3 times, and then
Railway STOPS restarting — the service ends in a crashed/stopped state
(visible as failed in the dashboard), not idling or retrying. That is the
intended fail-closed outcome: a stopped service is loudly wrong, whereas
an implicit mock default against a real queue would quietly mark real
`sec_discovery` jobs successful with empty output and could persist mock
bytes under real accessions. After setting the required variables, a
MANUAL redeploy/restart of the service is required — Railway does not
automatically revive a service that has exhausted its retries.

Enabling live ingestion is a deliberate, manual step: provision the
credentials per `docs/handoff/CREDENTIALS.md`, mount a Railway volume,
set `FEL_STORAGE_DIR` to a path on that volume, set `FEL_SEC_USER_AGENT`
to the deployment's SEC identity, set `FEL_SEC_LIVE=1`, and then redeploy
or restart the service.

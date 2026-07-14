# Railway service configuration

Config-as-code for the Railway services. Each service in the Railway
dashboard points its "config file path" at the matching JSON file here.

- `api.json` — FastAPI service (`uvicorn`, `/health` healthcheck).
- `worker.json` — job-queue consumer (`python -m fel_workers run`). No
  healthcheck path: it is not an HTTP service; liveness is covered by the
  ON_FAILURE restart policy shared with the API config.

## Worker environment wiring

Variables are set in the Railway service's Variables tab, never in these
JSON files (no secrets in this tree — see `../README.md` and
`docs/handoff/CREDENTIALS.md`). Only variable NAMES are documented here.

| Variable | Required | Purpose |
| --- | --- | --- |
| `FEL_DATABASE_URL` | yes | Postgres connection string for the job queue. The consumer exits with status 2 if unset. |
| `FEL_SEC_LIVE` | no | When `"1"`, binds the live EDGAR client instead of the deterministic mocks. Live mode fails closed: the process exits with status 2 unless `FEL_STORAGE_DIR` is also set. |
| `FEL_STORAGE_DIR` | only when `FEL_SEC_LIVE=1` | Durable path for ingested blobs (`LocalDirStorageProvider`). On Railway this must point inside a mounted volume — container disk is ephemeral, and blobs stored outside a volume vanish on redeploy, leaving persisted storage keys (and citations) unresolvable. |
| `FEL_FRED_API_KEY` | for live FRED ingestion | FRED/ALFRED API credential. |
| `FEL_ALPHAVANTAGE_API_KEY` | for live market ingestion | Alpha Vantage API credential. |

## Safe default: mock mode

`worker.json` deliberately does not set `FEL_SEC_LIVE`. A fresh deploy
therefore runs the consumer against the deterministic mock providers,
which need no credentials and no volume. Enabling live ingestion is a
deliberate, manual step: provision the credentials per
`docs/handoff/CREDENTIALS.md`, mount a Railway volume, set
`FEL_STORAGE_DIR` to a path on that volume, and only then set
`FEL_SEC_LIVE=1`.

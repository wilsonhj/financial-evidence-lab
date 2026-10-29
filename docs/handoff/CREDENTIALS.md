# Credential registry

This file records names and ownership only. Never commit values.

Every credential-type environment variable read (or reserved by name) in
`apps/`, `workers/`, `packages/`, `scripts/` and `infra/` is listed below.
Non-secret mode flags and targets such as `FEL_DEPLOYMENT_MODE`,
`FEL_AUTH_MODE`, `FEL_SEC_LIVE` and `FEL_STORAGE_DIR` are documented in
[`apps/api/README.md`](../../apps/api/README.md),
[`apps/web/README.md`](../../apps/web/README.md),
[`workers/README.md`](../../workers/README.md) and
[`infra/railway/README.md`](../../infra/railway/README.md), not here.

| Variable group | Earliest package | Delivery location | Status |
|---|---|---|---|
| Supabase URL and public client key | M0-AUTH integration | local environment / deployment secrets | Not requested |
| Supabase service-role key (`FEL_SUPABASE_URL`, `FEL_SUPABASE_SECRET_KEY`; reserved for live storage in `packages/providers/fel_providers/interfaces.py`, not yet read) | server integration tests | CI/deployment secrets only | Not requested |
| Hosted token verifier (`FEL_AUTH_ISSUER`, `FEL_AUTH_AUDIENCE`; read by `apps/api/app/config.py` when `FEL_AUTH_MODE=supabase`) | hosted API (ADR-0025, ADR-0027) | deployment secrets | Not requested |
| Postgres connection URLs (`FEL_DATABASE_URL`; `FEL_MIGRATION_DATABASE_URL` for the worker pre-deploy check in `infra/railway/worker.json`) | API and worker deployment | local environment / CI service containers / deployment secrets | Not requested |
| Web-to-API bearer token (`FEL_API_BEARER_TOKEN`; server-only, read by `apps/web/src/lib/data/runtime-config.ts` and `apps/web/src/lib/observatory/runtime-config.ts` when `FEL_EVIDENCE_SOURCE=http`, and by `apps/web/src/lib/deployment-mode.ts` in every mode: fixture mode requires it unset, and `reader-smoke`/`synthetic-http` parse it as mock claims) | hosted reader (#108) | deployment secrets | Not requested |
| OpenAI API key (`FEL_OPENAI_API_KEY`; reserved in `packages/providers/fel_providers/interfaces.py`, not yet read) | provider integration test | CI/deployment secrets only | Not requested |
| Alpha Vantage API key (`FEL_ALPHAVANTAGE_API_KEY`) | M1 market-data integration (M1-INGESTION) | CI/deployment secrets only | Not requested |
| FRED API key (`FEL_FRED_API_KEY`; read by `workers/src/fel_workers/ingestion/fred.py`, not yet by the deployed consumer) | FRED/ALFRED job kinds | CI/deployment secrets only | Not requested |
| SEC fair-access identity (`FEL_SEC_USER_AGENT`; required when `FEL_SEC_LIVE` is set) | live SEC worker | deployment secrets (contains contact data; never commit or log) | Not requested |
| Sentry DSN (`FEL_SENTRY_DSN`; API and worker) | M0-OBS-COST integration | deployment secrets | Not requested |
| Railway hosted reader-smoke target (`READER_SMOKE_SSH_PRIVATE_KEY`, `READER_SMOKE_SSH_KNOWN_HOSTS`, `READER_SMOKE_API_INSTANCE`, `READER_SMOKE_WEB_INSTANCE`, `READER_SMOKE_UNAUTHORIZED_WEB_INSTANCE`, `READER_SMOKE_FORBIDDEN_WEB_INSTANCE`, `READER_SMOKE_ENVIRONMENT_READ_TOKEN`; read by `.github/workflows/reader-prod-smoke.yml`, see [`evals/reports/reader-prod-smoke/README.md`](../../evals/reports/reader-prod-smoke/README.md)) | hosted reader smoke (#108) | GitHub environment secrets | Not requested |
| User-funded credential keyring (Fernet/MultiFernet, ADR-0026; `packages/providers/fel_providers/credential_cipher.py` takes it by constructor, so no variable name exists yet) | BYOK key-delivery package | deployment-managed secret outside the database | Not requested |

User-funded (BYOK) provider credentials under
[ADR-0026](../decisions/ADR-0026-public-workspaces-and-user-funded-inference.md)
belong to individual users. They are stored encrypted, selected per request and
never delivered through environment variables or this registry; only the
deployment keyring above is an operator credential.

Alpha Vantage tier note: the free tier is now limited to 25 requests/day and
`TIME_SERIES_DAILY_ADJUSTED` is premium-only. The M1 market-data work therefore
requires a paid tier (at least USD 49.99/month, 75 requests/min) or an ADR
revisiting the market-data adapter choice before integration.

SEC and FRED public access still require compliant identification, rate limits, and usage policy; they do not require secrets for the mock-first implementation.

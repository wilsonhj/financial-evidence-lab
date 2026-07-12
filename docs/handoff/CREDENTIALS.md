# Credential registry

This file records names and ownership only. Never commit values.

| Variable group | Earliest package | Delivery location | Status |
|---|---|---|---|
| Supabase URL and public client key | M0-AUTH integration | local environment / deployment secrets | Not requested |
| Supabase service-role key | server integration tests | CI/deployment secrets only | Not requested |
| OpenAI API key | provider integration test | CI/deployment secrets only | Not requested |
| Alpha Vantage API key | M1 market-data integration (M1-INGESTION) | CI/deployment secrets only | Not requested |
| Sentry DSN | M0-OBS-COST integration | deployment secrets | Not requested |

Alpha Vantage tier note: the free tier is now limited to 25 requests/day and
`TIME_SERIES_DAILY_ADJUSTED` is premium-only. The M1 market-data work therefore
requires a paid tier (at least USD 49.99/month, 75 requests/min) or an ADR
revisiting the market-data adapter choice before integration.

SEC and FRED public access still require compliant identification, rate limits, and usage policy; they do not require secrets for the mock-first implementation.

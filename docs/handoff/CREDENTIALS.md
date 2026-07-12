# Credential registry

This file records names and ownership only. Never commit values.

| Variable group | Earliest package | Delivery location | Status |
|---|---|---|---|
| Supabase URL and public client key | M0-AUTH integration | local environment / deployment secrets | Not requested |
| Supabase service-role key | server integration tests | CI/deployment secrets only | Not requested |
| OpenAI API key | provider integration test | CI/deployment secrets only | Not requested |
| Alpha Vantage API key | M1-MARKET integration | CI/deployment secrets only | Not requested |
| Sentry DSN | M0-OBS-COST integration | deployment secrets | Not requested |

SEC and FRED public access still require compliant identification, rate limits, and usage policy; they do not require secrets for the mock-first implementation.

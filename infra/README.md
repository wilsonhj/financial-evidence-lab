# Infrastructure

Platform configuration files and SQL migrations are the MVP's
infrastructure-as-code boundary (ADR-0002); Terraform/Pulumi are deferred.

## Layout

- `railway/` — Railway config-as-code. Each service in the Railway dashboard
  points its "config file path" at the matching JSON file. `api.json`,
  `worker.json` and `web.json` define their respective service commands.
  The web service uses the repository root so shared workspace contracts remain
  available. Per-service commands and environment wiring are documented in
  `railway/README.md`. Committed configuration does not prove hosted deployment.
- `scripts/backup_restore_smoke.sh` — migration + backup-restore smoke test
  run by the CI `database` job against a disposable Postgres container.

## Credentials

No secrets live in this tree. Hosted Supabase/Railway/Sentry credentials are
provisioned per `docs/handoff/CREDENTIALS.md` through the platforms' secret
stores only, and only when an integration-labeled issue requires them.

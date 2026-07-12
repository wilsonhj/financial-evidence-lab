# Infrastructure

Platform configuration files and SQL migrations are the MVP's
infrastructure-as-code boundary (ADR-0002); Terraform/Pulumi are deferred.

## Layout

- `railway/` — Railway config-as-code for the three services (web, api,
  worker). Each service in the Railway dashboard points its "config file
  path" at the matching JSON file.
- `scripts/backup_restore_smoke.sh` — migration + backup-restore smoke test
  run by the CI `database` job against a disposable Postgres container.

## Credentials

No secrets live in this tree. Hosted Supabase/Railway/Sentry credentials are
provisioned per `docs/handoff/CREDENTIALS.md` through the platforms' secret
stores only, and only when an integration-labeled issue requires them.

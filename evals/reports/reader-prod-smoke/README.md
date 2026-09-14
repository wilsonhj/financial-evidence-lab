# Reader production smoke evidence

The committed harness is preparation, not a hosted result. No hosted target,
credentials, deployment, screenshots or passing hosted run are asserted here.

## Provisioning prerequisites

An operator must provision a **dedicated disposable** PostgreSQL database,
API/storage service and three Next services on Railway, all at the same reviewed
commit. Never point fault commands at an ordinary production deployment. Run the
real fixture setup once in the API container against migrated empty evidence
storage. Keep the resulting manifest and local storage on that service. Configure
the API supervisor with `FEL_READER_SMOKE_SERVICE_HOSTED=1`, its matching
`FEL_READER_SMOKE_TARGET`, `FEL_AUTH_MODE=mock`, and the actual Railway `PORT`:

```sh
python -m evals.harness.reader_prod_smoke_service serve \
  --manifest /data/reader-smoke.json --dedicated-target dedicated-reader-smoke
```

The supervisor must stay alive while its owned API child is stopped. This creates
a real unavailable upstream at Railway's edge while preserving SSH recovery.
The service controller's watchdog must restart the child 600 seconds after
an owned stop; explicit `start` restores it sooner. The delay outlasts the
Playwright outage test budget so hosted health/UI assertions cannot race a
premature restart. Record the actual edge 502/503 observed, never substitute
middleware or assume both statuses were exercised.
This does not scale the whole container to zero.

Configure every Next service with the production HTTP evidence source, API URL,
workspace/entity/as-of values from the same manifest and matching target name.
The normal service uses the manifest owner's mock token; the unauthorized variant
uses literal `invalid`; the forbidden variant uses a mock owner claim for the
manifest's `denied_user`, who has no membership. These isolated variants let the
browser exercise real authentication failures without changing a shared service's
credentials. No bearer tokens enter the public manifest or browser traces.

All services must expose Railway's `RAILWAY_GIT_COMMIT_SHA` and
`RAILWAY_PUBLIC_DOMAIN` environment metadata. SSH inspection verifies the exact
revision, designated target, public domain, source binding and tenant config before
testing. The API and each web variant must be separate service instances.

## Protected workflow configuration

Create GitHub environment `reader-smoke` with required reviewers or a nonzero
wait timer. The dispatch workflow additionally checks that protection through the
GitHub API and refuses missing/unreadable/unprotected environments. No environment
creation, protection changes, credential provisioning or deployment is automated.

Environment variables (names only):

- `READER_SMOKE_TARGET`, `READER_SMOKE_REVISION` (exact 40-character SHA, identical
  to the workflow checkout and all deployed services).
- `READER_SMOKE_API_URL`, `READER_SMOKE_WEB_URL`,
  `READER_SMOKE_UNAUTHORIZED_WEB_URL`, `READER_SMOKE_FORBIDDEN_WEB_URL` (HTTPS).
- `READER_SMOKE_REMOTE_CWD`, `READER_SMOKE_REMOTE_PYTHON`,
  `READER_SMOKE_REMOTE_MANIFEST` (absolute API container paths; web source root
  must use the same working-directory path).

Environment secrets (values must never appear in issues, reports or logs):

- `READER_SMOKE_SSH_PRIVATE_KEY`: a dedicated key already registered with Railway.
- `READER_SMOKE_SSH_KNOWN_HOSTS`: independently verified pinned `ssh.railway.com`
  host keys. The workflow never trusts an unauthenticated runtime key scan.
- `READER_SMOKE_API_INSTANCE`, `READER_SMOKE_WEB_INSTANCE`,
  `READER_SMOKE_UNAUTHORIZED_WEB_INSTANCE`, `READER_SMOKE_FORBIDDEN_WEB_INSTANCE`:
  Railway **service instance IDs**, not service IDs.
- `READER_SMOKE_ENVIRONMENT_READ_TOKEN`: narrowly scoped repository environment
  read access used only to verify protection rules.

The [Railway SSH documentation](https://docs.railway.com/cli/ssh) specifies system
SSH with `<service-instance-id>@ssh.railway.com` and a registered key. The wrapper
pins that host, disables ambient SSH configuration, quotes all remote arguments,
and allows only manifest inspection plus named corruption/restoration and owned
API stop/start operations. It exposes no arbitrary shell-command interface.

## Running and retaining evidence

Deploy/stage reviewed code and synthetic data first, then manually dispatch
`Dedicated hosted reader smoke` from that exact revision. The workflow does not
deploy code. Preparation downloads the public manifest over SSH, checks all four
service revisions and bindings, and records target/URL/revision metadata. Each
mutation rechecks the remote revision, target and unchanged manifest.

Browser `finally` blocks restore faults, and workflow cleanup attempts restoration
again regardless of test outcome. An SSH/platform failure can prevent explicit
cleanup; the bounded service watchdog covers an abandoned API stop. The canonical
blob backup remains available for the operator to restore if the runner loses
connectivity during corruption. Do not report a pass until recovery is verified.

Actions artifacts contain the public manifest, deployed revision proof, raw test
results, browser-only traces, valid/corrupt screenshots, actual outage observation
and SHA-256 digest list. Raw SSH output, service environment dumps, bearer headers,
private keys, DSNs and authenticated API HAR files are excluded. After a real run,
commit a dated report with the run/artifact link, environment description, tested
SHA, outcomes, both acceptance screenshots and their digests. Failed runs retain
the same evidence. A missing hosted run leaves #108 open.

# ADR-0020: Select the worker database role in Railway startup

Status: Accepted for implementation under the owner's backlog execution request

Date: 2026-09-10

Issue: #190; prerequisite: PR #259 runtime installation and watchdog

## Context

Migration 0008 and PR #238 already provide `fel_worker NOLOGIN`, explicit
worker grants and consistency policies. Every worker-owned connection can
select that role through `FEL_WORKER_DB_ROLE`, but the committed Railway
command currently leaves the switch unset. Role creation alone therefore
does not establish restricted runtime privileges.

Historical worker source and migration comments cite ADR-0013. On main that
number belongs to task-ledger reconciliation; it is not the authority for this
rollout. This record documents the current decision without modifying an
already-applied migration or claiming the missing historical ADR was present.

## Decision

Set the committed worker start command to
`env FEL_WORKER_DB_ROLE=fel_worker python -m fel_workers run`. The explicit
non-secret value overrides an inherited blank or different service variable.
The existing connection setup selects the role before queue operations; failure
to select it stops startup. Local library/CLI use retains its existing opt-in
switch. This change neither broadens grants nor changes tenant policy.

Keep the migration-ledger check in the separate pre-deploy process, outside
the runtime role selection. Operators provision login membership in
`fel_worker` and keep migration authority separate from runtime credentials.
`SET ROLE` constrains subsequent normal worker operations; selecting it from
an owner/superuser login is not a security boundary against arbitrary malicious
SQL capable of resetting the role. Hosted acceptance must therefore record the
runtime login as well as effective role, without exposing a connection string.

## Verification and rollout

Run existing worker role/entrypoint tests, migration-0008 grant harness and
worker integration paths against a disposable database with the role selected.
Exercise the exact committed start command in isolated mock mode and confirm
its sessions enter `fel_worker`; confirm startup does not process jobs when the
configured login cannot select that role. Preserve the migration check,
watchdog and health configuration.

A merged configuration does not prove an existing Railway service uses it.
Issue #190 remains open until an approved hosted restart verifies the configured
command, runtime login, effective `current_user = fel_worker`, permitted worker
writes and refused deletion/DDL. No deployed credentials or paid provider use
are authorized by this document.

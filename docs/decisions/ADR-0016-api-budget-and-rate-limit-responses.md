# ADR-0016: API budget and rate-limit responses

Status: Accepted  
Date: 2026-09-09  
Occasioned by: #191, #203 and PR #232

## Authorization

The integration lead authorized PR #232 to carry its own additive contract
release in [the owner ruling](https://github.com/wilsonhj/financial-evidence-lab/pull/232#issuecomment-5556734058).
The [subsequent owner comment at commit `3a8384b`](https://github.com/wilsonhj/financial-evidence-lab/pull/232#issuecomment-5574302643)
narrowed that scope to the responses actually implemented. Acceptance records
that existing decision, rather than a new ratification in this session;
it does not authorize the deferred list or reader limits. The repository owner
requested review, fixes and merge of the open PRs in the 2026-09-09 session.
The integration order below is the implementation choice made during that
authorized review; the historical comments left merge order to integration.

## Decision

- Release the API hardening contract as 0.5.0 before the claims-output release.
- Declare 402 `COST_LIMIT_EXCEEDED` on query creation and rerun, using the
  existing error envelope. Declare 429 via the reusable `RateLimited` response
  with `Retry-After` on query creation, rerun and retrieval feedback.
- Keep budget admission serialized by organization and persist an immutable
  reservation with the queued run. Persist actual usage with terminal state.
  Unreconciled reservations remain held after persistent database failure.
- Reuse PostgreSQL and the existing audit/usage tables; no migration, new
  service, or change to tenant policy is needed. Pooled connections retain
  transaction-scoped role and claim setup. Normalize organization UUIDs before
  selecting a process-local rate-limit bucket.
- Do not declare pagination or reader-size errors until their implementation
  and consumers land together under #191. Current rate limiting is per API
process; distributed rate limiting and billable-provider enforcement remain
  explicit production-readiness work rather than guarantees of this release.

## Affected packages and compatibility

`apps/api` implements the responses; `packages/contracts` publishes the additive
OpenAPI version and regenerated TypeScript client. Existing successful response
shapes and list behavior are preserved. The pool extra belongs in production
`requirements.txt`; the development requirements inherit it.

PR #241 follows with contract 0.6.0 and ADR-0015. Its integration must retain
both this release's cost threading and its own typed generation abstention.

## Verification and consequences

Contract parity and generated-client checks must pass. PostgreSQL tests must
prove concurrent budget admission, caller attribution on rerun, idempotent
replay, atomic terminal metering, persistent-failure reservations, and tenant
state isolation across pool borrowers. Rate-limit tests must prove equivalent
UUID spellings share a bucket and exhausted buckets return `Retry-After`.

No provider credential is required. Local tests without PostgreSQL are not
evidence for these database guarantees; the PR's fresh database-backed CI is
the merge gate. #191 and #203 remain open for their documented residual scope.

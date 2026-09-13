# ADR-0025: Production token verification behind the existing tenant boundary

Status: Accepted for offline implementation after independent design review and integration-lead approval (2026-09-13)

Date: 2026-09-13

Issue: #292, production-auth residual of T0004; related #177 and #188

## Problem

The only implemented verifier accepts unsigned mock tokens. Credentials alone
cannot activate production identity verification. Keep #108's accepted mock-auth
hosted reader-smoke exception; its evidence-path proof does not certify identity.

## Decision

Use the existing TokenVerifier/TenantContext boundary. Verify Supabase asymmetric
access tokens with PyJWT[crypto], mapping UUID sub and trusted app_metadata.org_id
only. Do not infer organization membership or consult user_metadata. Supply viewer
as the candidate FEL role; existing PostgreSQL membership resolution supplies the
authoritative role on each request and extraction stream reauthorization.

Configure an exact HTTPS issuer and audience; allow only ES256/RS256 and require
essential identity/time claims with explicit30-second skew. Use a fixed trusted
JWKS destination, bounded HTTP reads and finite public-key cache. Apply refresh
cooldown to successful and failed attempts, including missing/expired cache, so
an outage cannot cause each waiting request to fetch again. No indefinite key
cache, token-derived URL or algorithm policy, symmetric-secret verification,
mock fallback, or immediate session-revocation guarantee is introduced.

The bounded implementation plan specifies exact limits, claim/error semantics,
timeout limitations, offline key/transport tests, RLS regressions and deployment
conditions: `../superpowers/plans/2026-09-13-production-auth-verifier.md`.

## Dependency and path authorization

Add reviewed PyJWT[crypto] and direct existing-httpx requirements in API metadata
and runtime input, resolve necessary runtime/dev lock changes with existing tools,
and prove clean production installation and audits. Do not mutate the shared
immutable test environment or update unrelated dependencies. No migration, wire
schema, generated contract, worker/provider, web or extraction-path change.

Register PRODUCTION-AUTH-VERIFIER under #292 with tasks[] to preserve the sole
canonical ledger. The implementation branch is agent/292-production-auth-api. Dispatch follows
merge of this reviewed design; the present design branch is agent/292-production-auth. Hosted
identity provisioning/testing remains separately environment-authorized; the
offline implementation does not request or publish actual keys or user tokens.

## Verification

Require generated offline signature fixtures, claim/algorithm/key confusion
rejections, bounded trusted-key retrieval/cache/rotation/outage proofs, real
PostgreSQL role/membership/tenant tests, unchanged mock regression behavior,
security audits and reproducible installs. Independent review, explicit lead
approval and exact-head required CI precede merge. Canonical completion and
hosted acceptance are not inferred from the offline package.

## References

- https://supabase.com/docs/guides/auth/jwts
- https://supabase.com/docs/guides/auth/signing-keys
- https://pyjwt.readthedocs.io/en/stable/api.html
- https://github.com/wilsonhj/financial-evidence-lab/issues/108#issuecomment-5028634088

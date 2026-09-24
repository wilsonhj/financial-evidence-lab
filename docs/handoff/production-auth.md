# Production authentication deployment notes

Issue #292 implements accepted ADR-0025's offline verifier. It does not provision
identities, enable hosted access, or certify the web application's login flow.

## Server configuration

- Set `FEL_AUTH_MODE=supabase` explicitly for production identity verification.
- Set `FEL_AUTH_ISSUER` to the exact HTTPS issuer in issued access tokens, without
  credentials, a query, fragment, or trailing slash. Hosted and self-hosted issuer
  paths can differ; copy the approved issuer configuration rather than guessing.
- `FEL_AUTH_AUDIENCE` defaults to `authenticated`; an override must match the
  intended access-token audience exactly. Audience arrays are rejected.

The single public-key endpoint is the configured issuer followed by
`/.well-known/jwks.json`. The API needs no Supabase signing secret or service-role
key to verify asymmetric ES256/RS256 tokens. Legacy HS256 tokens are unsupported;
there is no fallback to mock verification or another identity server. Missing or
invalid configuration fails closed. Mock mode remains available for the explicitly
accepted #108 evidence smoke and local fixtures; leaving the historical default
unset does not enable production identity verification.

Trusted identity administration must populate `app_metadata.org_id`. The verifier
requires UUID values for that organization and the token's `sub`, then normalizes
their spelling. It never reads `user_metadata` or falls back to top-level `org_id`.
The `memberships` table is authoritative: a verified candidate starts with the FEL
role `viewer`, and each request resolves its actual database role. A token's
`role` cannot grant application permissions. Tokens alone do not provision a user
or membership, and users may have multiple organization memberships.

## Runtime limits and failure behavior

Access tokens are limited to 16 KiB; key IDs to 128 UTF-8 bytes; a JWKS document
to 64 KiB and 32 public keys. Retrieval requests identity encoding and rejects
compressed responses, redirects, malformed documents, duplicate IDs and private
or symmetric key material. Claim validation requires `iss`, `aud`, `sub`, `exp`
and `iat`, checks optional `nbf`, and allows 30 seconds of clock skew. Numeric
dates must be finite integers, not strings or booleans.

One verifier is retained for the configured issuer/audience. A successful public
key set lives for at most 300 seconds. Every refresh attempt starts a 30-second
cooldown, including failures and initially empty or expired caches. Unknown key
IDs cannot create unbounded cache entries. Known, unexpired keys remain usable
during refresh or outage; expired keys are never used. Failed refreshes neither
extend the previous TTL nor publish a partial key set.

Key-service operations use one-second connect/read/write/pool timeouts and a
two-second elapsed budget checked around streamed chunks. These are not a hard
wall-clock deadline: a blocking transport operation, particularly OS DNS lookup,
can overshoot. Refresh-lock waiting is limited to one second, and key retrieval
does not hold a database connection.

Invalid tokens receive a safe `401 UNAUTHENTICATED`. A successful unexpired key
set with an unknown ID receives 401 during its refresh cooldown. An unavailable
key service with no usable key receives `503 AUTH_UNAVAILABLE`; failed refreshes
are not retried by each waiting request. Configuration failures also return safe
503 errors. Error responses contain no token, key material, or configured URL.

Restart the API processes to purge their key caches during rotation/revocation.
Supabase's upstream JWKS cache can add ten minutes of delay; a process restart
does not purge that upstream cache. Follow the issuer's documented rotation
procedure. This implementation does not promise immediate session/key revocation.
Already-open streams retain their original identity, while their existing batch
checks re-resolve database membership; reconnects verify the access token again.

## Acceptance and remaining rollout work

Offline tests generate disposable EC/RSA signing keys and inject HTTP transports.
PostgreSQL tests verify database roles, membership removal and tenant isolation.
Runtime and development locks include the cryptography extra; deployments use
the existing hash-verified `scripts/runtime/install.sh` workflow.

Hosted issuer configuration, organization assignment and identity acceptance
require the separately approved environment and secret-delivery process. Preserve
#108's scoped mock-auth exception, #177's live acceptance conditions and the
canonical task ledger; this package does not clear those gates.

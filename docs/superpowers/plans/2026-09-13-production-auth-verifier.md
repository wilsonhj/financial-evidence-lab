# Production token verification design — issue292

Status: Proposed; offline implementation dispatch awaits independent design review and registered paths. Hosted authentication remains separately credentialed. No provider substitution or OpenAI code is involved.

## Existing boundary and selected behavior

Keep TokenVerifier.verify(token)->TenantContext and tenant-context/v1 unchanged. In FEL_AUTH_MODE=supabase, validate an asymmetric Supabase access token and map canonical UUID sub plus app_metadata.org_id to user_id/org_id. The candidate role is fixed viewer until the existing database membership lookup supplies the actual FEL role. Do not read user_metadata, accept top-level org_id as fallback, select a first membership, or interpret Supabase role=authenticated as a FEL permission. Missing/malformed identity fails before database access. Organization assignment must be performed by the trusted identity administrator; this slice does not build assignment/login/organization-switching UI.

Retain explicit mock mode and #108's accepted mock-auth hosted evidence-smoke exception. Supabase mode never falls back to mock. Unsupported mode/missing deployment config fails closed. No claim of immediate session revocation: cryptographic access-token verification obeys token expiry; local membership revocation is enforced by the existing request/batch lookup.

## Configuration and verification

Use exact server configuration FEL_AUTH_ISSUER (HTTPS URL without credentials/query/fragment), FEL_AUTH_AUDIENCE (default authenticated), and fixed allowed algorithms ES256/RS256. Derive the single JWKS URL from the configured issuer plus /.well-known/jwks.json; never use unverified iss/jku/x5u/jwk URLs to fetch keys. Reject insecure issuer configuration; offline tests inject transport rather than weakening URL validation. Exact issuer avoids the self-hosted /auth/v1 path change and custom-domain ambiguity. Keep an explicit trailing-slash normalization policy: reject a trailing slash rather than silently rewriting the issuer used for validation.

Require iss,aud,sub,exp,iat. Validate exp/iat and optional nbf as finite integral numeric dates, excluding bool; fixed30-second skew. Require aud exactly authenticated unless explicitly configured otherwise; no array-audience permissiveness is needed initially. Reject unsupported critical JOSE extensions and detached/unencoded payload forms. Require a bounded nonempty kid; algorithm must match a supported public-key type and optional JWK alg/use/key_ops. No symmetric keys or client-supplied key material.

Use established PyJWT[crypto]>=2.14.0 with its cryptography backend, not custom signature code. Explicit algorithm allowlist and required-claim options remain separate. Existing httpx supplies trusted key retrieval. Add direct API package dependencies for the imports and runtime requirement floor; resolve/audit hashed runtime and dev locks in a NEW temporary environment, preserving the shared immutable environment and unrelated versions where possible. Existing build-tool lock should not change.

## Bounded retrieval and cache

At most16KiB token input,128-byte kid,64KiB JWKS response and32 keys. Reject duplicate key IDs, private/symmetric key material, malformed keys, redirects and wrong media/shape. Use explicit one-second connect/read/pool/write timeouts. Check a two-second elapsed budget before and after response chunks; these checks and phase/inactivity timeouts are not a strict two-second wall-clock deadline, especially during OS name resolution. Do not claim cancellation guarantees the synchronous transport does not provide. Read response incrementally to enforce bytes before JSON decode.

Keep one verifier cache per settings identity, protected against concurrent refresh. Cache verified public key set for at most300 seconds; never maintain an indefinite per-key cache. A fresh unknown kid may trigger one refresh subject to a30-second cooldown, with no per-attacker-kid cache growth. Set the attempt timestamp before every refresh, successful or failed, including expired or initially absent sets. During cooldown do not repeat a failed fetch for queued callers: a valid unexpired known key remains usable, otherwise return the safe unavailable result. Bound refresh-lock waiting and never hold a database connection during key retrieval. Expired cached keys are not usable during outage. Unexpired known keys may continue validating while their TTL is valid. A failed refresh must not extend the old TTL or replace a good set with partially parsed data. Clear through process restart/cache reset; document that Supabase's upstream10-minute cache adds revocation delay. No claim of immediate key/session revocation.

Invalid token/claims returns the existing safe401 envelope; transient key-service outage returns a safe503 through an explicit verifier-unavailable error without URL/token/key contents. Whether a fresh unknown kid during cooldown is401 or503 must be fixed in tests; propose401 when a valid cached key set was refreshed successfully,503 only when key retrieval is unavailable and no usable set can establish identity. Configuration errors are safe startup/request failures, not leaked exception strings.

## Test-first slices

1. Offline generated EC/RSA keys and frozen-clock tokens: valid identity, wrong signature/issuer/audience, missing/invalid dates, expired/early tokens, wrong alg/kid/key type, unsupported critical headers, malformed/oversized tokens, role and user_metadata ignored. No real tokens/keys in repository.
2. Injectable HTTP transport: fixed destination, redirect refusal, response bounds, malformed/duplicate keys, cache TTL, unknown-key cooldown, rotation, outage, concurrent single refresh, no stale TTL extension. No external requests.
3. Wire into config/dependencies; explicit mock remains unchanged. Real PostgreSQL membership tests prove verified viewer candidate becomes DB reviewer/owner only through existing resolution, non-member403 and cross-tenant hidden404. Reauthorize long-lived extraction stream batches as currently implemented.
4. Regenerate and inspect only necessary runtime/dev locks; clean production installation/import, Python/API tests, format/lint/type/security and audit. Independent implementation review and exact-head full CI before merge.
5. Hosted acceptance remains open until approved issuer/environment and secret delivery locations are supplied. JWT/JWKS validation itself needs public keys, not a Supabase service-role key. No deployment or live identity provisioning in offline slice.

## Registration

Proposed workstream PRODUCTION-AUTH-VERIFIER under292, tasks[] (historical T0004 residual remains linked, not duplicated), depends_on[], branch agent/292-production-auth. Allowed exact auth.py/dependencies.py/config.py/new supabase_auth.py, focused auth test files, apps/api/pyproject.toml, requirements.txt/requirements.lock/requirements-dev.lock, accepted new ADR0025, dedicated implementation plan and deployment notes. Root alone registers workstreams/ADR; no extraction/main/pagination/web paths or migration changes.

## Sources checked September13

- https://supabase.com/docs/guides/auth/jwts
- https://supabase.com/docs/guides/auth/signing-keys
- https://supabase.com/changelog/47093-self-hosted-supabase-api-external-url-to-include-auth-v1
- https://pyjwt.readthedocs.io/en/stable/api.html

These support the verification primitives; numeric budgets and claim-mapping selections above are proposed FEL policy, not vendor requirements.

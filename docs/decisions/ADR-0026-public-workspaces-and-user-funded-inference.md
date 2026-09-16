# ADR-0026: Public private-workspace access and user-funded inference

Status: Accepted for bounded implementation under the owner's September 16 plan approval

Date: 2026-09-16

Issues: #324 (public access/BYOK), #323 (OpenAI baseline), #188 (coordination)

## Decision and evidence

The owner requested public signup, confidential private workspaces, and a staged
OpenRouter connection followed by direct OpenAI/Anthropic keys, and explicitly
prohibited other users consuming the owner's API credits. The owner subsequently
instructed implementation of the reviewed completion plan. Current reader,
Observatory and extraction web bindings use a deployment-wide bearer/workspace;
that implementation does not isolate public users. This ADR authorizes the
security and contract prerequisites for the requested product addition. It does
not certify public readiness, grant a paid budget, or promote another model.

- Public business requests require request-scoped verified identity and database
  membership. Dedicated mock-auth reader smoke remains a distinct authorized mode.
- Every billable operation uses an explicitly selected credential owned by the
  initiating user in the organization. No owner-key fallback exists, including
  embeddings, verification, retries and background jobs. Missing/revoked keys
  fail before a provider call. Infrastructure quotas still apply to BYOK users.
- Initial public credential flow is OpenRouter S256 PKCE with server code exchange;
  direct OpenAI and Anthropic keys are a later independently reviewed package.
  Credential encryption uses the already locked cryptography Fernet/MultiFernet
  library with an explicit deployment-managed keyring outside the database.
  The authenticated encrypted payload binds purpose, credential, user and
  organization identity, checked on decrypt. This deliberately narrows the
  generic envelope/KMS proposal: it adds neither AWS nor a home-grown cipher.
  Queue messages carry references only. #327 owns the offline primitive;
  persistence, authorization, key delivery and hosted acceptance stay separate.
- Credential metadata can be read by its owner; plaintext cannot be read back.
  Secrets are excluded from prompts, logs, errors, URLs, traces and artifacts.
  Routing endpoints are fixed/allowlisted; no user-supplied upstream URLs.
- Confidential-data routing requires an approved serving-provider policy. Unknown
  retention/training policy fails closed. No silent provider/model fallback.
- OpenAI remains the accepted model baseline. Provider comparison is isolated,
  public-data-only research until benchmark evidence and a promotion ADR exist.
  This ADR is not acceptance of proposed ADR-0012 or an alternative model pin.

## Staging and compatibility

Before public auth runtime changes, freeze additive contracts for onboarding,
credential metadata/lifecycle, usage authorization and deployment modes. Publish
their migration and least-privilege proof in a separate reviewed contract PR.
The existing verifier, deterministic financial engine, human review requirement,
tenant anti-oracle semantics and immutable evidence identities remain binding.

Offline OpenAI adapters #323 (structured) and #326 (embeddings) are independently
dispatchable under ADR-0002. Each
accepts an explicit key, pinned model and prices; it never reads deployment keys.
changes no frozen interface, automatically activates no provider, and performs
no paid call during tests. Usage and worker/API wiring require subsequent review.

## Validation and rollout

Public deployment remains gated on two-user browser/API isolation, credential
ownership/revocation, no secret-canary leaks, session/CSRF/cache checks, durable
cost boundaries and hosted identity verification. #108 mock-auth smoke is not
this acceptance. Standard required CI, independent review and lead approval apply.
No canonical task is marked complete by this decision.

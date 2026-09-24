# ADR-0027: Explicit deployment modes and public shared-identity refusal

Status: Accepted for bounded implementation under the owner's instruction to continue the approved plan

Date: 2026-09-16

Issues: #333, #334, #335; parent #324. Extends ADR-0026 without changing the accepted stack.

Missing deployment mode means public. Public web business routes remain unavailable until request-scoped sessions exist; public API clients may continue using independently verified Supabase identities. No shared deployment bearer can substitute for a public web user's identity. Health/static endpoints remain available.

Select four explicit modes: public, fixture, reader-smoke, synthetic-http. The fourth preserves the already accepted local extraction/load HTTP workflow without mislabeling it reader smoke or allowing networked fixture fallbacks. Named storage markers and manifest identity checks prevent accidental target mixing; they are configuration safety checks, not protection against an operator controlling environment/storage. Exact policy is frozen in `docs/research/deployment-guard-contract.md`.

Use Next's existing Proxy request boundary for literal HTTP503, plus source-factory checks for server actions and direct invocation. An error UI alone cannot prove HTTP status. Add no session/cookie/SDK/provider dependency, published FastAPI error code, schema migration or paid resource. The API uses existing AUTH_UNAVAILABLE.

The default intentionally disables business access on unconfigured/shared-identity web deployments. Document the change and configure only dedicated synthetic targets explicitly; never infer a trusted mode from NODE_ENV, request headers, query parameters or hostnames. No public readiness or canonical task completion is claimed. API/web/harness changes must be reviewed and integrated together before merging the default flip.

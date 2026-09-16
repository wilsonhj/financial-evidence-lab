# Deployment guard: frozen implementation contract

September 16, 2026; ADR-0027; #333 integration, #334 API, #335 web. This narrow contract supersedes the three-mode guard proposal in `public-auth-byok-contract.md`. Other public-session/custody contracts remain Proposed.

## Common rules

`FEL_DEPLOYMENT_MODE` must exactly equal public, fixture, reader-smoke or synthetic-http. Unset means public; empty, padded or unknown values fail closed. Deployment environment is trusted operator configuration, never selected by HTTP inputs. Target syntax is `[a-zA-Z0-9][a-zA-Z0-9_-]{2,79}`. Marker files contain exactly that target, with no newline; bound reads to 81 bytes and reject errors/extra bytes. No error exposes config values, tokens, identities or marker paths.

The guard does not provision keys, authenticate public web sessions or guarantee a dedicated target against an administrator who controls storage/config. Existing dedicated harness preflights and real tenant checks remain required. No live provider or real user credentials are introduced. Public rollout remains blocked on ADR-0026 acceptance.

## API policy

Check in get_verifier before verifier construction/token verification/membership lookup. Settings remain importable and health endpoints reachable; lifespan pool startup is unchanged.

- public: require auth_mode supabase; preserve existing verifier and database membership checks. Mock/unknown auth is unavailable.
- fixture: API business authentication unavailable (web-only offline fixtures).
- reader-smoke: require auth_mode mock, valid FEL_READER_SMOKE_TARGET and matching `.reader-smoke-target` under FEL_STORAGE_DIR. Existing reader controller enforces manifest/revision/target details. No extra loopback requirement for the separately authorized hosted reader target.
- synthetic-http: require auth_mode mock, FEL_ALLOW_MOCK_LLM exactly1, valid FEL_SYNTHETIC_HTTP_TARGET and matching `.synthetic-http-target` storage marker. Parse PostgreSQL connection info; require host exactly localhost,127.0.0.1 or ::1 (one explicit host, no socket/multihost/alternate hostaddr bypass). This is local-only. Existing load runner retains its fel_load* database restriction; cross-stack seeder requires its dedicated local acceptance database.

Every refusal uses existing503 AUTH_UNAVAILABLE with fixed safe message. Proof failures never fall back to mock/public/fixture. No new API schema/version/error is needed. Unit/DB fixtures explicitly configure synthetic mode with temporary storage/marker; they do not monkeypatch guard/verifier enforcement. Guard tests override/clear that setup deliberately. Independently selected Supabase tests use public.

## Web policy

Use one server-only guard from evidence and Observatory runtime loaders; extraction already delegates to Observatory. Guard before parsing/returning a source, not after an HTTP request. Preserve typed guarded configuration errors.

- public: refuse all business requests until sessions exist, regardless of valid shared bearer, workspace/entity settings or fixture source.
- fixture: FEL_EVIDENCE_SOURCE exactly fixture; reject a nonempty FEL_API_BEARER_TOKEN. Committed offline sources only.
- reader-smoke: HTTP source, explicit mock auth, valid FEL_READER_SMOKE_TARGET, existing valid fixed HTTP bindings. Token must be a valid bounded mock token or the literal `invalid` used only by the isolated unauthorized smoke variant. Preserve denied-user mock token. No production JWT is accepted as a smoke bearer. Hosted remote preflight continues comparing target, revisions, identities, as-of and API storage marker; web does not pretend to possess the API's private filesystem.
- synthetic-http: HTTP source, mock auth, FEL_ALLOW_MOCK_LLM exactly1, valid FEL_SYNTHETIC_HTTP_TARGET, loopback-only API URL without credentials/query/fragment, and CROSS_STACK_MANIFEST file at most16KiB. Strict JSON exact shape: the existing ten UUID fields org,user,workspace,entity,policy,document,version,section,span,corpus plus schema_version=`extraction-cross-stack/v1` and target matching FEL_SYNTHETIC_HTTP_TARGET. Canonical lowercase UUIDs; manifest bytes must be the UTF-8 JSON serialization with lexicographically sorted keys, no whitespace and no trailing newline. Validate by parsing and exact canonical re-encoding comparison, which also rejects duplicate keys. Fail closed on read/parse errors. Token's exact mock org/user/owner role and configured workspace/entity must match manifest; no extra entities. Load is API-only and needs no web manifest. Parser may use existing dependencies only; no hand-waved duplicate-key acceptance.

The marker/schema additions are made by the registered synthetic harness integration. Generic HTTP protocol unit tests may retain injected configs; production factory tests must exercise the real guard.

## HTTP boundary

Add Next16 `src/proxy.ts`, no runtime export. Constant matchers: /, /desk/:path*, /reader/:path*, /observatory/:path*, /extractions/:path*, /extraction-runs/:path*, /approved-extractions/:path*, /api/extraction/:path*. Public, missing and invalid mode return503 before page/action/SSE execution; use static safe text for pages and existing web error-envelope shape with code PUBLIC_AUTH_NOT_READY for API paths, Cache-Control:no-store. Invalid nonpublic proofs also fail closed. /api/health, static assets and the existing separately gated telemetry endpoint remain available.

Factories and direct extraction route handlers must refuse safely even when invoked without Proxy. For public/missing mode return the same code from direct extraction handlers; other existing typed errors remain compatible. Server actions must not fetch upstream when guarded. This web-local unavailable code does not change the published FastAPI contract.

## Acceptance and integration

Failing-first tests prove otherwise-valid shared configuration makes zero fetches in public mode across evidence, Observatory and extraction. Verify mode/proof matrix, bounded malformed manifests/markers, invalid/denied smoke variants, public Supabase preservation and zero membership calls for public mock. Production-build HTTP tests cover all matched route families, action POST/RSC/prefetch/SSE, trailing slash behavior and health200. A normalized redirect may precede the final503; it may not reach business data.

Lead propagates explicit modes/targets into fixture Playwright, both HTTP smoke configurations, invalid/denied subprocesses, remote environment assertions, local load runner and required CI. Synthetic seeders create markers only after dedicated-target checks and refuse a pre-existing mismatched marker. Re-run existing real HTTP/worker/browser acceptance and local reader workflow; do not relax workload, time, privacy or correctness gates. Record hosted limitations separately.

Rollout: unconfigured public/shared-bearer services lose business access by design; health must use the health endpoint. Do not silently opt a real public service into a smoke mode to restore access. No public session readiness is claimed.

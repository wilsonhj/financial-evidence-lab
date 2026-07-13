# ADR-0004: Public corpus tables carry no org_id and no RLS

Status: Accepted
Date: 2026-07-13
Occasioned by: PR #80 / issue #54

## Decision

The **public-evidence** corpus tables introduced by
`db/migrations/0002_corpus_core.sql` — `documents`, `document_versions`,
`sections`, `source_spans`, `tables_meta`, `financial_facts`,
`corpus_versions`, `corpus_version_documents` — intentionally carry **no
`org_id` column and no row-level security**, unlike the tenant-scoped tables
of migration 0001.

The two **operational** tables in the same migration —
`ingestion_quarantine` (malformed-source diagnostics) and `ingestion_runs`
(job ledger) — are **explicitly excluded from this exemption**. They hold
pipeline diagnostics and operational metadata, not public SEC/FRED evidence,
and their access design is a separate open finding (see "Operational tables"
below), not disposed of by this ADR.

Tenant isolation in this system applies to *analysis objects* — workspaces,
claims, extractions — never to public source evidence. The corpus is public,
shared, immutable data (SEC filings, macro series): every tenant reads the
same corpus, and per-tenant copies or row filters would add cost and
migration risk while protecting nothing.

Access control is enforced at two other layers instead:

1. **Write path**: only ingestion workers, running under the service role,
   write corpus rows. The API role `fel_app` holds `SELECT` only (no
   INSERT/UPDATE/DELETE grant exists), making the corpus append-only from
   the application's point of view.
2. **Read path**: the corpus API routes (`apps/api/app/corpus.py`) require
   an authenticated tenant context (`get_tenant_context`) and execute under
   `SET LOCAL ROLE fel_app`. Anonymous requests receive 401; authenticated
   non-members receive 403 — public data, but not an unauthenticated
   endpoint.

## Operational tables (excluded; open P1)

The 0002 migration as reviewed grants `fel_app` `SELECT` on
`ingestion_quarantine` and `ingestion_runs` alongside the evidence tables.
That grant is **not** covered by this ADR: quarantine rows and the job
ledger are operational diagnostics whose tenant readability is a recorded
open P1 (issue #54, integration-lead record of 2026-07-13, preserved — not
disposed — by the subsequent authorization). Before PR #80 merges, that
finding must be resolved on its branch by either

- removing the two tables from the `fel_app` grant (operator/service-role
  access only), or
- documenting and testing a separate least-privilege design (e.g. RLS or a
  filtered view) with its own review.

Whichever resolution lands, these tables follow the analysis-object rule,
not the public-corpus rule.

## Boundaries of this decision

- Any table holding tenant-created or tenant-derived data — including
  annotations on corpus objects, saved queries, or extraction results —
  MUST carry `org_id` and RLS per 0001's conventions. Attaching a tenant
  overlay to corpus rows does not inherit this ADR's exemption.
- If a future source is licensed or otherwise non-public (e.g. paid market
  data with redistribution limits), its storage does not qualify as "public
  corpus" and needs its own access-control decision before ingestion.
- The single-active `corpus_versions` pointer and the append-only posture
  are part of the contract: retrieval milestones (M2) may rely on corpus
  immutability under `fel_app`.

## Context

M1-INGESTION (PR #80, issue #54) required corpus storage. `db/migrations/**`
is a shared path in both `AGENTS.md` and `workstreams.yaml`, and issue #54
lists it as forbidden, so the migration shipped as a flagged deviation
requiring integration-lead sign-off. Line-level review (PR #80 thread,
2026-07-13) verified the migration is strictly additive — only
`CREATE TABLE`/`CREATE INDEX`/`GRANT` on new objects, no
`ALTER`/`DROP`/`REVOKE` touching 0001 objects — and confirmed the SELECT-only
grant and the authenticated read path described above. The tenancy rationale
is also documented in the migration's header comment; this ADR is the durable
decision record that header points back to.

## Consequences

- M2-RETRIEVAL and later packages may join corpus tables freely without
  tenant predicates, and may treat published corpus versions as immutable.
- Security review of corpus endpoints focuses on the two enforcement layers
  above (role grants, tenant-context dependency), not on RLS policies.
- Adding RLS to these tables later would be a `contract-change` with its own
  ADR, since downstream query plans and tests will assume its absence.

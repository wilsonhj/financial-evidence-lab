# ADR-0023: Model and forecast storage boundaries

Status: Accepted for the design-only #197 residual under the owner's backlog instruction

Date: 2026-09-10

## Context

Issue #197 requested three platform organization foreign keys, a disposition
for the reserved active-scenario pointer, and a data-model sketch in the
canonical plan before #63 began. Migration 0009, merged in PR #239, implements
the foreign keys and documents the pointer's future composite constraint.
The sketch was omitted. #63 subsequently merged in PR #212; that historical
ordering requirement was missed and cannot be satisfied retroactively.

The engine now has immutable content-addressed snapshots, sparse scenarios,
formula ASTs and explicit iteration groups. Persistence must preserve those
contracts rather than replace them. This decision completes the missing design
and makes ownership explicit; it creates no tables or HTTP contracts.

## Decision

Add the M4/M5 storage sketch to section 7 of the canonical implementation plan.
Use tenant/workspace-scoped database identities separately from unchanged
engine hashes. Store the engine's canonical snapshot bytes and immutable input
pins; normalized nodes and edges are transactional query projections of that
same snapshot. Preserve valid branching and restore by deriving a new version.

Deliver graph/scenario storage and the active-scenario composite foreign key
with #64's contract slice. Deliver forecast storage with #66 and export storage
with #68. Each slice requires its own reviewed additive migration, frozen
contracts, runtime enforcement and database harness. #61 must supply the
approved extraction-version contract before #64 can bind source facts.
Existing milestone dependencies and live exit gates remain binding.

All tenant references must enforce their organization and relevant workspace,
graph/version scope, not merely reference an existing UUID. The future scenario
migration must preflight every non-null reserved pointer and fail on invalid
references; it must not silently delete, null or reassign existing data.

Use existing authenticated API/worker role boundaries and explicit grants/RLS.
No new browser database access or privileged client key is introduced. This
also avoids relying on Supabase's changing default grants: see the
[April 28 Data API change](https://supabase.com/changelog/45329-breaking-change-tables-not-exposed-to-data-and-graphql-api-automatically)
and [RLS guidance](https://supabase.com/docs/guides/database/postgres/row-level-security),
checked September 10. The changelog explicitly leaves direct Postgres clients
unaffected; this repository uses those clients for its API and worker.

## Scope and acceptance

The integration lead authorizes only this ADR, canonical plan section 7 and
ARCH-SCHEMA-HYGIENE's design dispatch/evidence in workstreams.yaml for the #197
PR, plus marking the verified wave 6 control PR #273 merged. Its contract-change label is required. No canonical task checkbox changes,
root configuration, migrations, API/provider code or financial calculations
are authorized by this design slice.

Verify the existing migration 0009 harness on isolated PostgreSQL, review the
sketch against engine snapshot/scenario contracts, and run current CI. The
issue's implementation residuals remain explicit under #64/#66/#68, rather
than being certified by this document. Closing #197 may acknowledge the fixed
hygiene and completed design after review; it must disclose the missed historical
ordering and link those owning issues. It is not M4/M5 implementation acceptance.

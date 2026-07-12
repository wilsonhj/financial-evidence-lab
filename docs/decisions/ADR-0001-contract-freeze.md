# ADR-0001: Contract-first parallel delivery

Status: Accepted

## Decision

Freeze repository boundaries and public contracts after `M0-SCAFFOLD` and `M0-CONTRACTS`. Parallel agents consume versioned contracts and fixtures. Shared contracts change only through an ADR and integration-lead approval.

## Rationale

Independent agents can safely implement UI, providers, retrieval, and calculations only when identifiers, schemas, temporal semantics, and package boundaries are stable. Contract-first delivery reduces merge conflicts and prevents silently incompatible implementations.

## Consequences

- Feature teams may be temporarily blocked by an explicit contract decision.
- Fixture-driven parallel work is preferred over waiting for live services.
- Contract PRs are small, separately reviewed, and merged before dependent changes.
- Fable schedules only packages compatible with the current contract version.

# Architecture decision records

Each file in this folder records one architecture or process decision: its context, the decision, and its consequences. To add one, take the next unused four-digit number and name the file `ADR-NNNN-short-kebab-title.md`, with an `# ADR-NNNN: Title` heading followed by `Status:` and `Date:` lines. This folder is a shared path: per `AGENTS.md` "Shared paths", every change under `docs/decisions/**` needs the `contract-change` label, an accepted ADR, and integration-lead review.

The Status column below is abbreviated. Many ADRs qualify their status with a longer sentence (for example "Accepted for implementation under ..."); those rows show "Accepted (qualified)". The `Status:` line in each ADR file is authoritative.

| ADR | Title | Status | Date | Supersedes / Superseded by |
|---|---|---|---|---|
| [ADR-0001](ADR-0001-contract-freeze.md) | Contract-first parallel delivery | Accepted | 2026-07-12 | — |
| [ADR-0002](ADR-0002-mvp-stack.md) | Locked MVP technology stack | Accepted | 2026-07-12 | — |
| [ADR-0003](ADR-0003-root-config-edits.md) | Mechanical root-config edits ride with the owning package | Accepted | 2026-07-13 | — |
| [ADR-0004](ADR-0004-public-corpus-tenancy.md) | Public corpus tables carry no org_id and no RLS | Accepted | 2026-07-13 | — |
| [ADR-0005](ADR-0005-reader-composite-endpoint.md) | Composite version-pinned evidence reader endpoint | Accepted | 2026-07-15 | Superseded in part (oversized-reader posture) by [ADR-0021](ADR-0021-bounded-api-pagination-and-reader.md) |
| [ADR-0006](ADR-0006-observable-retrieval.md) | Versioned observable retrieval and trace replay | Accepted | 2026-07-16 | — |
| [ADR-0007](ADR-0007-agentic-extraction-contract.md) | Bounded agentic-extraction contract and persistence | Accepted | 2026-07-16 | — |
| [ADR-0008](ADR-0008-python-package-scaffold-edits.md) | New first-party package scaffold wiring rides with the owning package | Accepted | 2026-07-19 | — |
| [ADR-0009](ADR-0009-checkpoint-payload-in-event-stream.md) | `step_completed.stage_output` carries evidence text, and the event stream is not metadata-only | Superseded | 2026-07-29 | Superseded by [ADR-0011](ADR-0011-extraction-step-output-column.md) |
| [ADR-0010](ADR-0010-cross-repo-pattern-adoption.md) | Cross-repo pattern adoption from avalanche and predict-rlm | Proposed | 2026-08-06 | — |
| [ADR-0011](ADR-0011-extraction-step-output-column.md) | Add `extraction_run_steps.output` so the checkpoint stops riding on the event payload | Accepted | 2026-08-29 | Supersedes [ADR-0009](ADR-0009-checkpoint-payload-in-event-stream.md) |
| [ADR-0012](ADR-0012-llm-provider-substitution.md) | Split the AI-provider decision by role, and supersede only ADR-0002's generation-provider clause | Proposed | 2026-08-31 | Proposes to supersede one clause of [ADR-0002](ADR-0002-mvp-stack.md) |
| [ADR-0013](ADR-0013-canonical-task-ledger-reconciliation.md) | Retrospectively authorize the PR #206 canonical task-ledger reconciliation | Accepted | 2026-09-03 | — |
| [ADR-0014](ADR-0014-migration-ledger-and-applier.md) | Checksummed migration ledger and single applier | Accepted (qualified) | 2026-09-02 | — |
| [ADR-0015](ADR-0015-claims-output-contract.md) | Structured claims output and independent numeric verification | Accepted | 2026-09-06 | — |
| [ADR-0016](ADR-0016-api-budget-and-rate-limit-responses.md) | API budget and rate-limit responses | Accepted | 2026-09-09 | — |
| [ADR-0017](ADR-0017-parallel-backlog-execution.md) | Bounded parallel backlog execution | Accepted (qualified) | 2026-09-09 | — |
| [ADR-0018](ADR-0018-formula-ast-and-explicit-iteration.md) | Formula AST and explicit iterative calculation groups | Accepted (qualified) | 2026-09-10 | — |
| [ADR-0019](ADR-0019-unit-comparison-policy.md) | Consistent unit comparison without rewriting source payloads | Accepted (qualified) | 2026-09-10 | — |
| [ADR-0020](ADR-0020-worker-role-rollout.md) | Select the worker database role in Railway startup | Accepted (qualified) | 2026-09-10 | — |
| [ADR-0021](ADR-0021-bounded-api-pagination-and-reader.md) | Bounded API pagination and evidence reads | Accepted (qualified) | 2026-09-10 | Supersedes in part [ADR-0005](ADR-0005-reader-composite-endpoint.md) (oversized-reader posture) |
| [ADR-0022](ADR-0022-guidance-range-ordering.md) | Signed guidance range ordering | Accepted (qualified) | 2026-09-10 | — |
| [ADR-0023](ADR-0023-model-and-forecast-storage-boundaries.md) | Model and forecast storage boundaries | Accepted (qualified) | 2026-09-10 | — |
| [ADR-0024](ADR-0024-extraction-review-and-conflict-occurrences.md) | Extraction review and conflict occurrences | Accepted (qualified) | 2026-09-10 | — |
| [ADR-0025](ADR-0025-production-token-verification.md) | Production token verification behind the existing tenant boundary | Accepted (qualified) | 2026-09-13 | — |
| [ADR-0026](ADR-0026-public-workspaces-and-user-funded-inference.md) | Public private-workspace access and user-funded inference | Accepted (qualified) | 2026-09-16 | — |
| [ADR-0027](ADR-0027-deployment-modes.md) | Explicit deployment modes and public shared-identity refusal | Accepted (qualified) | 2026-09-16 | — |
| [ADR-0028](ADR-0028-offline-calibration-primitives.md) | Offline extraction calibration preparation | Accepted (qualified) | 2026-09-16 | — |
| [ADR-0029](ADR-0029-retrieval-receipts.md) | Retrieval receipts for non-SEC provider fetches | Accepted | 2026-10-24 | — |
| [ADR-0030](ADR-0030-explicit-fred-missing-values.md) | Explicit FRED missing values | Accepted | 2026-10-24 | — |
| [ADR-0031](ADR-0031-named-source-clocks.md) | Named source clocks | Accepted | 2026-10-24 | — |
| [ADR-0032](ADR-0032-documentation-status-reconciliation.md) | Reconcile ADR and specification status with the repository | Proposed | 2026-10-31 | — |

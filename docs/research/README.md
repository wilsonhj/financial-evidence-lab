# Research notes

<details>
<summary>Relevant source files</summary>

- [docs/research/](./) — the documents indexed on this page
- [docs/research/ontology/](ontology/) — SaaS disclosure ontology research draft and issuer survey
- [specs/001-financial-evidence-lab/spec.md](../../specs/001-financial-evidence-lab/spec.md) — the canonical specification these notes are subordinate to

</details>

Source references verified against commit `437ce55`.

This directory holds research notes, audits, proposals, and frozen
implementation contracts written while planning work. They are inputs to
decisions, not the decisions themselves: the canonical specification, accepted
ADRs in [`docs/decisions`](../decisions/), and current `main` govern on
conflict. Most notes are dated snapshots of GitHub state and can lag recent
merges, so reconcile them against live issues before acting on them.

Dates are the date stated in each document; where a document states none, the
date it was first committed is used and marked "(committed)".

## Index

| Document | Date | Status | Summary |
| --- | --- | --- | --- |
| [RECONCILIATION-2026-07-16.md](RECONCILIATION-2026-07-16.md) | 2026-07-16 | Audit (historical) | Recovery of the PR #74 benchmark seed and PR #75 ontology research into `main`, with remaining promotion gates |
| [ontology/README.md](ontology/README.md) | 2026-07-16 | Research draft | Method and reconciliation status of the B2B SaaS disclosure ontology research (issue #73) |
| [ontology/saas-disclosure-survey.md](ontology/saas-disclosure-survey.md) | 2026-07-16 | Research draft | Raw per-issuer survey of nine SaaS metric families, preserved for provenance |
| [finrobot-cherry-pick-calc-engine.md](finrobot-cherry-pick-calc-engine.md) | 2026-07-20 | Proposal | Study of FinRobot's valuation engine and what a FEL-compliant calculation-engine port would need |
| [finrobot-cherry-pick-extraction-agents.md](finrobot-cherry-pick-extraction-agents.md) | 2026-07-20 | Proposal | Study of FinRobot's section agents mapped onto the frozen M3 extraction roles |
| [evals-report-renderer-proposal.md](evals-report-renderer-proposal.md) | 2026-07-29 (committed) | Proposal | Issue draft for a stdlib-only Markdown and SVG eval report renderer |
| [2026-09-09-open-issue-audit.md](2026-09-09-open-issue-audit.md) | 2026-09-09 | Audit | Read-only audit of the 39 open GitHub issues against trunk |
| [2026-09-09-backlog-resolution-spec.md](2026-09-09-backlog-resolution-spec.md) | 2026-09-09 | Review specification | Coverage and closure criteria for resolving the open backlog (umbrella #188) |
| [2026-09-11-model-scenario-design.md](2026-09-11-model-scenario-design.md) | 2026-09-11 | Research note | Storage boundaries for source-backed models and sparse scenarios (issue #64) |
| [2026-09-16-completion-spec.md](2026-09-16-completion-spec.md) | 2026-09-16 | Implementation specification | Remaining work to complete the product, including public signup and user-funded AI access |
| [public-auth-byok-contract.md](public-auth-byok-contract.md) | 2026-09-16 | Proposed contract | Public authentication sessions and bring-your-own-key inference design under ADR-0026 |
| [deployment-guard-contract.md](deployment-guard-contract.md) | 2026-09-16 | Frozen contract | `FEL_DEPLOYMENT_MODE` guard rules for API and web under ADR-0027 |
| [offline-calibration-contract.md](offline-calibration-contract.md) | 2026-09-16 | Frozen contract | Offline calibration dataset interchange and numerical primitives under ADR-0028 |

## Related pages

- [Architecture decisions](../decisions/)
- [Architecture overview](../architecture/overview.md)
- [System design](../architecture/system-design.md)
- [Ontology](../../packages/ontology/README.md) — the machine contract built from the ontology research
- [Retrieval evals](../../packages/retrieval-evals/README.md) — the compiler for the recovered benchmark seed

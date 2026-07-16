# M3 `/speckit.clarify` and `/speckit.analyse`

## Clarifications resolved with recommended defaults

| Question | Resolution |
|---|---|
| Orchestrator | Existing PostgreSQL jobs + persisted finite state machine |
| Agent count | All five parent-spec roles; three produce user proposals |
| Structured output | Additive `StructuredLLMProvider`; strict schema, one repair |
| Approval | Manual-only for all M3 proposals |
| Threshold purpose | Review priority/blocking; defaults 0.85 record/0.80 field |
| Currency | Identify only; no conversion |
| Comparability | Explicit ontology qualifier key; aliases do not collapse definitions |
| Rerun | New linked run; never mutate prior run/proposals |
| Merge | Compatible records only; union evidence; supersede inputs |
| Contradictions | M2-owned detector; M3 preserves conflicts |
| Events | PostgreSQL append-only event IDs + resumable SSE |
| Calibration | Pure deterministic isotonic v1; insufficient data fails closed |
| Budgets | 10 calls/100k input/20k output/USD2/600s hard defaults |

## Analysis findings and disposition

| Severity | Finding | Resolution |
|---|---|---|
| HIGH | No extraction persistence/RLS/contracts exist | ADR-0007 + serial contract/migration PR before implementation |
| HIGH | #60 cannot register a worker job or implement structured provider within allowed paths | Refresh #60 paths to narrow consumer/main/provider files after contract merge |
| HIGH | Parent spec names five agents while tasks/issues name three | Five typed roles explicitly scoped; classifier/fact-table roles route/contextualize |
| HIGH | Free-text provider lacks schema/model/usage/refusal contract | Add `StructuredLLMProvider` additive minor, mock and OpenAI adapter |
| HIGH | Temporal/corpus/version behavior was undefined | Run pins cutoff/corpus/input manifest; API and worker revalidate every source |
| HIGH | Review/merge/correction state transitions were ambiguous | Closed states/actions, ETags, idempotency, atomic batch, immutable versions defined |
| HIGH | API lacked the required approved-record correction mutation | Added If-Match/idempotent correction command that revalidates payload/evidence and appends an immutable child version |
| HIGH | Proposal/event payloads were untyped | Added `extraction-payload/v1` KPI/guidance/driver union, all-variant fixtures, and closed `extraction-event/v1` |
| HIGH | Confidence could be confused with approval | Manual-only approval; deterministic calibration; raw model score never approval score |
| HIGH | #62 appeared to own contradiction detection | Explicitly consume M2 report; no new detector/agent |
| MEDIUM | PR #75 is merged but later review found provenance/coverage gaps | Reconcile as advisory research; correct/track gaps before ontology v1 freeze |
| MEDIUM | No deterministic qualifiers for issuer metric conflicts | Ontology required qualifiers/comparability key defined |
| MEDIUM | Provider/schema repair could recurse | Exactly one initial + one repair attempt, global caps |
| MEDIUM | Service-role worker could bypass tenant isolation | Worker validates org/workspace ownership and scopes every write; RLS API negatives |
| MEDIUM | SSE replay/heartbeat unspecified | Identity event IDs, Last-Event-ID, 15–30s heartbeat |
| MEDIUM | Bulk review partial failure/races unspecified | Sorted locks, all-or-none transaction, per-item expected versions/412 |
| MEDIUM | One If-Match could not protect a multi-proposal batch | Require an expected version for every selected proposal; any mismatch atomically returns 412; reserve If-Match for one approved-record correction |
| MEDIUM | Step idempotency referenced a missing workflow-version column | Added `workflow_version` to persisted step rows and the unique successful-step key |
| MEDIUM | `waiting_review -> succeeded` and zero-proposal runs were undefined | Last all-terminal disposition with no open conflict succeeds; valid zero-proposal abstention succeeds explicitly; provider/schema/budget failure fails before review |
| MEDIUM | Calibrator tenant ownership was ambiguous | Classified calibrators as tenant-neutral release artifacts over approved non-tenant fixtures, SELECT-only to app/worker roles |
| MEDIUM | Numeric matching/calibration gates underspecified | Exact decimal/unit/period/sign/scale scoring and versioned isotonic artifact |

**Result:** Design-pass HIGH/MEDIUM items listed above were resolved in the Spec Kit package. A subsequent design review (PR #102) found contract/doc alignment gaps (migration numbering, create pins, cost ceiling, review reason, closed driver categories, research provenance wording). Those are addressed in the design-fix commit(s) on this branch. Remaining LOW items are implementation naming/layout choices governed by generated contracts and package tests.

## Constitution check

- Evidence/cutoff integrity: enforced at API, worker, persistence, review, and eval boundaries.
- Deterministic finance: Decimal normalization/calculation; LLM only proposes.
- Test first: failure/tenant/temporal/property/eval cases are task gates.
- Security/cost: fixed tools, untrusted-content boundary, RLS, redacted telemetry, hard budgets.
- Simplicity/provider isolation: existing services only; one narrow provider port; no new framework.

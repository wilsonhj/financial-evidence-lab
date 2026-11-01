# ADR-0033: Note the failing retrieval gate in the spec 002 quickstart

Status: Proposed
Date: 2026-11-01
Occasioned by: the post-merge review of #364, #365 and #366 (#363 follow-up)
Scope: one sentence group in `specs/002-observable-hybrid-retrieval/quickstart.md`, this ADR's row in `docs/decisions/README.md`, and nothing else

## Context

ADR-0032 decision item 3 made the spec 002 quickstart name only commands that
exist, and PR #366 did that. The quickstart now tells a reader to run
`make eval-retrieval-gate` and describes what it measures, but not that it
fails. Run at `main` @ `2bdea3f` against a local `pgvector/pgvector:0.8.5-pg17`
database, it prints `recall_at_10 0.4692 0.9000 FAIL` and
`temporal_validity 1.0000 1.0000 PASS`, reports `overall: FAIL`, and the make
target exits non-zero (`make: *** [Makefile:71: eval-retrieval-gate] Error 1`).

The failure is known and intended: the mock embedder carries little semantic
signal, the 0.90 threshold is canonical, and the live gate belongs to #177 and
#132 (see ADR-0012 Amendment 1 and the archived September status history). A
reader following the quickstart cannot tell this expected failure from a
broken setup.

`specs/**` is a shared path under `AGENTS.md`, and that class of edit needs an
accepted ADR. ADR-0032 creates no standing exception for later `specs/**`
edits, so this ADR is that authorization, modelled on ADR-0013 and ADR-0032.

## Decision

The integration lead authorizes exactly this correction:

1. In `specs/002-observable-hybrid-retrieval/quickstart.md`, in the paragraph
   that describes `make eval-retrieval-gate`, insert before its last sentence:
   that the gate currently fails and the command exits non-zero; the mock
   embedder's Recall@10 (0.4692) against the 0.9000 threshold; that temporal
   validity (1.0000) passes; that this is expected until live embeddings land
   (#177, #132); and that the threshold is not to be lowered.
2. Add this ADR's row to `docs/decisions/README.md`.

This ADR changes no threshold, gate logic, golden, contract, schema,
migration, lockfile, authentication boundary or cross-package interface, and
no decision content in any other ADR.

## Consequences

- A reader of the quickstart knows the expected result of the gate.
- When the live gate passes, the sentence goes stale. Removing it then needs
  its own authorization, like any other `specs/**` edit.

## Alternatives rejected

- **Leave the quickstart silent.** Rejected: an expected failure that is not
  documented reads as a broken environment.
- **Fold the note into an amendment to ADR-0032.** Rejected: ADR-0032 is
  Accepted and its verification is tied to the PR that added it.

## Verification

The authorization holds only if the PR that adds this ADR changes
`specs/002-observable-hybrid-retrieval/quickstart.md` by exactly the sentences
in "Decision" item 1, and changes no other file under `specs/**` or
`docs/decisions/**` beyond this ADR and its index row.

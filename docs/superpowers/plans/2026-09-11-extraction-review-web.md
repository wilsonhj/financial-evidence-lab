# Extraction review web implementation breakdown

Subordinate to accepted ADR-0024 and docs/superpowers/plans/2026-09-10-extraction-review.md.
PR #280 supplies the initial contract at c105f1b; event-ordering PR #283 is merged at 2e3f92b. Implementation waits for #284's candidate-read contract and explicit dispatch; this plan does not certify live acceptance.

## Boundaries

Own new apps/web/src/lib/extraction/**, components/extraction/**,
app/extractions/**, app/extraction-runs/**, app/approved-extractions/**,
app/api/extraction/**, colocated tests and e2e/extraction-review.spec.ts.
Only existing production change: minimal desk/page.tsx navigation link.
No root dependency/configuration or shared-contract edits by web owner.
Import components and operations from generated @fel/contracts; no manual wire-type mirrors.

Use the 0.9.0 generated ExtractionCandidateFields alternative for proposal payloads.
Its fixed `extraction-candidate-fields/v1` discriminator denotes a read-only map
of public financial field names to their persisted JSON text. Render field strings
as plain text without JSON.parse, Number, HTML interpretation or automatic edit
conversion. This preserves malformed values and unsafe/fractional JSON numbers;
missing and JSON null remain distinct. The wrapper itself does not indicate a
financial failure or approval; show actual validations. Allow an empty evidence
list and render the missing evidence explicitly. Full replacement edit/correction
commands still require the unchanged strict financial payload schema. Validate
closed field names and 65,536-character field limits; test unsafe integers,
fractional/nested values, quotes, null/missing, no controls and safe rendering.

## Implementation slices and proof

1. Server source boundary: reuse explicit FEL_EVIDENCE_SOURCE fixture/http switch
   and current configured API base/token/workspace validation. Keep node:process
   imports and bearer configuration out of client modules. Add generated-type
   mock fixtures and strict runtime validation for list/detail/result responses.
   Prove explicit selection, malformed response failure, no fallback and bounded
   pagination. No all-page drains. Missing configuration renders an honest error.

2. Bounded same-origin read/action routes: fixed upstream extraction paths, strict
   IDs/cursors/methods, JSON/body limits, same-origin mutation checks, no-store.
   Forward only needed If-Match/Idempotency-Key/resume fields and expose the
   upstream ETag/Location/status/closed error envelope. Never forward arbitrary
   URLs or browser authorization. Abort upstream when browser disconnects.
   Prove credential containment, scope rejection, exact 412/409/413 behavior
   and identical retry key/body. API remains the authorization authority.

3. Run and proposal navigation: bounded queue/run/history pages with explicit
   next/previous controls, empty/error/loading states and source links pinned to
   immutable corpus/cutoff/document version. Render exact raw and normalized
   financial fields and actual blockers; NULL confidence displays uncalibrated.
   Do not infer approval from confidence or show mock evidence as live.

4. Review state: selected IDs and versions, complete conflict membership and
   ETags, explicit winner IDs/reason, full replacement edits, explicit merge
   payload source. No arithmetic aggregation. Preserve drafts after 412; require
   intentional resubmission after comparison refresh. Network retry preserves
   request key/body; edited command gets a new key. Display batch atomicity and
   actual selected count. Verify unselected proposals remain unchanged.

5. Immutable history and correction: approved record/version detail, parent
   links, frozen source/validation context, full replacement correction with
   current head ETag. Historical unknown context stays explicitly unknown.
   No display of a mutable current value as a prior approved version.

6. SSE: new extraction-specific incremental parser and consumer, generated
   extraction-event validation, run identity checks, 64KiB frame limit, 500-event
   retained view, bounded reconnect/backoff, resumable last ID and terminal
   behavior. Existing retrieval parser is useful reference but its unbounded
   buffering and seq model must not be copied blindly. Streaming proxy forwards
   chunks with backpressure and cancellation; it must not await full completion.
   Prove split UTF-8/frame boundaries, malformed/oversized frames, disconnect,
   replay deduplication, waiting_review and later review-completion transitions.

7. Browser acceptance: real page navigation and interaction for review, stale
   update preserving an edit, correction history, cancel/rerun and source reader
   links. Include keyboard focus, labels and announcement behavior. A local
   worker-to-browser stream smoke remains distinct from hosted #108 acceptance.

## Integration questions before implementation

- Use the accepted workspace extraction-permissions read for role-aware controls.
  Its allowed_actions comes from current database membership; mutations still
  reauthorize. Do not decode configured bearer claims or invent authentication.
- ExtractionRunCreate does not accept a policy ID. Backend selects the highest
  existing immutable organization policy version and returns its frozen pins.
  The optional corpus_version_id preserves a selected artifact's corpus; when
  omitted/null, backend selects the unique active corpus. Never widen source
  scope or silently substitute another corpus. Missing configuration fails
  explicitly; no policy creation or provider fallback is implied by this UI.
- Backend owns event ordering and replay guarantees. Await its proof of safe
  monotonic replay before using numeric event IDs as a durable watermark.
- Lead owns planned-marker removal with backend router mount, preserving strict
  OpenAPI parity tests. Web builds only against the final committed contract.

Every final PR requires independent review, explicit approval and all required CI
before merge. No live credential, paid call or hosted acceptance is implied.

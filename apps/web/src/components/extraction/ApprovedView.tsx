import Link from "next/link";
import type { Approved } from "../../lib/extraction/contracts";
import { PayloadFields } from "./display";
import { SourceLinks } from "./SourceLinks";
export function ApprovedView({ approved }: { approved: Approved }) {
  return (
    <>
      <p>
        Immutable version {approved.version} · {approved.version_id}
      </p>
      <p>
        Approved by {approved.approved_by} at {approved.created_at}
      </p>
      <p>Reason: {approved.approval_reason}</p>
      <p>
        {approved.ontology_version} · {approved.normalizer_version} · {approved.validator_version}
      </p>
      <p>Evidence manifest: {approved.evidence_manifest_hash}</p>
      {approved.parent_version_id && (
        <p>
          <Link
            href={`/approved-extractions/${approved.record_id}/versions/${approved.parent_version_id}`}
          >
            Previous immutable version
          </Link>
        </p>
      )}
      <PayloadFields payload={approved.payload} />
      <SourceLinks
        evidence={approved.evidence}
        sources={approved.validation_context?.source_runs ?? null}
      />
    </>
  );
}

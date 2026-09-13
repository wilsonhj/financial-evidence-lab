import Link from "next/link";
import { getExtractionSource } from "../../../lib/extraction/source";
import { guards } from "../../../lib/extraction/contracts";
import { ExtractionShell, ExtractionError } from "../../../components/extraction/display";
import { ApprovedView } from "../../../components/extraction/ApprovedView";
import { ActionForm } from "../../../components/extraction/ActionForm";
export const dynamic = "force-dynamic";
export default async function ApprovedPage({ params }: { params: Promise<{ recordId: string }> }) {
  try {
    const source = getExtractionSource(),
      { recordId } = await params;
    const [approved, permissions] = await Promise.all([
      source.read(`approved/${recordId}`, guards.approved),
      source.read("permissions", guards.permissions),
    ]);
    return (
      <ExtractionShell title={`${approved.data.metric_id} approved record`} mode={source.mode}>
        <p>
          <Link href={`/approved-extractions/${recordId}/versions`}>
            Browse immutable version history
          </Link>
        </p>
        <ApprovedView approved={approved.data} />
        <ActionForm
          key={recordId}
          action="correct"
          path={`approved/${recordId}/corrections`}
          initialEtag={approved.etag}
          permitted={permissions.data.allowed_actions.includes("correct")}
        />
      </ExtractionShell>
    );
  } catch {
    return (
      <ExtractionShell title="Approved record">
        <ExtractionError />
      </ExtractionShell>
    );
  }
}

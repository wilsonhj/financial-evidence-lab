import Link from "next/link";
import { getExtractionSource } from "../../../../../lib/extraction/source";
import { guards } from "../../../../../lib/extraction/contracts";
import { ExtractionShell, ExtractionError } from "../../../../../components/extraction/display";
import { ApprovedView } from "../../../../../components/extraction/ApprovedView";
export const dynamic = "force-dynamic";
export default async function VersionPage({
  params,
}: {
  params: Promise<{ recordId: string; versionId: string }>;
}) {
  try {
    const source = getExtractionSource(),
      { recordId, versionId } = await params;
    const { data: approved } = await source.read(
      `approved/${recordId}/versions/${versionId}`,
      guards.approved,
    );
    return (
      <ExtractionShell title="Immutable approved version" mode={source.mode}>
        <ApprovedView approved={approved} />
        <Link href={`/approved-extractions/${recordId}/versions`}>Version history</Link>
        {" · "}
        <Link href={`/approved-extractions/${recordId}`}>Current head and correction</Link>
      </ExtractionShell>
    );
  } catch {
    return (
      <ExtractionShell title="Immutable approved version">
        <ExtractionError />
      </ExtractionShell>
    );
  }
}

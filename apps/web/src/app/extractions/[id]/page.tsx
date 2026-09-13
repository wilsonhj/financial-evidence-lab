import Link from "next/link";
import { getExtractionSource } from "../../../lib/extraction/source";
import { guards } from "../../../lib/extraction/contracts";
import {
  ExtractionShell,
  ExtractionError,
  PayloadFields,
  ProposalStatus,
} from "../../../components/extraction/display";
import { ReviewQueue } from "../../../components/extraction/ReviewQueue";
import { SourceLinks } from "../../../components/extraction/SourceLinks";
export const dynamic = "force-dynamic";
export default async function ProposalPage({ params }: { params: Promise<{ id: string }> }) {
  try {
    const source = getExtractionSource(),
      { id } = await params;
    const [proposal, permissions] = await Promise.all([
      source.read(`proposals/${id}`, guards.proposal),
      source.read("permissions", guards.permissions),
    ]);
    const { data: run } = await source.read(`runs/${proposal.data.run_id}`, guards.run);
    return (
      <ExtractionShell title={`${proposal.data.metric_id} proposal`} mode={source.mode}>
        <Link href={`/extraction-runs/${run.id}`}>Run {run.id}</Link>
        <ProposalStatus proposal={proposal.data} />
        <PayloadFields payload={proposal.data.payload} />
        <SourceLinks
          evidence={proposal.data.evidence}
          sources={[{ run_id: run.id, as_of: run.as_of, corpus_version_id: run.corpus_version_id }]}
        />
        <ReviewQueue key={id} proposals={[proposal.data]} permissions={permissions.data} />
      </ExtractionShell>
    );
  } catch {
    return (
      <ExtractionShell title="Extraction proposal">
        <ExtractionError />
      </ExtractionShell>
    );
  }
}

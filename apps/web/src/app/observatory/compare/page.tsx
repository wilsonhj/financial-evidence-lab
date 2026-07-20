import Link from "next/link";

import { EvidenceFailureState } from "../../../components/EvidenceFailureState";
import { RunComparison } from "../../../components/RunComparison";
import { observatoryFailureState } from "../../../lib/observatory/errors";
import { getObservatorySource } from "../../../lib/observatory/server";

export const dynamic = "force-dynamic";

export default async function ObservatoryComparePage({
  searchParams,
}: {
  searchParams?: Promise<{ a?: string; b?: string }>;
}) {
  const { a, b } = (await searchParams) ?? {};
  if (!a || !b) {
    return (
      <main className="page-main">
        <p>
          <Link href="/observatory">← Search Observatory</Link>
        </p>
        <h1>Run comparison</h1>
        <p className="obs-empty">Provide two run ids (?a=…&b=…) to compare.</p>
      </main>
    );
  }

  const source = getObservatorySource();
  try {
    const [runA, runB] = await Promise.all([source.getRun(a), source.getRun(b)]);
    return (
      <main className="page-main">
        <p>
          <Link href={`/observatory/runs/${a}`}>← Back to run</Link>
        </p>
        <h1>Run comparison</h1>
        <RunComparison a={runA} b={runB} />
      </main>
    );
  } catch (error) {
    const kind = observatoryFailureState(error);
    if (kind) return <EvidenceFailureState kind={kind} />;
    throw error;
  }
}

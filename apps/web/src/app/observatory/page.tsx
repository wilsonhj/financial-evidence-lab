import Link from "next/link";

import { ObservatoryControls } from "../../components/ObservatoryControls";
import { MOCK_RUN_ID } from "../../lib/observatory/fixtures/synthetic-trace";
import { loadObservatoryRuntimeConfig } from "../../lib/observatory/runtime-config";

export const dynamic = "force-dynamic";

export default async function ObservatoryPage({
  searchParams,
}: {
  searchParams?: Promise<{ error?: string }>;
}) {
  const { error } = (await searchParams) ?? {};

  let isMock: boolean;
  try {
    isMock = loadObservatoryRuntimeConfig().mode === "mock";
  } catch {
    isMock = false;
  }

  return (
    <main className="page-main">
      <h1>Search Observatory</h1>
      <p>
        Inspect a hybrid retrieval run: the query plan, per-lane candidates with raw and fused
        ranks, dedupe and rejection decisions, generated claims with citation status, and budget,
        latency and cost.
      </p>
      <ObservatoryControls error={error} />
      {isMock && (
        <p>
          <Link href={`/observatory/runs/${MOCK_RUN_ID}`}>Open the demo retrieval run →</Link>
        </p>
      )}
    </main>
  );
}

import type { RetrievalTrace } from "./query-source";
import { partitionCandidates } from "./trace-view";

export interface ComparisonRow {
  label: string;
  a: string;
  b: string;
  /** True when the two runs differ on this metric. */
  changed: boolean;
}

function count(trace: RetrievalTrace): { supported: number; rejected: number } {
  const { supported, rejected } = partitionCandidates(trace);
  return { supported: supported.length, rejected: rejected.length };
}

/**
 * Side-by-side comparison of two runs on the metrics that matter when tuning
 * controls or reviewing a rerun: status, supported/rejected counts, claims,
 * context budget, cost and total latency. Pure and order-preserving.
 */
export function compareRuns(a: RetrievalTrace, b: RetrievalTrace): ComparisonRow[] {
  const ca = count(a);
  const cb = count(b);
  const latency = (trace: RetrievalTrace) =>
    Object.values(trace.timings_ms).reduce((sum, ms) => sum + ms, 0);
  const row = (label: string, av: string | number, bv: string | number): ComparisonRow => ({
    label,
    a: String(av),
    b: String(bv),
    changed: String(av) !== String(bv),
  });

  return [
    row("Status", a.status, b.status),
    row("Supported candidates", ca.supported, cb.supported),
    row("Rejected candidates", ca.rejected, cb.rejected),
    row("Claims", a.claims.length, b.claims.length),
    row("Context items", a.budget_usage.context_items, b.budget_usage.context_items),
    row("Input tokens", a.budget_usage.input_tokens, b.budget_usage.input_tokens),
    row("Output tokens", a.budget_usage.output_tokens, b.budget_usage.output_tokens),
    row("Cost (USD)", a.cost_usd, b.cost_usd),
    row("Total latency (ms)", latency(a), latency(b)),
  ];
}

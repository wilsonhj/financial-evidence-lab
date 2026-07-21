import { compareRuns } from "../lib/observatory/compare";
import type { RetrievalTrace } from "../lib/observatory/query-source";

/** Side-by-side comparison of two runs' key metrics; changed rows are flagged. */
export function RunComparison({ a, b }: { a: RetrievalTrace; b: RetrievalTrace }) {
  const rows = compareRuns(a, b);
  return (
    <section className="panel-card" aria-labelledby="obs-compare-heading">
      <h2 id="obs-compare-heading">Run comparison</h2>
      <table className="doc-table">
        <caption className="visually-hidden">Comparison of run A and run B</caption>
        <thead>
          <tr>
            <th scope="col">Metric</th>
            <th scope="col">Run A ({a.run_id.slice(0, 8)})</th>
            <th scope="col">Run B ({b.run_id.slice(0, 8)})</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className={row.changed ? "obs-changed" : undefined}>
              <th scope="row">{row.label}</th>
              <td>{row.a}</td>
              <td>
                {row.b}
                {row.changed && <span className="visually-hidden"> (changed)</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

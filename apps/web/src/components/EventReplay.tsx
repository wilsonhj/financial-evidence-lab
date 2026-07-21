import type { RetrievalTrace } from "../lib/observatory/query-source";

/**
 * Stored replay of a run's persisted event log. This is a read of the trace's
 * events (no new run is created), rendered in seq order so the run can be
 * stepped through after the fact.
 */
export function EventReplay({ trace }: { trace: RetrievalTrace }) {
  const events = [...trace.events].sort((a, b) => a.seq - b.seq);
  return (
    <section className="panel-card" aria-labelledby="obs-replay-heading">
      <h2 id="obs-replay-heading">Stored replay</h2>
      {events.length === 0 ? (
        <p className="obs-empty">No persisted events for this run.</p>
      ) : (
        <ol className="obs-replay">
          {events.map((event) => (
            <li key={event.seq}>
              <span className="badge badge-info">#{event.seq}</span> <code>{event.type}</code>{" "}
              <span className="obs-muted">{event.occurred_at}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

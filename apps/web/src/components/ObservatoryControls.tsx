import { submitQueryAction } from "../lib/observatory/actions";
import { FILTER_MAX_ITEMS, QUESTION_MAX, TOP_K_MAX, TOP_K_MIN } from "../lib/observatory/controls";
import { LANES } from "../lib/observatory/trace-view";

const LANE_LABELS: Record<(typeof LANES)[number], string> = {
  dense: "Dense",
  lexical: "Lexical",
  facts: "Facts",
  tables: "Tables",
};

/**
 * Bounded query controls. Native input constraints keep values within the
 * frozen contract bounds (top_k 1..100, question length, unique lanes); the
 * server action re-validates before creating a query. Optional parentQueryId
 * links a control-changed query to its parent for comparison.
 */
export function ObservatoryControls({
  parentQueryId,
  error,
}: {
  parentQueryId?: string;
  error?: string;
}) {
  return (
    <form
      className="obs-controls"
      action={submitQueryAction}
      aria-labelledby="obs-controls-heading"
    >
      <h2 id="obs-controls-heading">
        {parentQueryId ? "Rerun with changed controls" : "New query"}
      </h2>
      {error && (
        <p className="reader-banner citation-error" role="alert">
          {error}
        </p>
      )}
      {parentQueryId && <input type="hidden" name="parentQueryId" value={parentQueryId} />}

      <label htmlFor="obs-question">Question</label>
      <textarea
        id="obs-question"
        name="question"
        required
        maxLength={QUESTION_MAX}
        rows={2}
        defaultValue=""
      />

      <fieldset>
        <legend>Lanes</legend>
        {LANES.map((lane) => (
          <label key={lane} className="obs-check">
            <input type="checkbox" name="lanes" value={lane} defaultChecked />
            {LANE_LABELS[lane]}
          </label>
        ))}
      </fieldset>

      <label htmlFor="obs-topk">
        Top-k ({TOP_K_MIN}–{TOP_K_MAX})
      </label>
      <input
        id="obs-topk"
        name="topK"
        type="number"
        min={TOP_K_MIN}
        max={TOP_K_MAX}
        step={1}
        inputMode="numeric"
      />

      <label htmlFor="obs-asof">Cutoff (as-of)</label>
      <input id="obs-asof" name="asOf" type="datetime-local" />

      <label htmlFor="obs-forms">Form filters (max {FILTER_MAX_ITEMS}, comma-separated)</label>
      <input id="obs-forms" name="forms" type="text" />

      <label htmlFor="obs-periods">Period filters (max {FILTER_MAX_ITEMS}, comma-separated)</label>
      <input id="obs-periods" name="periods" type="text" />

      <button type="submit" className="retry-button">
        Run query
      </button>
    </form>
  );
}

import { rerunAction } from "../lib/observatory/actions";

/** Parent-linked rerun: creates a child run pinned to the original query inputs. */
export function RerunButton({ queryId, runId }: { queryId: string; runId: string }) {
  return (
    <form action={rerunAction} className="obs-rerun">
      <input type="hidden" name="queryId" value={queryId} />
      <input type="hidden" name="runId" value={runId} />
      <button type="submit" className="retry-button">
        Rerun (unchanged, parent-linked)
      </button>
    </form>
  );
}

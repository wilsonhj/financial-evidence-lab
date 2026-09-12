import Link from "next/link";
import { getExtractionSource } from "../../../lib/extraction/source";
import { guards } from "../../../lib/extraction/contracts";
import { pageQuery } from "../../../lib/extraction/page-query";
import {
  ExtractionShell,
  ExtractionError,
  ExtractionPagination,
} from "../../../components/extraction/display";
import { ActionForm } from "../../../components/extraction/ActionForm";
import { RunEvents } from "../../../components/extraction/RunEvents";
export const dynamic = "force-dynamic";
export default async function RunPage({
  params,
  searchParams,
}: {
  params: Promise<{ runId: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  try {
    const source = getExtractionSource(),
      { runId } = await params,
      query = pageQuery(await searchParams);
    const [run, steps, permissions] = await Promise.all([
      source.read(`runs/${runId}`, guards.run),
      source.read(`runs/${runId}/steps`, guards.steps, query),
      source.read("permissions", guards.permissions),
    ]);
    const r = run.data;
    return (
      <ExtractionShell title={`Extraction run ${r.id}`} mode={source.mode}>
        <p>
          Status: {r.status} · Cutoff: {r.as_of} · Corpus:{" "}
          {r.corpus_version_id ?? "No corpus pin recorded"}
        </p>
        <p>
          {r.provider} / {r.model} · {r.workflow_version} · {r.ontology_version}
        </p>
        <p>
          Usage: {r.usage.calls} calls · {r.usage.input_tokens} input tokens ·{" "}
          {r.usage.output_tokens} output tokens · USD {r.usage.cost_usd}
        </p>
        {r.cancel_requested_at && <p>Cancellation requested at {r.cancel_requested_at}</p>}
        {r.parent_run_id && (
          <Link href={`/extraction-runs/${r.parent_run_id}`}>Original parent run</Link>
        )}
        <p>
          <Link href={`/extractions?run_id=${r.id}`}>Review this run's proposals</Link>
          {" · "}
          <Link href={`/extraction-runs/${r.id}/events`}>Stored event history</Link>
        </p>
        <table>
          <caption>Execution steps in order</caption>
          <thead>
            <tr>
              <th>Step</th>
              <th>Attempt</th>
              <th>Status</th>
              <th>Started</th>
              <th>Finished</th>
            </tr>
          </thead>
          <tbody>
            {steps.data.items.map((s) => (
              <tr key={s.id}>
                <td>{s.step_name}</td>
                <td>{s.attempt}</td>
                <td>
                  {s.status}
                  {s.error && `: ${s.error.error.code}`}
                </td>
                <td>{s.started_at ?? "Not started"}</td>
                <td>{s.finished_at ?? "Not finished"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <ExtractionPagination
          path={`/extraction-runs/${r.id}`}
          query={Object.fromEntries(query)}
          page={steps.data}
        />
        <RunEvents key={r.id} runId={r.id} />
        <ActionForm
          key={`cancel:${r.id}`}
          action="cancel"
          path={`runs/${r.id}`}
          initialEtag={run.etag}
          permitted={
            permissions.data.allowed_actions.includes("cancel") &&
            ["queued", "running", "waiting_review"].includes(r.status)
          }
        />
        <ActionForm
          key={`rerun:${r.id}`}
          action="rerun"
          path={`runs/${r.id}/rerun`}
          permitted={permissions.data.allowed_actions.includes("rerun")}
        />
      </ExtractionShell>
    );
  } catch {
    return (
      <ExtractionShell title="Extraction run">
        <ExtractionError />
      </ExtractionShell>
    );
  }
}

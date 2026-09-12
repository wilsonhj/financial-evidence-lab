"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { guards, type Run, type Approved } from "../../lib/extraction/contracts";
import {
  prepareRequest,
  sendPrepared,
  statusMessage,
  type PendingRequest,
} from "../../lib/extraction/review-state";
import { PayloadFields } from "./display";

export function ActionForm({
  action,
  path,
  permitted,
  initialEtag = null,
}: {
  action: "create" | "cancel" | "rerun" | "correct";
  path: string;
  permitted: boolean;
  initialEtag?: string | null;
}) {
  const [draft, setDraft] = useState("");
  const [tag, setTag] = useState(initialEtag);
  const [message, setMessage] = useState("");
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);
  const [comparison, setComparison] = useState<Run | Approved | null>(null);
  const [result, setResult] = useState<Run | Approved | null>(null);
  const pending = useRef<PendingRequest | undefined>(undefined);
  const method = action === "cancel" ? "DELETE" : "POST";
  async function submit() {
    setBusy(true);
    setMessage("");
    try {
      let body = draft;
      if (action === "cancel") body = "";
      else if (action === "rerun") body = JSON.stringify({ reason: draft });
      else {
        const value: unknown = JSON.parse(draft);
        if (!(action === "create" ? guards.create(value) : guards.correction(value)))
          throw new Error("Supply the complete valid replacement and evidence");
      }
      pending.current = prepareRequest(path, method, body, tag, pending.current);
      const response = await sendPrepared(pending.current);
      if (!response.ok) {
        setMessage(statusMessage(response.status));
        if (response.status === 412) setStale(true);
        return;
      }
      const value: unknown = await response.json();
      if (!guards.run(value) && !guards.approved(value)) throw new Error("Invalid action receipt");
      setResult(value);
      setTag(response.headers.get("etag"));
      pending.current = undefined;
      setMessage(
        action === "cancel"
          ? "Cancellation requested. Running work stops cooperatively; inspect its terminal event."
          : "Action committed. Open the immutable result below.",
      );
    } catch (e) {
      setMessage(
        e instanceof Error ? e.message : "Network interrupted. Retry preserves the exact request.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    setBusy(true);
    try {
      const resource = path.replace(/\/corrections$/, "");
      const response = await fetch(`/api/extraction/${resource}`, { cache: "no-store" });
      const value: unknown = await response.json();
      if (!response.ok || (!guards.run(value) && !guards.approved(value)))
        throw new Error("Unable to refresh current version");
      setComparison(value);
      setTag(response.headers.get("etag"));
      pending.current = undefined;
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Comparison unavailable");
    } finally {
      setBusy(false);
    }
  }
  const label =
    action === "correct"
      ? "Full correction JSON (reason, strict payload and evidence)"
      : action === "create"
        ? "Run request JSON (entity_id, as_of, modes, source_span_ids; optional corpus_version_id)"
        : "Rerun reason";
  return (
    <section aria-label={`${action} extraction`}>
      <h2>
        {action === "correct"
          ? "Append correction"
          : `${action[0]!.toUpperCase()}${action.slice(1)} run`}
      </h2>
      {action === "correct" && (
        <p>Creates a new immutable version. Prior approved values and evidence remain unchanged.</p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {action !== "cancel" && (
          <>
            <label htmlFor={`${action}-draft`}>{label}</label>
            <textarea
              id={`${action}-draft`}
              rows={action === "rerun" ? 2 : 12}
              value={draft}
              required
              disabled={busy || !permitted}
              onChange={(e) => {
                setDraft(e.target.value);
                pending.current = undefined;
                setResult(null);
              }}
            />
          </>
        )}
        <button
          type="submit"
          disabled={!permitted || busy || stale || (action !== "cancel" && !draft.trim())}
        >
          {action === "correct"
            ? "Submit full correction"
            : action === "cancel"
              ? "Request cancellation"
              : action === "create"
                ? "Create bounded run"
                : "Create unchanged child run"}
        </button>
      </form>
      {!permitted && <p>Your current permissions do not allow this action.</p>}
      {stale && (
        <button type="button" disabled={busy} onClick={() => void refresh()}>
          Refresh current version for comparison
        </button>
      )}
      {comparison && (
        <section>
          <h3>Current version {comparison.version}</h3>
          {"payload" in comparison ? (
            <PayloadFields payload={comparison.payload} />
          ) : (
            <p>{comparison.status}</p>
          )}
          <button
            type="button"
            onClick={() => {
              setStale(false);
              setComparison(null);
              setMessage("Draft preserved. Submit intentionally using the refreshed version.");
            }}
          >
            Use refreshed version
          </button>
        </section>
      )}
      <p role="status" aria-live="polite">
        {message}
      </p>
      {result &&
        ("record_id" in result ? (
          <Link href={`/approved-extractions/${result.record_id}/versions/${result.version_id}`}>
            Open approved version {result.version}
          </Link>
        ) : (
          <Link href={`/extraction-runs/${result.id}`}>Open run {result.id}</Link>
        ))}
    </section>
  );
}

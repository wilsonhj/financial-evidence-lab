"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import {
  guards,
  type Proposal,
  type Permissions,
  type Conflict,
  type Review,
  type Schemas,
} from "../../lib/extraction/contracts";
import {
  buildReview,
  prepareRequest,
  sendPrepared,
  statusMessage,
  type PendingRequest,
} from "../../lib/extraction/review-state";
import { PayloadFields } from "./display";

export function ReviewQueue({
  proposals,
  permissions: initialPermissions,
}: {
  proposals: Proposal[];
  permissions: Permissions;
}) {
  const [rows, setRows] = useState(proposals);
  const [permissions, setPermissions] = useState(initialPermissions);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [action, setAction] = useState<Review["action"]>("accept");
  const [reason, setReason] = useState("");
  const [patch, setPatch] = useState("");
  const [groups, setGroups] = useState<Conflict[]>([]);
  const [winners, setWinners] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [compared, setCompared] = useState(false);
  const [result, setResult] = useState<Schemas["ReviewResult"] | null>(null);
  const pending = useRef<PendingRequest | undefined>(undefined);
  const selected = rows.filter((p) => selectedIds.includes(p.id));
  const editable = selected.every((p) => ["proposed", "needs_review"].includes(p.state));
  const permitted = permissions.allowed_actions.includes(action);
  const change = () => {
    pending.current = undefined;
    setResult(null);
  };
  async function json(path: string) {
    const response = await fetch(`/api/extraction/${path}`, { cache: "no-store" });
    if (!response.ok) throw new Error(statusMessage(response.status));
    return response.json() as Promise<unknown>;
  }
  async function refresh(contextOnly = false) {
    setBusy(true);
    setMessage("");
    try {
      const capability = await json("permissions");
      if (!guards.permissions(capability)) throw new Error("Invalid permissions response");
      setPermissions(capability);
      const current = contextOnly
        ? selected
        : await Promise.all(
            selected.map(async (p) => {
              const value = await json(`proposals/${p.id}`);
              if (!guards.proposal(value) || value.id !== p.id)
                throw new Error("Invalid proposal response");
              return value;
            }),
          );
      const ids = [...new Set(current.flatMap((p) => p.conflict_ids))];
      if (ids.length > 100) throw new Error("Too many conflict groups for one atomic review");
      const conflicts = await Promise.all(
        ids.map(async (id) => {
          const value = await json(`conflicts/${id}`);
          if (!guards.conflict(value) || value.id !== id)
            throw new Error("Invalid conflict response");
          return value;
        }),
      );
      setGroups(conflicts);
      if (!contextOnly) {
        setRows(rows.map((p) => current.find((c) => c.id === p.id) ?? p));
        setCompared(true);
        pending.current = undefined;
      }
      setMessage(
        contextOnly
          ? "Complete conflict membership loaded. Choose the winners explicitly."
          : "Current versions loaded below. Compare them with your preserved draft, then use the refreshed versions explicitly.",
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Unable to refresh comparison");
    } finally {
      setBusy(false);
    }
  }
  async function submit() {
    setBusy(true);
    setMessage("");
    try {
      const body = buildReview(selected, action, reason, patch, groups, winners);
      pending.current = prepareRequest("review", "POST", body, null, pending.current);
      const response = await sendPrepared(pending.current);
      if (!response.ok) {
        setMessage(statusMessage(response.status));
        if (response.status === 412) {
          setStale(true);
          setCompared(false);
        }
        return;
      }
      const value: unknown = await response.json();
      if (
        !guards.result(value) ||
        value.action !== action ||
        ![value.proposal_states, value.proposal_versions].every(
          (map) =>
            Object.keys(map).length === selected.length &&
            selected.every((p) => Object.hasOwn(map, p.id)),
        )
      )
        throw new Error("Invalid review receipt; refresh before proceeding");
      setResult(value);
      setRows(
        rows.map((p) =>
          value.proposal_states[p.id]
            ? { ...p, state: value.proposal_states[p.id]!, version: value.proposal_versions[p.id]! }
            : p,
        ),
      );
      setMessage(
        `Atomic ${action} completed for ${selected.length} selected proposals. Unselected proposals were not submitted.`,
      );
      pending.current = undefined;
    } catch (e) {
      setMessage(
        e instanceof Error
          ? e.message
          : "Network interrupted. Retry retains the same request and key.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="Review proposals">
      {!rows.length ? (
        <p>No proposals on this page.</p>
      ) : (
        <table>
          <caption>Proposals on this page</caption>
          <thead>
            <tr>
              <th>Select</th>
              <th>Metric</th>
              <th>Kind</th>
              <th>Source run</th>
              <th>State</th>
              <th>Confidence</th>
              <th>Blockers</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Select ${p.metric_id} ${p.id}`}
                    checked={selectedIds.includes(p.id)}
                    disabled={busy || !["proposed", "needs_review"].includes(p.state)}
                    onChange={(e) => {
                      change();
                      setGroups([]);
                      setWinners([]);
                      setSelectedIds(
                        e.target.checked
                          ? [...selectedIds, p.id]
                          : selectedIds.filter((id) => id !== p.id),
                      );
                    }}
                  />
                </td>
                <td>
                  <Link href={`/extractions/${p.id}`}>{p.metric_id}</Link>
                </td>
                <td>{p.kind}</td>
                <td>
                  <Link href={`/extraction-runs/${p.run_id}`}>Run {p.run_id}</Link>
                </td>
                <td>
                  {p.state} (v{p.version})
                </td>
                <td>{p.record_confidence ?? "Uncalibrated"}</td>
                <td>
                  {p.validations
                    .filter((v) => v.status !== "pass")
                    .map((v) => `${v.status}: ${v.code}`)
                    .join(", ") || "No recorded blockers"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p>
        {selected.length} selected. Review is atomic: the whole selected batch succeeds or none of
        it does.
      </p>
      <button type="button" onClick={() => void refresh(true)} disabled={busy || !selected.length}>
        Load complete conflict context
      </button>
      {groups.map((group) => (
        <fieldset key={group.id}>
          <legend>
            Conflict {group.id}: {group.status}
          </legend>
          <p>{group.reason_codes.join(", ")}</p>
          <p>ETag {group.etag}</p>
          <ul>
            {Object.entries(group.member_versions).map(([id, version]) => (
              <li key={id}>
                <Link href={`/extractions/${id}`}>{id}</Link> version {version}
                {selectedIds.includes(id) && (
                  <label>
                    <input
                      type="checkbox"
                      checked={winners.includes(id)}
                      disabled={busy}
                      onChange={(e) => {
                        change();
                        setWinners(
                          e.target.checked ? [...winners, id] : winners.filter((w) => w !== id),
                        );
                      }}
                    />
                    Explicit winner
                  </label>
                )}
              </li>
            ))}
          </ul>
          {group.resolution && <p>Recorded decision: {group.resolution.reason}</p>}
        </fieldset>
      ))}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label htmlFor="review-action">Review action</label>
        <select
          id="review-action"
          value={action}
          disabled={busy}
          onChange={(e) => {
            const value = e.target.value;
            if (["accept", "edit", "reject", "merge"].includes(value)) {
              change();
              setAction(value as Review["action"]);
            }
          }}
        >
          {(["accept", "edit", "reject", "merge"] as const).map((a) => (
            <option key={a} value={a} disabled={!permissions.allowed_actions.includes(a)}>
              {a}
            </option>
          ))}
        </select>
        <label htmlFor="review-reason">Reason</label>
        <textarea
          id="review-reason"
          value={reason}
          maxLength={2000}
          required
          disabled={busy}
          onChange={(e) => {
            change();
            setReason(e.target.value);
          }}
        />
        {(action === "edit" || action === "merge") && (
          <>
            <label htmlFor="review-replacement">
              {action === "edit"
                ? "Full replacements JSON array (extraction_id, payload, evidence)"
                : "Explicit merge source JSON (payload_source_id)"}
            </label>
            <textarea
              id="review-replacement"
              rows={12}
              value={patch}
              required
              disabled={busy}
              onChange={(e) => {
                change();
                setPatch(e.target.value);
              }}
            />
            <p>
              Provide the complete strict payload and evidence for every edit. Candidate display
              fields are never converted automatically. A merge copies the selected source; it does
              not sum values.
            </p>
          </>
        )}
        <button
          type="submit"
          disabled={
            busy ||
            stale ||
            !permitted ||
            !selected.length ||
            selected.length > 100 ||
            !editable ||
            !reason.trim()
          }
        >
          Submit atomic review
        </button>
        {!permitted && <p>Your current permissions do not allow this action.</p>}
      </form>
      <button type="button" disabled={busy} onClick={() => void refresh()}>
        Refresh comparison and permissions
      </button>
      {compared && (
        <>
          <h2>Refreshed selected versions</h2>
          {selected.map((p) => (
            <div key={p.id}>
              <h3>
                {p.id} · v{p.version} · {p.state}
              </h3>
              <PayloadFields payload={p.payload} />
            </div>
          ))}
          <button
            type="button"
            onClick={() => {
              setStale(false);
              setCompared(false);
              change();
              setMessage("Refreshed versions selected. Submit intentionally when ready.");
            }}
          >
            Use refreshed versions
          </button>
        </>
      )}
      <p role="status" aria-live="polite">
        {message}
      </p>
      {result && (
        <section aria-label="Immutable review receipt">
          <p>Review {result.review_id}</p>
          <ul>
            {result.approved_versions.map((v) => (
              <li key={v.version_id}>
                <Link href={`/approved-extractions/${v.record_id}/versions/${v.version_id}`}>
                  Approved version {v.version}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  );
}

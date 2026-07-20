import { sendFeedbackAction } from "../lib/observatory/actions";

const LABELS: { value: string; text: string }[] = [
  { value: "relevant", text: "Relevant" },
  { value: "irrelevant", text: "Irrelevant" },
  { value: "duplicate", text: "Duplicate" },
  { value: "temporally_invalid", text: "Temporally invalid" },
];

/** Append-only feedback for one candidate item; submits via a server action. */
export function FeedbackControl({ runId, itemId }: { runId: string; itemId: string }) {
  const selectId = `feedback-${itemId}`;
  return (
    <form action={sendFeedbackAction} className="obs-feedback">
      <input type="hidden" name="runId" value={runId} />
      <input type="hidden" name="itemId" value={itemId} />
      <label htmlFor={selectId} className="visually-hidden">
        Feedback for item {itemId.slice(0, 8)}
      </label>
      <select id={selectId} name="label" defaultValue="relevant">
        {LABELS.map((label) => (
          <option key={label.value} value={label.value}>
            {label.text}
          </option>
        ))}
      </select>
      <label htmlFor={`reason-${itemId}`} className="visually-hidden">
        Reason (optional)
      </label>
      <input id={`reason-${itemId}`} name="reason" type="text" placeholder="Reason (optional)" />
      <button type="submit">Send</button>
    </form>
  );
}

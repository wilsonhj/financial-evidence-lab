"use client";

import { useState } from "react";

import type { NoteAnchor, NotesState } from "@/lib/notes";

export interface NotesPanelProps {
  notes: NotesState;
  anchor: NoteAnchor | null;
  anchorLabel: string;
  onAdd: (anchor: NoteAnchor, body: string) => void;
  onRemove: (noteId: string) => void;
  describeAnchor: (anchor: NoteAnchor) => string;
}

/**
 * Analyst notes overlay. Notes attach to a section or source span by id and
 * live entirely in client-side state — source content is never modified
 * (enforced by lib/notes and its invariant test).
 */
export function NotesPanel({
  notes,
  anchor,
  anchorLabel,
  onAdd,
  onRemove,
  describeAnchor,
}: NotesPanelProps) {
  const [draft, setDraft] = useState("");

  return (
    <section className="panel-card" aria-label="Analyst notes">
      <h2>Analyst notes</h2>
      <form
        className="note-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!anchor || draft.trim().length === 0) return;
          onAdd(anchor, draft.trim());
          setDraft("");
        }}
      >
        <label htmlFor="note-draft">
          Attach note to: <strong>{anchorLabel}</strong>
        </label>
        <textarea
          id="note-draft"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Notes are stored alongside the evidence and never modify source content."
        />
        <button type="submit" disabled={!anchor || draft.trim().length === 0}>
          Add note
        </button>
      </form>
      {notes.notes.length > 0 && (
        <ul className="note-list">
          {notes.notes.map((note) => (
            <li key={note.id}>
              <button type="button" onClick={() => onRemove(note.id)}>
                Remove
              </button>
              <p style={{ margin: 0 }}>{note.body}</p>
              <span className="note-meta">
                {describeAnchor(note.anchor)} · {note.createdAt.slice(0, 16).replace("T", " ")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

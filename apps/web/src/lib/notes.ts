/**
 * Analyst notes are an overlay keyed by evidence anchors (a section or a
 * source span). They live entirely outside the document/section/fact records,
 * so attaching, editing, or removing a note can never mutate source content.
 * M0-level persistence is client-side state; the store is a plain immutable
 * value so it can later be swapped for a server-backed store unchanged.
 */

export interface NoteAnchor {
  kind: "section" | "span";
  /** SectionRecord id or SourceSpanRecord id. */
  id: string;
}

export interface AnalystNote {
  id: string;
  anchor: NoteAnchor;
  body: string;
  createdAt: string;
}

export interface NotesState {
  notes: readonly AnalystNote[];
}

export const emptyNotesState: NotesState = { notes: [] };

let counter = 0;

/** Deterministic-enough client id for M0 client-side persistence. */
export function nextNoteId(now: () => number = Date.now): string {
  counter += 1;
  return `note-${now()}-${counter}`;
}

export function addNote(
  state: NotesState,
  anchor: NoteAnchor,
  body: string,
  options: { id?: string; createdAt?: string } = {},
): NotesState {
  const note: AnalystNote = {
    id: options.id ?? nextNoteId(),
    anchor: { ...anchor },
    body,
    createdAt: options.createdAt ?? new Date().toISOString(),
  };
  return { notes: [...state.notes, note] };
}

export function removeNote(state: NotesState, noteId: string): NotesState {
  return { notes: state.notes.filter((note) => note.id !== noteId) };
}

export function notesForAnchor(state: NotesState, anchor: NoteAnchor): AnalystNote[] {
  return state.notes.filter(
    (note) => note.anchor.kind === anchor.kind && note.anchor.id === anchor.id,
  );
}

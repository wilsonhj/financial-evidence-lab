/**
 * Reader UI state (selection, outline focus, and the notes overlay) as a
 * single pure reducer keyed by document id. EvidenceReader dispatches a
 * "reset" action whenever its `documentId` prop no longer matches
 * `state.documentId`, which re-derives fresh initial state for the new
 * document (see issue #198): the reader no longer needs a `key={documentId}`
 * remount to keep state from leaking across documents when the reader stays
 * mounted across a client-side navigation.
 */

import { addNote, emptyNotesState, removeNote, type NoteAnchor, type NotesState } from "./notes";

export interface ReaderState {
  documentId: string;
  activeSectionId: string | null;
  selectedSpanId: string | null;
  notes: NotesState;
}

export type ReaderAction =
  | {
      type: "reset";
      documentId: string;
      activeSectionId: string | null;
      selectedSpanId: string | null;
    }
  | { type: "select-section"; sectionId: string }
  | { type: "select-span"; spanId: string | null }
  | { type: "add-note"; anchor: NoteAnchor; body: string }
  | { type: "remove-note"; noteId: string };

/** Lazy-initializer for useReducer's third argument. */
export function initReaderState(
  documentId: string,
  activeSectionId: string | null,
  selectedSpanId: string | null,
): ReaderState {
  return { documentId, activeSectionId, selectedSpanId, notes: emptyNotesState };
}

export function readerReducer(state: ReaderState, action: ReaderAction): ReaderState {
  switch (action.type) {
    case "reset":
      return initReaderState(action.documentId, action.activeSectionId, action.selectedSpanId);
    case "select-section":
      return { ...state, activeSectionId: action.sectionId };
    case "select-span":
      return { ...state, selectedSpanId: action.spanId };
    case "add-note":
      return { ...state, notes: addNote(state.notes, action.anchor, action.body) };
    case "remove-note":
      return { ...state, notes: removeNote(state.notes, action.noteId) };
    default:
      return state;
  }
}

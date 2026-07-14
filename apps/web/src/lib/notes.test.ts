import { describe, expect, it } from "vitest";

import { addNote, emptyNotesState, notesForAnchor, removeNote } from "./notes";
import {
  fixtureDocuments,
  fixtureFacts,
  fixtureSections,
  fixtureSpans,
} from "./fixtures/synthetic-filing";

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const key of Object.getOwnPropertyNames(value)) {
      deepFreeze((value as Record<string, unknown>)[key]);
    }
  }
  return value;
}

describe("analyst notes", () => {
  it("adds and removes notes immutably", () => {
    const anchor = { kind: "span", id: "cccccccc-0000-4000-8000-000000000001" } as const;
    const s1 = addNote(emptyNotesState, anchor, "Check warranty accrual timing.", {
      id: "n1",
      createdAt: "2026-07-13T00:00:00Z",
    });
    const s2 = addNote(s1, { kind: "section", id: "sec" }, "MD&A figure disagrees.", {
      id: "n2",
      createdAt: "2026-07-13T00:01:00Z",
    });

    expect(emptyNotesState.notes).toHaveLength(0);
    expect(s1.notes).toHaveLength(1);
    expect(s2.notes).toHaveLength(2);
    expect(notesForAnchor(s2, anchor).map((note) => note.id)).toEqual(["n1"]);

    const s3 = removeNote(s2, "n1");
    expect(s3.notes.map((note) => note.id)).toEqual(["n2"]);
    expect(s2.notes).toHaveLength(2);
  });

  it("never mutates source content: documents, sections, spans, and facts stay byte-identical", () => {
    // Freeze the entire evidence corpus; any attempted write throws in strict mode.
    const documents = deepFreeze(structuredClone(fixtureDocuments));
    const sections = deepFreeze(structuredClone(fixtureSections));
    const spans = deepFreeze(structuredClone(fixtureSpans));
    const facts = deepFreeze(structuredClone(fixtureFacts));
    const before = JSON.stringify({ documents, sections, spans, facts });

    let state = emptyNotesState;
    for (const section of sections) {
      state = addNote(state, { kind: "section", id: section.id }, `Note on ${section.title}`);
    }
    for (const span of spans) {
      state = addNote(state, { kind: "span", id: span.id }, "Span-level annotation");
    }
    state = removeNote(state, state.notes[0]!.id);

    expect(state.notes.length).toBe(sections.length + spans.length - 1);
    expect(JSON.stringify({ documents, sections, spans, facts })).toBe(before);
  });

  it("stores anchors by reference id only — notes carry no source text", () => {
    const state = addNote(
      emptyNotesState,
      { kind: "span", id: fixtureSpans[0]!.id },
      "Independent annotation",
    );
    const note = state.notes[0]!;
    expect(Object.keys(note).sort()).toEqual(["anchor", "body", "createdAt", "id"]);
    expect(Object.keys(note.anchor).sort()).toEqual(["id", "kind"]);
  });
});

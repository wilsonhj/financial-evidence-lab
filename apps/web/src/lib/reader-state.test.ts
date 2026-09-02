import { describe, expect, it } from "vitest";

import { emptyNotesState } from "./notes";
import { initReaderState, readerReducer, type ReaderState } from "./reader-state";

const BASE: ReaderState = initReaderState("doc-1", "sec-1", null);

describe("initReaderState", () => {
  it("builds fresh state for a document id with an empty notes overlay", () => {
    expect(initReaderState("doc-1", "sec-1", "span-1")).toEqual({
      documentId: "doc-1",
      activeSectionId: "sec-1",
      selectedSpanId: "span-1",
      notes: emptyNotesState,
    });
  });
});

describe("readerReducer: reset", () => {
  it("replaces state entirely for a new document id, discarding stale selection and notes", () => {
    const withNote = readerReducer(BASE, {
      type: "add-note",
      anchor: { kind: "section", id: "sec-1" },
      body: "Watch this.",
    });
    const withSelection = readerReducer(withNote, { type: "select-span", spanId: "span-9" });

    const next = readerReducer(withSelection, {
      type: "reset",
      documentId: "doc-2",
      activeSectionId: "sec-2",
      selectedSpanId: null,
    });

    expect(next).toEqual({
      documentId: "doc-2",
      activeSectionId: "sec-2",
      selectedSpanId: null,
      notes: emptyNotesState,
    });
  });

  it("is idempotent-shaped: resetting to the same document id still yields empty notes", () => {
    const withNote = readerReducer(BASE, {
      type: "add-note",
      anchor: { kind: "section", id: "sec-1" },
      body: "Note.",
    });
    const next = readerReducer(withNote, {
      type: "reset",
      documentId: "doc-1",
      activeSectionId: "sec-1",
      selectedSpanId: null,
    });
    expect(next.notes.notes).toHaveLength(0);
  });
});

describe("readerReducer: select-section", () => {
  it("updates only activeSectionId", () => {
    const next = readerReducer(BASE, { type: "select-section", sectionId: "sec-7" });
    expect(next).toEqual({ ...BASE, activeSectionId: "sec-7" });
  });
});

describe("readerReducer: select-span", () => {
  it("sets selectedSpanId", () => {
    const next = readerReducer(BASE, { type: "select-span", spanId: "span-3" });
    expect(next.selectedSpanId).toBe("span-3");
  });

  it("clears selectedSpanId with null (toggling a span off)", () => {
    const selected = readerReducer(BASE, { type: "select-span", spanId: "span-3" });
    const cleared = readerReducer(selected, { type: "select-span", spanId: null });
    expect(cleared.selectedSpanId).toBeNull();
  });

  it("leaves activeSectionId and notes untouched", () => {
    const next = readerReducer(BASE, { type: "select-span", spanId: "span-3" });
    expect(next.activeSectionId).toBe(BASE.activeSectionId);
    expect(next.notes).toBe(BASE.notes);
  });
});

describe("readerReducer: add-note / remove-note", () => {
  it("appends a note anchored to the given section or span", () => {
    const next = readerReducer(BASE, {
      type: "add-note",
      anchor: { kind: "span", id: "span-1" },
      body: "Check the restated figure.",
    });
    expect(next.notes.notes).toHaveLength(1);
    expect(next.notes.notes[0]).toMatchObject({
      anchor: { kind: "span", id: "span-1" },
      body: "Check the restated figure.",
    });
  });

  it("removes a note by id without touching selection or outline focus", () => {
    const withNote = readerReducer(BASE, {
      type: "add-note",
      anchor: { kind: "section", id: "sec-1" },
      body: "Temp note.",
    });
    const noteId = withNote.notes.notes[0]!.id;
    const next = readerReducer(withNote, { type: "remove-note", noteId });
    expect(next.notes.notes).toHaveLength(0);
    expect(next.activeSectionId).toBe(BASE.activeSectionId);
    expect(next.selectedSpanId).toBe(BASE.selectedSpanId);
  });

  it("removing an unknown note id is a no-op", () => {
    const next = readerReducer(BASE, { type: "remove-note", noteId: "does-not-exist" });
    expect(next).toEqual(BASE);
  });
});

describe("readerReducer: purity", () => {
  it("never mutates the input state object", () => {
    const before = JSON.parse(JSON.stringify(BASE));
    readerReducer(BASE, { type: "select-section", sectionId: "sec-9" });
    readerReducer(BASE, { type: "select-span", spanId: "span-9" });
    readerReducer(BASE, {
      type: "add-note",
      anchor: { kind: "section", id: "sec-1" },
      body: "x",
    });
    expect(BASE).toEqual(before);
  });
});

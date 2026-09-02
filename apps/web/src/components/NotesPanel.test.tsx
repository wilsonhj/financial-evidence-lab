import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { addNote, emptyNotesState, type NoteAnchor } from "../lib/notes";
import { byTag, findOne } from "../lib/test-support/shallow-tree";

// NotesPanel keeps its draft text in useState. To exercise onSubmit with a
// specific draft value (without a DOM to type into), stub useState so the
// test controls exactly what the "current" draft is for one call.
const useStateMock = vi.fn();
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return { ...actual, useState: (init: unknown) => useStateMock(init) };
});

import { NotesPanel } from "./NotesPanel";

const SECTION_ANCHOR: NoteAnchor = { kind: "section", id: "sec-1" };
const describeAnchor = (anchor: NoteAnchor) => `anchor:${anchor.kind}:${anchor.id}`;

describe("NotesPanel rendering", () => {
  it("names the analyst-notes region and labels the draft field with the current anchor", () => {
    useStateMock.mockReturnValue(["", vi.fn()]);
    const markup = renderToStaticMarkup(
      <NotesPanel
        notes={emptyNotesState}
        anchor={SECTION_ANCHOR}
        anchorLabel="Section: Part I"
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        describeAnchor={describeAnchor}
      />,
    );
    expect(markup).toContain('aria-label="Analyst notes"');
    expect(markup).toContain("Section: Part I");
    expect(markup).toContain('for="note-draft"');
    expect(markup).toContain('id="note-draft"');
  });

  it("disables submission until something is selected and text is entered", () => {
    useStateMock.mockReturnValue(["", vi.fn()]);
    const noAnchor = renderToStaticMarkup(
      <NotesPanel
        notes={emptyNotesState}
        anchor={null}
        anchorLabel="nothing selected"
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        describeAnchor={describeAnchor}
      />,
    );
    expect(noAnchor).toContain("disabled");
  });

  it("lists existing notes with a remove control and their anchor description", () => {
    useStateMock.mockReturnValue(["", vi.fn()]);
    const state = addNote(emptyNotesState, SECTION_ANCHOR, "Watch this line item.", {
      id: "note-1",
      createdAt: "2026-05-01T12:34:00Z",
    });
    const markup = renderToStaticMarkup(
      <NotesPanel
        notes={state}
        anchor={SECTION_ANCHOR}
        anchorLabel="Section: Part I"
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        describeAnchor={describeAnchor}
      />,
    );
    expect(markup).toContain("Watch this line item.");
    expect(markup).toContain("Remove");
    expect(markup).toContain("anchor:section:sec-1");
  });
});

describe("NotesPanel callbacks", () => {
  it("submitting a non-empty draft calls onAdd with the anchor and trimmed body, then clears the draft", () => {
    const setDraft = vi.fn();
    useStateMock.mockReturnValue(["  Check the restated figure.  ", setDraft]);
    const onAdd = vi.fn();
    const element = NotesPanel({
      notes: emptyNotesState,
      anchor: SECTION_ANCHOR,
      anchorLabel: "Section: Part I",
      onAdd,
      onRemove: vi.fn(),
      describeAnchor,
    });
    const form = findOne(element, byTag("form"));
    (form.props as { onSubmit: (event: { preventDefault: () => void }) => void }).onSubmit({
      preventDefault: vi.fn(),
    });
    expect(onAdd).toHaveBeenCalledWith(SECTION_ANCHOR, "Check the restated figure.");
    expect(setDraft).toHaveBeenCalledWith("");
  });

  it("submitting a blank draft never calls onAdd", () => {
    useStateMock.mockReturnValue(["   ", vi.fn()]);
    const onAdd = vi.fn();
    const element = NotesPanel({
      notes: emptyNotesState,
      anchor: SECTION_ANCHOR,
      anchorLabel: "Section: Part I",
      onAdd,
      onRemove: vi.fn(),
      describeAnchor,
    });
    const form = findOne(element, byTag("form"));
    (form.props as { onSubmit: (event: { preventDefault: () => void }) => void }).onSubmit({
      preventDefault: vi.fn(),
    });
    expect(onAdd).not.toHaveBeenCalled();
  });

  it("submitting with nothing selected never calls onAdd", () => {
    useStateMock.mockReturnValue(["A note.", vi.fn()]);
    const onAdd = vi.fn();
    const element = NotesPanel({
      notes: emptyNotesState,
      anchor: null,
      anchorLabel: "nothing selected",
      onAdd,
      onRemove: vi.fn(),
      describeAnchor,
    });
    const form = findOne(element, byTag("form"));
    (form.props as { onSubmit: (event: { preventDefault: () => void }) => void }).onSubmit({
      preventDefault: vi.fn(),
    });
    expect(onAdd).not.toHaveBeenCalled();
  });

  it("clicking Remove on a note calls onRemove with that note's id", () => {
    useStateMock.mockReturnValue(["", vi.fn()]);
    const state = addNote(emptyNotesState, SECTION_ANCHOR, "Note body", { id: "note-9" });
    const onRemove = vi.fn();
    const element = NotesPanel({
      notes: state,
      anchor: SECTION_ANCHOR,
      anchorLabel: "Section: Part I",
      onAdd: vi.fn(),
      onRemove,
      describeAnchor,
    });
    const removeButton = findOne(
      element,
      (el) => el.type === "button" && (el.props as { children?: unknown }).children === "Remove",
    );
    (removeButton.props as { onClick: () => void }).onClick();
    expect(onRemove).toHaveBeenCalledWith("note-9");
  });
});

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

// NotesPanel calls useState twice, in order: draft text, then the
// visually-hidden live-region announcement. Queue both return values so each
// call gets its own tuple instead of sharing one mocked setter.
function stubUseState(draft: string, setDraft: (value: string) => void = vi.fn()) {
  const setAnnouncement = vi.fn();
  useStateMock.mockReturnValueOnce([draft, setDraft]).mockReturnValueOnce(["", setAnnouncement]);
  return { setAnnouncement };
}

describe("NotesPanel rendering", () => {
  it("names the analyst-notes region and labels the draft field with the current anchor", () => {
    stubUseState("");
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

  // WCAG 2.2 SC 4.1.3 (Status Messages): note add/remove is a client-side
  // state update with no page navigation and no focus move, so it needs a
  // role="status" live region a screen reader announces without the user
  // having to be focused on the notes list.
  it("carries a visually-hidden role=status live region for add/remove outcomes", () => {
    stubUseState("");
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
    expect(markup).toContain('role="status"');
    expect(markup).toContain('aria-live="polite"');
  });

  it("disables submission until something is selected and text is entered", () => {
    stubUseState("");
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
    stubUseState("");
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
    const { setAnnouncement } = stubUseState("  Check the restated figure.  ", setDraft);
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
    // 4.1.3: the live region is told about the outcome even though the
    // visible list update alone would not reliably reach an AT user.
    expect(setAnnouncement).toHaveBeenCalledWith("Note added.");
  });

  it("submitting a blank draft never calls onAdd", () => {
    stubUseState("   ");
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
    stubUseState("A note.");
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

  it("clicking Remove on a note calls onRemove with that note's id and announces it", () => {
    const { setAnnouncement } = stubUseState("");
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
    expect(setAnnouncement).toHaveBeenCalledWith("Note removed.");
  });
});

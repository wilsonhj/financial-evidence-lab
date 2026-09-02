import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { buildOutline } from "../lib/outline";
import type { SectionRecord } from "../lib/contracts";
import { byTag, findAll, findOne } from "../lib/test-support/shallow-tree";

// OutlineNav only uses useRef (to focus the active item after a keyboard
// move) and useEffect (to run that focus once the DOM has the new item).
// Neither is needed to prove onSelect fires with the right id, so both are
// stubbed to call the component as a plain function outside a real render.
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    useRef: (init: unknown) => ({ current: init }),
    useEffect: () => {},
  };
});

import { OutlineNav } from "./OutlineNav";

function section(id: string, order: number, level = 1): SectionRecord {
  return {
    id,
    document_version_id: "v1",
    order,
    level,
    title: `Section ${id}`,
    start_char: 0,
    end_char: 0,
    content: "",
  };
}

const model = buildOutline([section("a", 1), section("b", 2), section("c", 3)]);

interface ItemButtonProps {
  children: string;
  onClick: () => void;
}

interface ListProps {
  onKeyDown: (event: { key: string; preventDefault: () => void }) => void;
}

describe("OutlineNav rendering", () => {
  it("labels the outline navigation landmark and lists every section", () => {
    const markup = renderToStaticMarkup(
      <OutlineNav model={model} activeId="a" onSelect={vi.fn()} />,
    );
    expect(markup).toContain('aria-label="Filing outline"');
    expect(markup).toContain("Section a");
    expect(markup).toContain("Section b");
    expect(markup).toContain("Section c");
  });

  it("marks the active entry current and keeps it the sole roving tab stop", () => {
    const markup = renderToStaticMarkup(
      <OutlineNav model={model} activeId="b" onSelect={vi.fn()} />,
    );
    expect(markup).toContain('aria-current="true"');
    // Exactly one item is in the tab order; the rest are tabIndex="-1".
    expect((markup.match(/tabindex="0"/g) ?? []).length).toBe(1);
  });
});

describe("OutlineNav selection callbacks", () => {
  it("clicking an outline item calls onSelect with its section id", () => {
    const onSelect = vi.fn();
    const element = OutlineNav({ model, activeId: "a", onSelect });
    const buttons = findAll(element, byTag("button"));
    const buttonForC = buttons.find(
      (button) => (button.props as ItemButtonProps).children === "Section c",
    )!;
    (buttonForC.props as ItemButtonProps).onClick();
    expect(onSelect).toHaveBeenCalledWith("c");
  });

  it("ArrowDown moves to the next section in document order", () => {
    const onSelect = vi.fn();
    const element = OutlineNav({ model, activeId: "a", onSelect });
    const list = findOne(element, byTag("ul"));
    (list.props as ListProps).onKeyDown({ key: "ArrowDown", preventDefault: vi.fn() });
    expect(onSelect).toHaveBeenCalledWith("b");
  });

  it("ArrowUp moves to the previous section and stops at the first", () => {
    const onSelect = vi.fn();
    const element = OutlineNav({ model, activeId: "a", onSelect });
    const list = findOne(element, byTag("ul"));
    (list.props as ListProps).onKeyDown({ key: "ArrowUp", preventDefault: vi.fn() });
    // previousOutlineId clamps to the first entry itself.
    expect(onSelect).toHaveBeenCalledWith("a");
  });

  it("Home and End jump to the first and last sections", () => {
    const onSelect = vi.fn();
    const element = OutlineNav({ model, activeId: "b", onSelect });
    const list = findOne(element, byTag("ul"));
    (list.props as ListProps).onKeyDown({ key: "Home", preventDefault: vi.fn() });
    (list.props as ListProps).onKeyDown({ key: "End", preventDefault: vi.fn() });
    expect(onSelect).toHaveBeenNthCalledWith(1, "a");
    expect(onSelect).toHaveBeenNthCalledWith(2, "c");
  });

  it("prevents default browser scrolling for the keys it handles", () => {
    const element = OutlineNav({ model, activeId: "a", onSelect: vi.fn() });
    const list = findOne(element, byTag("ul"));
    const preventDefault = vi.fn();
    (list.props as ListProps).onKeyDown({ key: "ArrowDown", preventDefault });
    expect(preventDefault).toHaveBeenCalled();
  });

  it("ignores keys it does not handle", () => {
    const onSelect = vi.fn();
    const element = OutlineNav({ model, activeId: "a", onSelect });
    const list = findOne(element, byTag("ul"));
    (list.props as ListProps).onKeyDown({ key: "Tab", preventDefault: vi.fn() });
    expect(onSelect).not.toHaveBeenCalled();
  });
});

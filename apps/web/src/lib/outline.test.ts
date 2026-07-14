import { describe, expect, it } from "vitest";

import type { SectionRecord } from "./contracts";
import {
  buildOutline,
  firstOutlineId,
  lastOutlineId,
  nextOutlineId,
  previousOutlineId,
} from "./outline";

const DOC = "aaaaaaaa-0000-4000-8000-00000000ffff";

function section(id: string, order: number, level: number, parent_id?: string): SectionRecord {
  return {
    id,
    document_version_id: DOC,
    parent_id,
    order,
    level,
    title: `Section ${id}`,
    content: "",
  };
}

describe("buildOutline", () => {
  it("orders nodes by section order regardless of input order", () => {
    const model = buildOutline([
      section("c", 3, 3, "b"),
      section("a", 1, 1),
      section("b", 2, 2, "a"),
    ]);
    expect(model.nodes.map((node) => node.id)).toEqual(["a", "b", "c"]);
  });

  it("exposes id, title, and depth for each node (the full production surface)", () => {
    const model = buildOutline([
      section("part", 1, 1),
      section("item", 2, 2, "part"),
      section("statement", 3, 3, "item"),
    ]);
    expect(model.nodes).toEqual([
      { id: "part", title: "Section part", depth: 1 },
      { id: "item", title: "Section item", depth: 2 },
      { id: "statement", title: "Section statement", depth: 3 },
    ]);
  });

  it("handles an empty section list", () => {
    const model = buildOutline([]);
    expect(model.nodes).toEqual([]);
    expect(firstOutlineId(model)).toBeNull();
    expect(lastOutlineId(model)).toBeNull();
    expect(nextOutlineId(model, null)).toBeNull();
  });
});

describe("outline keyboard navigation", () => {
  const model = buildOutline([
    section("a", 1, 1),
    section("b", 2, 2, "a"),
    section("c", 3, 2, "a"),
  ]);

  it("moves forward in document order and stops at the end", () => {
    expect(nextOutlineId(model, "a")).toBe("b");
    expect(nextOutlineId(model, "b")).toBe("c");
    expect(nextOutlineId(model, "c")).toBe("c");
  });

  it("moves backward in document order and stops at the start", () => {
    expect(previousOutlineId(model, "c")).toBe("b");
    expect(previousOutlineId(model, "a")).toBe("a");
  });

  it("starts from the first entry when nothing is focused", () => {
    expect(nextOutlineId(model, null)).toBe("a");
    expect(previousOutlineId(model, null)).toBe("a");
  });

  it("recovers to the first entry for an unknown id", () => {
    expect(nextOutlineId(model, "missing")).toBe("a");
  });

  it("exposes Home/End targets", () => {
    expect(firstOutlineId(model)).toBe("a");
    expect(lastOutlineId(model)).toBe("c");
  });
});

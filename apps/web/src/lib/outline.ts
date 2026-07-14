import type { SectionRecord } from "./contracts";

/** Flattened outline entry for the keyboard-navigable filing outline. */
export interface OutlineNode {
  id: string;
  title: string;
  /** Nesting depth for indentation and aria-level (1-based). */
  depth: number;
}

export interface OutlineModel {
  /** Document order, matching the rendered section order. */
  nodes: OutlineNode[];
}

/**
 * Builds the outline navigation model from extracted sections. Sections are
 * sorted by their extraction order; depth comes from the section level so the
 * outline mirrors the filing hierarchy (Part > Item > Statement/Note). The
 * model is a flat ordered list — navigation and rendering never needed the
 * parent/child graph, so none is built.
 */
export function buildOutline(sections: readonly SectionRecord[]): OutlineModel {
  const nodes = [...sections]
    .sort((a, b) => a.order - b.order)
    .map((section) => ({ id: section.id, title: section.title, depth: section.level }));
  return { nodes };
}

/** Id of the outline entry after `currentId` in document order (wraps nothing). */
export function nextOutlineId(model: OutlineModel, currentId: string | null): string | null {
  if (model.nodes.length === 0) return null;
  if (currentId === null) return model.nodes[0]?.id ?? null;
  const index = model.nodes.findIndex((node) => node.id === currentId);
  if (index === -1) return model.nodes[0]?.id ?? null;
  return model.nodes[Math.min(index + 1, model.nodes.length - 1)]?.id ?? null;
}

/** Id of the outline entry before `currentId` in document order. */
export function previousOutlineId(model: OutlineModel, currentId: string | null): string | null {
  if (model.nodes.length === 0) return null;
  if (currentId === null) return model.nodes[0]?.id ?? null;
  const index = model.nodes.findIndex((node) => node.id === currentId);
  if (index === -1) return model.nodes[0]?.id ?? null;
  return model.nodes[Math.max(index - 1, 0)]?.id ?? null;
}

export function firstOutlineId(model: OutlineModel): string | null {
  return model.nodes[0]?.id ?? null;
}

export function lastOutlineId(model: OutlineModel): string | null {
  return model.nodes[model.nodes.length - 1]?.id ?? null;
}

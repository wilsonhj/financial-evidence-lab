import type { ReactElement, ReactNode } from "react";

/**
 * Minimal shallow-render tree walker for component tests.
 *
 * The suite has no DOM (vitest runs with `environment: "node"`, no jsdom) and
 * no dependency on `react-test-renderer`, so interaction tests cannot mount a
 * real DOM and dispatch events. Instead, tests call a "use client" component
 * as a plain function (its JSX return value is just a tree of plain
 * objects — no rendering occurs) and use these helpers to locate an element
 * by host tag and invoke its event-handler prop directly with the arguments
 * the test wants to exercise. Components that use `useMemo` / `useRef` /
 * `useEffect` internally need those hooks stubbed first (see
 * `stubClientHooks`) since no dispatcher is installed outside a real render.
 */

function isElement(node: unknown): node is ReactElement {
  return typeof node === "object" && node !== null && "type" in node && "props" in node;
}

/** Depth-first search of a shallow element tree for every element matching `predicate`. */
export function findAll(
  node: ReactNode,
  predicate: (element: ReactElement) => boolean,
): ReactElement[] {
  const results: ReactElement[] = [];
  const visit = (current: ReactNode): void => {
    if (current === null || current === undefined || typeof current === "boolean") return;
    if (Array.isArray(current)) {
      for (const child of current) visit(child);
      return;
    }
    if (!isElement(current)) return;
    if (predicate(current)) results.push(current);
    const children = (current.props as { children?: ReactNode }).children;
    if (children !== undefined) visit(children);
  };
  visit(node);
  return results;
}

/** Like `findAll`, but requires exactly one match. */
export function findOne(
  node: ReactNode,
  predicate: (element: ReactElement) => boolean,
): ReactElement {
  const matches = findAll(node, predicate);
  if (matches.length !== 1) {
    throw new Error(`expected exactly one matching element, found ${matches.length}`);
  }
  return matches[0]!;
}

/** Predicate matching a host element by its DOM tag name (e.g. "button"). */
export function byTag(tag: string): (element: ReactElement) => boolean {
  return (element) => element.type === tag;
}

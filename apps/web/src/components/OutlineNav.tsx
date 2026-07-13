"use client";

import { useEffect, useRef } from "react";

import type { OutlineModel } from "@/lib/outline";
import { firstOutlineId, lastOutlineId, nextOutlineId, previousOutlineId } from "@/lib/outline";

export interface OutlineNavProps {
  model: OutlineModel;
  activeId: string | null;
  onSelect: (sectionId: string) => void;
}

/**
 * Keyboard-navigable filing outline: a roving-tabindex listbox-style nav.
 * ArrowUp/ArrowDown move through document order, Home/End jump to the ends,
 * Enter/Space activate (buttons handle that natively).
 */
export function OutlineNav({ model, activeId, onSelect }: OutlineNavProps) {
  const containerRef = useRef<HTMLElement>(null);
  const focusPending = useRef(false);

  useEffect(() => {
    if (!focusPending.current || !activeId) return;
    focusPending.current = false;
    containerRef.current
      ?.querySelector<HTMLButtonElement>(`[data-outline-id="${activeId}"]`)
      ?.focus();
  }, [activeId]);

  const moveTo = (id: string | null) => {
    if (!id) return;
    focusPending.current = true;
    onSelect(id);
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        moveTo(nextOutlineId(model, activeId));
        break;
      case "ArrowUp":
        event.preventDefault();
        moveTo(previousOutlineId(model, activeId));
        break;
      case "Home":
        event.preventDefault();
        moveTo(firstOutlineId(model));
        break;
      case "End":
        event.preventDefault();
        moveTo(lastOutlineId(model));
        break;
      default:
        break;
    }
  };

  return (
    <nav className="outline-nav" aria-label="Filing outline" ref={containerRef}>
      <h2 id="outline-heading">Outline</h2>
      <ul onKeyDown={handleKeyDown} aria-labelledby="outline-heading">
        {model.nodes.map((node) => (
          <li key={node.id}>
            <button
              type="button"
              className="outline-item"
              data-outline-id={node.id}
              style={{ paddingLeft: `${0.4 + (node.depth - 1) * 0.9}rem` }}
              aria-current={node.id === activeId}
              tabIndex={node.id === (activeId ?? model.nodes[0]?.id) ? 0 : -1}
              onClick={() => onSelect(node.id)}
            >
              {node.title}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

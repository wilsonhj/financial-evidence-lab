import type { ReactElement, ReactNode } from "react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { findOne, findAll } from "../../lib/test-support/shallow-tree";
const hooks = vi.hoisted(() => ({
  index: 0,
  values: [] as unknown[],
  effects: [] as (() => (() => void) | void)[],
}));
vi.mock("react", async (load) => ({
  ...(await load<typeof import("react")>()),
  useState(initial: unknown) {
    const i = hooks.index++;
    if (!Object.hasOwn(hooks.values, i))
      hooks.values[i] = typeof initial === "function" ? initial() : initial;
    return [
      hooks.values[i],
      (next: unknown) => {
        hooks.values[i] = typeof next === "function" ? next(hooks.values[i]) : next;
      },
    ];
  },
  useRef(initial: unknown) {
    const i = hooks.index++;
    return (hooks.values[i] ??= { current: initial });
  },
  useEffect(effect: () => (() => void) | void) {
    hooks.effects.push(effect);
  },
}));
import { ReviewQueue } from "./ReviewQueue";
import { ActionForm } from "./ActionForm";
import { RunEvents } from "./RunEvents";
import { initialFixture } from "../../lib/extraction/fixture";
import { guards, type Schemas } from "../../lib/extraction/contracts";

const props = (node: ReactElement) => node.props as Record<string, unknown>;
function view(render: () => ReactNode) {
  const tree = () => {
    hooks.index = 0;
    return render();
  };
  const field = (id: string, value: string) => {
    const node = findOne(tree(), (e) => props(e).id === id);
    (props(node).onChange as (e: unknown) => void)({ target: { value } });
  };
  const button = (name: string) =>
    findOne(tree(), (e) => e.type === "button" && props(e).children === name);
  const click = (name: string) => (props(button(name)).onClick as () => void)();
  const submit = () =>
    (props(findOne(tree(), (e) => e.type === "form")).onSubmit as (e: unknown) => void)({
      preventDefault() {},
    });
  const status = () => String(props(findOne(tree(), (e) => props(e).role === "status")).children);
  return { tree, field, button, click, submit, status };
}
const selected = () => ({ ...initialFixture().proposals[0]!, conflict_ids: [] });
function resultFor(id: string): Schemas["ReviewResult"] {
  return {
    review_id: "00000000-0000-4000-8000-000000000001",
    action: "accept",
    proposal_states: { [id]: "accepted" },
    proposal_versions: { [id]: 2 },
    approved_record_ids: [],
    approved_versions: [],
    resolved_conflicts: [],
  };
}
beforeEach(() => {
  hooks.index = 0;
  hooks.values = [];
  hooks.effects = [];
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("review interaction state", () => {
  it("contains role-aware controls and preserves one body/key across a network retry", async () => {
    const p = selected(),
      fetcher = vi
        .fn()
        .mockRejectedValueOnce(new Error("Network interrupted"))
        .mockResolvedValueOnce(Response.json(resultFor(p.id)));
    vi.stubGlobal("fetch", fetcher);
    const v = view(() =>
      ReviewQueue({ proposals: [p], permissions: initialFixture().permissions }),
    );
    const checkbox = findOne(v.tree(), (e) => e.type === "input" && props(e).type === "checkbox");
    (props(checkbox).onChange as (e: unknown) => void)({ target: { checked: true } });
    v.field("review-reason", "Checked exact evidence");
    v.submit();
    await vi.waitFor(() => expect(v.status()).toContain("Network interrupted"));
    v.submit();
    await vi.waitFor(() => expect(v.status()).toContain("Atomic accept completed"));
    expect(fetcher.mock.calls[0]?.[1].body).toBe(fetcher.mock.calls[1]?.[1].body);
    expect(fetcher.mock.calls[0]?.[1].headers["idempotency-key"]).toBe(
      fetcher.mock.calls[1]?.[1].headers["idempotency-key"],
    );
  });
  it("preserves a stale draft, refreshes membership and requires explicit resubmission", async () => {
    const p = selected();
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(Response.json({}, { status: 412 }))
      .mockResolvedValueOnce(Response.json(initialFixture().permissions))
      .mockResolvedValueOnce(Response.json({ ...p, version: 2 }));
    vi.stubGlobal("fetch", fetcher);
    const v = view(() =>
      ReviewQueue({ proposals: [p], permissions: initialFixture().permissions }),
    );
    (props(findOne(v.tree(), (e) => e.type === "input")).onChange as (e: unknown) => void)({
      target: { checked: true },
    });
    v.field("review-action", "edit");
    v.field("review-reason", "Preserve this reason");
    const patch = JSON.stringify([
      { extraction_id: p.id, payload: p.payload, evidence: p.evidence },
    ]);
    v.field("review-replacement", patch);
    v.submit();
    await vi.waitFor(() => expect(v.status()).toContain("draft is preserved"));
    expect(props(v.button("Submit atomic review")).disabled).toBe(true);
    v.click("Refresh comparison and permissions");
    await vi.waitFor(() => expect(v.status()).toContain("Current versions loaded"));
    expect(props(findOne(v.tree(), (e) => props(e).id === "review-replacement")).value).toBe(patch);
    expect(props(v.button("Submit atomic review")).disabled).toBe(true);
    v.click("Use refreshed versions");
    expect(props(v.button("Submit atomic review")).disabled).toBe(false);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });
  it("loads complete group membership and does not infer a winner", async () => {
    const state = initialFixture(),
      p = state.proposals[0]!;
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(Response.json(state.permissions))
        .mockResolvedValueOnce(Response.json(state.conflicts[0])),
    );
    const v = view(() => ReviewQueue({ proposals: [p], permissions: state.permissions }));
    (props(findOne(v.tree(), (e) => e.type === "input")).onChange as (e: unknown) => void)({
      target: { checked: true },
    });
    v.click("Load complete conflict context");
    await vi.waitFor(() => expect(v.status()).toContain("Choose the winners explicitly"));
    const winner = findAll(v.tree(), (e) => e.type === "input" && props(e).type === "checkbox")[1]!;
    expect(props(winner).checked).toBe(false);
    (props(winner).onChange as (e: unknown) => void)({ target: { checked: true } });
    expect(props(findAll(v.tree(), (e) => e.type === "input")[1]!).checked).toBe(true);
  });
  it("keeps viewer actions disabled and handles permission refresh failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({}, { status: 403 })));
    const permissions = { ...initialFixture().permissions, allowed_actions: [] };
    const v = view(() => ReviewQueue({ proposals: [], permissions }));
    expect(props(v.button("Submit atomic review")).disabled).toBe(true);
    v.click("Refresh comparison and permissions");
    await vi.waitFor(() => expect(v.status()).toContain("permissions"));
  });
});

describe("run and correction commands", () => {
  it.each(["create", "cancel", "rerun", "correct"] as const)(
    "disables %s without the authoritative permission",
    (action) => {
      const v = view(() => ActionForm({ action, path: "runs", permitted: false }));
      expect(
        props(findOne(v.tree(), (e) => e.type === "button" && props(e).type === "submit")).disabled,
      ).toBe(true);
    },
  );
  it.each(["create", "rerun", "cancel"] as const)(
    "submits %s and displays the returned immutable run link",
    async (action) => {
      const state = initialFixture(),
        fetcher = vi
          .fn()
          .mockResolvedValue(Response.json(state.runs[0], { headers: { etag: '"new"' } }));
      vi.stubGlobal("fetch", fetcher);
      const v = view(() =>
        ActionForm({ action, path: "runs", permitted: true, initialEtag: '"old"' }),
      );
      if (action !== "cancel")
        v.field(
          `${action}-draft`,
          action === "rerun"
            ? "Same source"
            : JSON.stringify({
                entity_id: state.runs[0]!.entity_id,
                as_of: state.runs[0]!.as_of,
                modes: ["kpi"],
                source_span_ids: [state.proposals[0]!.evidence[0]!.source_span_id],
              }),
        );
      v.submit();
      await vi.waitFor(() => expect(v.status()).toMatch(/Action committed|Cancellation requested/));
      expect(fetcher.mock.calls[0]?.[1].method).toBe(action === "cancel" ? "DELETE" : "POST");
    },
  );
  it("retains a correction after 412, compares the head and appends after explicit acknowledgement", async () => {
    const approved = initialFixture().versions[0]!,
      fetcher = vi
        .fn()
        .mockResolvedValueOnce(Response.json({}, { status: 412 }))
        .mockResolvedValueOnce(
          Response.json({ ...approved, version: 2 }, { headers: { etag: '"2"' } }),
        )
        .mockResolvedValueOnce(Response.json({ ...approved, version: 3 }));
    vi.stubGlobal("fetch", fetcher);
    const v = view(() =>
      ActionForm({
        action: "correct",
        path: `approved/${approved.record_id}/corrections`,
        permitted: true,
        initialEtag: '"1"',
      }),
    );
    const body = JSON.stringify({
      reason: "Preserved draft",
      payload: approved.payload,
      evidence: approved.evidence,
    });
    v.field("correct-draft", body);
    v.submit();
    await vi.waitFor(() => expect(v.status()).toContain("draft is preserved"));
    v.click("Refresh current version for comparison");
    await vi.waitFor(() => expect(v.button("Use refreshed version")).toBeTruthy());
    expect(props(findOne(v.tree(), (e) => props(e).id === "correct-draft")).value).toBe(body);
    v.click("Use refreshed version");
    v.submit();
    await vi.waitFor(() => expect(v.status()).toContain("Action committed"));
    expect(fetcher.mock.calls[2]?.[1].headers["if-match"]).toBe('"2"');
  });
  it("rejects malformed edits locally and does not fabricate an action receipt", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const v = view(() => ActionForm({ action: "correct", path: "approved", permitted: true }));
    v.field("correct-draft", "{}");
    v.submit();
    await vi.waitFor(() => expect(v.status()).toContain("complete valid replacement"));
    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe("live event component", () => {
  it("retains only 500 events, exposes terminal status and reconnects explicitly", async () => {
    const run = initialFixture().runs[0]!;
    const events = Array.from({ length: 505 }, (_, i) => ({
      schema_version: "extraction-event/v1",
      id: i + 1,
      run_id: run.id,
      type: i === 504 ? "run_succeeded" : "step_completed",
      occurred_at: run.created_at,
      payload: {},
    }));
    expect(events.every(guards.event)).toBe(true);
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(events.map((e) => `id: ${e.id}\ndata: ${JSON.stringify(e)}\n\n`).join(""), {
            headers: { "content-type": "text/event-stream" },
          }),
        ),
    );
    const v = view(() => RunEvents({ runId: run.id }));
    v.tree();
    const cleanup = hooks.effects[0]!();
    await vi.waitFor(() => expect(v.status()).toBe("complete"));
    expect(findAll(v.tree(), (e) => e.type === "tr")).toHaveLength(501);
    v.click("Reconnect live events");
    expect(hooks.values[2]).toBe(1);
    cleanup?.();
  });
});

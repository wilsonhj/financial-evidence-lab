import { describe, expect, it, vi } from "vitest";
import { createSource } from "./source";
import { initialFixture } from "./fixture";
import { guards } from "./contracts";

describe("explicit extraction source", () => {
  it("rejects impossible calendar cutoffs instead of browser date rollover", () => {
    expect(guards.run({ ...initialFixture().runs[0], as_of: "2026-02-30T00:00:00Z" })).toBe(false);
  });
  it("binds fixture reads to generated contracts and exposes synthetic mode", async () => {
    const source = createSource({ mode: "fixture" });
    expect(source.mode).toBe("fixture");
    const { data: permissions } = await source.read("permissions", guards.permissions);
    expect(permissions.allowed_actions).toContain("edit");
    const { data: page } = await source.read(
      "proposals",
      guards.proposals,
      new URLSearchParams({ limit: "1" }),
    );
    expect(page.items).toHaveLength(1);
    expect(page.next_cursor).not.toBeNull();
    const next = await source.read(
      "proposals",
      guards.proposals,
      new URLSearchParams({ limit: "1", cursor: page.next_cursor! }),
    );
    expect(next.data.items[0]?.id).not.toBe(page.items[0]?.id);
  });
  it("binds a fixture cursor to the limit and filter that produced it", async () => {
    const source = createSource({ mode: "fixture" });
    const { data: page } = await source.read(
      "proposals",
      guards.proposals,
      new URLSearchParams({ limit: "1", state: "needs_review" }),
    );
    expect(page.next_cursor).not.toBeNull();
    // Reinterpreting an offset under a different page size would silently skip rows.
    await expect(
      source.read(
        "proposals",
        guards.proposals,
        new URLSearchParams({ limit: "2", cursor: page.next_cursor! }),
      ),
    ).rejects.toThrow();
    // Carrying a cursor across a filter change would page a different list.
    await expect(
      source.read(
        "proposals",
        guards.proposals,
        new URLSearchParams({ limit: "1", state: "accepted", cursor: page.next_cursor! }),
      ),
    ).rejects.toThrow();
  });
  it("never falls back from configured HTTP after a failure", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("private upstream failure"));
    const source = createSource(
      {
        mode: "http",
        baseUrl: "https://api.example",
        token: "fixture-only",
        workspaceId: "00000000-0000-4000-8000-000000000001",
      },
      fetcher,
    );
    await expect(source.read("proposals", guards.proposals)).rejects.toThrow("HTTP 502");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("returns an honest error for invisible fixture resources", async () => {
    const source = createSource({ mode: "fixture" });
    await expect(
      source.read("runs/00000000-0000-4000-8000-999999999999", guards.run),
    ).rejects.toThrow("HTTP 404");
  });
});

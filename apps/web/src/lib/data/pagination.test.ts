import { describe, expect, it, vi } from "vitest";
import { HttpEvidenceSource, EvidenceContractError } from "./http-source";
import { fixtureEvidenceSource } from "./fixture-source";
import { fixtureDocuments } from "../fixtures/synthetic-filing";
import { loadReaderData } from "../reader-loader";

const entity = fixtureDocuments[0]!.entity_id;
describe("bounded evidence consumers", () => {
  it("requests one explicit entity page with cutoff and pin without reader fanout", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify([fixtureDocuments[0]]), {
          headers: { "X-FEL-Page-Limit": "1", "X-FEL-Next-Cursor": "next" },
        }),
    );
    const source = new HttpEvidenceSource({
      baseUrl: "https://api.test",
      entityIds: [entity],
      token: "secret",
      asOf: "2026-12-31T23:59:59Z",
      corpusVersionId: "pin",
      fetchImpl,
    });
    const page = await source.listDocuments(entity, { limit: 1 });
    expect(page.items).toHaveLength(1);
    expect(page.nextCursor).toBe("next");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const url = new URL((fetchImpl.mock.calls[0] as unknown as [string])[0]);
    expect(url.searchParams.get("limit")).toBe("1");
    expect(url.searchParams.get("corpus_version_id")).toBe("pin");
  });
  it("rejects a repeated continuation instead of looping", async () => {
    const source = new HttpEvidenceSource({
      baseUrl: "https://api.test",
      entityIds: [entity],
      token: "secret",
      fetchImpl: async () =>
        new Response("[]", { headers: { "X-FEL-Page-Limit": "1", "X-FEL-Next-Cursor": "same" } }),
    });
    await expect(source.listDocuments(entity, { limit: 1, cursor: "same" })).rejects.toBeInstanceOf(
      EvidenceContractError,
    );
  });
  it("loads target only first and retains explicit incomplete coverage", async () => {
    const result = await loadReaderData(fixtureEvidenceSource, fixtureDocuments[0]!.id);
    expect(result.kind).toBe("ready");
    if (result.kind === "ready") {
      expect(result.data.documents).toHaveLength(1);
      expect(result.data.siblingPage?.scope).toBe("excluded");
      expect(result.data.siblingPage?.complete).toBe(false);
    }
  });
});

it("rejects wrong target versions and incomplete target-only metadata", async () => {
  const full = (await fixtureEvidenceSource.getReader(fixtureDocuments[0]!.id, {
    includeSiblings: false,
  }))!;
  const source = new HttpEvidenceSource({
    baseUrl: "https://api.test",
    entityIds: [entity],
    token: "secret",
    fetchImpl: async () => new Response(JSON.stringify(full)),
  });
  await expect(
    source.getReader(full.document.meta.id, { includeSiblings: false, documentVersionId: "wrong" }),
  ).rejects.toBeInstanceOf(EvidenceContractError);
  full.sibling_page!.complete = true;
  await expect(
    source.getReader(full.document.meta.id, { includeSiblings: false }),
  ).rejects.toBeInstanceOf(EvidenceContractError);
});

it("does not attach bearer credentials to an absolute continuation URL", async () => {
  const urls: string[] = [];
  const source = new HttpEvidenceSource({
    baseUrl: "https://api.test",
    entityIds: [entity],
    token: "secret",
    fetchImpl: async (url) => {
      urls.push(String(url));
      return new Response(JSON.stringify([fixtureDocuments[0]]), {
        headers: { "X-FEL-Page-Limit": "1" },
      });
    },
  });
  await source.listDocuments(entity, { limit: 1, cursor: "https://attacker.test/steal" });
  expect(new URL(urls[0]!).origin).toBe("https://api.test");
  expect(new URL(urls[0]!).searchParams.get("cursor")).toBe("https://attacker.test/steal");
});

it("uses the original selected target when opening bounded related history", async () => {
  const target = await loadReaderData(fixtureEvidenceSource, fixtureDocuments[0]!.id);
  if (target.kind !== "ready") throw new Error("fixture missing");
  const next = await loadReaderData(fixtureEvidenceSource, target.data.document.id, {
    siblingLimit: 1,
    documentVersionId: target.data.documentVersionId,
    asOf: target.data.scope.as_of,
  });
  expect(next.kind).toBe("ready");
  if (next.kind === "ready") {
    expect(next.data.documentVersionId).toBe(target.data.documentVersionId);
    expect(next.data.scope.as_of).toBe(target.data.scope.as_of);
    expect(next.data.siblingPage?.complete).toBe(true);
  }
});

it("traverses more than 200 fixture records in both directions and rejects cross-scope cursors", async () => {
  const { fixturePage } = await import("./pagination");
  const items = Array.from({ length: 257 }, (_, index) => ({
    id: index,
    published_at: "2026-01-01T00:00:00Z",
  }));
  for (const order of ["asc", "desc"] as const) {
    let page = fixturePage(items, { limit: 50, order }, "scope", EvidenceContractError);
    const visited = [...page.items];
    while (page.nextCursor) {
      const previous = page;
      page = fixturePage(items, { cursor: page.nextCursor }, "scope", EvidenceContractError);
      visited.push(...page.items);
      expect(
        fixturePage(items, { cursor: page.previousCursor! }, "scope", EvidenceContractError).items,
      ).toEqual(previous.items);
    }
    expect(visited.map((item) => item.id)).toEqual(
      (order === "asc" ? items : [...items].reverse()).map((item) => item.id),
    );
    expect(() =>
      fixturePage(items, { cursor: page.previousCursor! }, "another-entity", EvidenceContractError),
    ).toThrow(EvidenceContractError);
  }
});

it("retains an explicitly unpinned reader scope when runtime defaults specify a pin", async () => {
  const body = await fixtureEvidenceSource.getReader(fixtureDocuments[0]!.id, {
    includeSiblings: false,
  });
  const source = new HttpEvidenceSource({
    baseUrl: "https://api.test",
    entityIds: [entity],
    token: "secret",
    corpusVersionId: "runtime-pin",
    fetchImpl: async () => new Response(JSON.stringify(body)),
  });
  await expect(
    source.getReader(fixtureDocuments[0]!.id, { includeSiblings: false, corpusVersionId: "" }),
  ).resolves.toMatchObject({ corpus_version_id: null });
});

it("requires sibling page metadata for an order-only request", async () => {
  const body = await fixtureEvidenceSource.getReader(fixtureDocuments[0]!.id);
  const source = new HttpEvidenceSource({
    baseUrl: "https://api.test",
    entityIds: [entity],
    token: "secret",
    fetchImpl: async () => new Response(JSON.stringify(body)),
  });
  await expect(
    source.getReader(fixtureDocuments[0]!.id, { siblingOrder: "desc" }),
  ).rejects.toBeInstanceOf(EvidenceContractError);
});

it("uses page mode for order-only fixture reader requests", async () => {
  const body = await fixtureEvidenceSource.getReader(fixtureDocuments[0]!.id, {
    siblingOrder: "desc",
  });
  expect(body?.sibling_page?.scope).toBe("page");
});

it.each(["next_cursor", "previous_cursor"] as const)(
  "rejects an empty sibling page with %s",
  async (key) => {
    const body = (await fixtureEvidenceSource.getReader(fixtureDocuments[0]!.id, {
      includeSiblings: false,
    }))!;
    body.sibling_page = {
      scope: "page",
      returned: 0,
      limit: 10,
      complete: false,
      next_cursor: null,
      previous_cursor: null,
      [key]: "continuation",
    };
    const source = new HttpEvidenceSource({
      baseUrl: "https://api.test",
      entityIds: [entity],
      token: "secret",
      fetchImpl: async () => new Response(JSON.stringify(body)),
    });
    await expect(
      source.getReader(fixtureDocuments[0]!.id, { siblingLimit: 10 }),
    ).rejects.toBeInstanceOf(EvidenceContractError);
  },
);

import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/data/server", () => ({ getEvidenceSource: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import DocumentListPage from "./page";
import { PageNavigation } from "../components/PageNavigation";
import { getEvidenceSource } from "../lib/data/server";
import { EvidenceApiError, HttpEvidenceSource } from "../lib/data/http-source";
import { FixtureEvidenceSource } from "../lib/data/fixture-source";
import { fixtureDocuments } from "../lib/fixtures/synthetic-filing";

const document = fixtureDocuments[0]!;

function links(markup: string) {
  return [...markup.matchAll(/href="([^"]+)"[^>]*>([^<]+)<\/a>/g)].map((match) => ({
    url: new URL(match[1]!.replaceAll("&amp;", "&"), "https://app.test"),
    label: match[2],
  }));
}

describe("filing list pagination", () => {
  beforeEach(() => vi.resetAllMocks());

  it("renders exactly the requested HTTP page and keeps entity and order on navigation", async () => {
    const fetchImpl = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify([document]), {
          headers: {
            "X-FEL-Page-Limit": "50",
            "X-FEL-Next-Cursor": "next+/=",
            "X-FEL-Previous-Cursor": "previous+/=",
          },
        }),
    );
    vi.mocked(getEvidenceSource).mockReturnValue(
      new HttpEvidenceSource({
        baseUrl: "https://api.test",
        token: "test-token",
        entityIds: [document.entity_id],
        fetchImpl,
      }),
    );
    const html = renderToStaticMarkup(
      await DocumentListPage({
        searchParams: Promise.resolve({
          entity: document.entity_id,
          cursor: "current+/=",
          order: "desc",
        }),
      }),
    );
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const request = new URL(String(fetchImpl.mock.calls[0]![0]));
    expect(request.searchParams.get("cursor")).toBe("current+/=");
    expect(request.searchParams.get("order")).toBe("desc");
    expect(request.searchParams.get("limit")).toBe("50");
    expect(html).toContain("Showing 1 filings");
    expect(html).toContain("Amendment history is not fully loaded");
    expect(html).toContain(`/reader/${document.id}`);
    const next = links(html).find((link) => link.label === "Next page")!.url;
    expect(next.pathname).toBe("/");
    expect(next.searchParams.get("entity")).toBe(document.entity_id);
    expect(next.searchParams.get("cursor")).toBe("next+/=");
    expect(next.searchParams.get("order")).toBe("desc");
    const oldest = links(html).find((link) => link.label === "Oldest first")!.url;
    expect(oldest.searchParams.has("cursor")).toBe(false);
  });

  it("renders an empty final page with disabled previous and next controls", async () => {
    const source = new FixtureEvidenceSource();
    vi.spyOn(source, "listDocuments").mockResolvedValue({
      items: [],
      nextCursor: null,
      previousCursor: null,
      limit: 50,
    });
    vi.mocked(getEvidenceSource).mockReturnValue(source);
    const html = renderToStaticMarkup(await DocumentListPage({}));
    expect(html).toContain("Showing 0 filings");
    expect(html.match(/aria-disabled="true"/g)).toHaveLength(2);
    expect(links(html).some((link) => link.label === "Next page")).toBe(false);
  });

  it("does not expose an unsafe source link and labels amendments without inventing history", async () => {
    const source = new FixtureEvidenceSource();
    vi.spyOn(source, "listDocuments").mockResolvedValue({
      items: [
        { ...document, form: "10-Q/A", source_url: "javascript:alert(1)" },
        { ...document, id: "other", form: undefined },
      ],
      nextCursor: null,
      previousCursor: null,
      limit: 50,
    });
    vi.mocked(getEvidenceSource).mockReturnValue(source);
    const html = renderToStaticMarkup(await DocumentListPage({}));
    expect(html).toContain("Amendment / restatement");
    expect(html).toContain(">Filing</a>");
    expect(html).not.toContain("javascript:");
  });

  it("renders typed failures but lets unexpected errors reach the route boundary", async () => {
    vi.mocked(getEvidenceSource).mockImplementationOnce(() => {
      throw new EvidenceApiError(401, "/documents", "authentication");
    });
    expect(renderToStaticMarkup(await DocumentListPage({}))).toContain("Sign in required");
    const error = new Error("unexpected failure");
    vi.mocked(getEvidenceSource).mockImplementationOnce(() => {
      throw error;
    });
    await expect(DocumentListPage({})).rejects.toBe(error);
  });
});

describe("PageNavigation scope preservation", () => {
  it("encodes opaque cursors on the app route and resets only the active cursor when changing order", () => {
    const html = renderToStaticMarkup(
      <PageNavigation
        path="/reader/target"
        params={{
          as_of: "2026-01-01T00:00:00Z",
          corpus_version_id: "",
          document_version_id: "version",
          span: "selected",
          sibling_cursor: "old",
        }}
        cursorKey="sibling_cursor"
        orderKey="sibling_order"
        order="desc"
        nextCursor="https://untrusted.test/?token=x"
        previousCursor="before+/="
        label="Related filing pages"
      />,
    );
    const next = links(html).find((link) => link.label === "Next page")!.url;
    expect(next.origin).toBe("https://app.test");
    expect(next.pathname).toBe("/reader/target");
    expect(next.searchParams.get("sibling_cursor")).toBe("https://untrusted.test/?token=x");
    expect(next.searchParams.get("document_version_id")).toBe("version");
    expect(next.searchParams.get("span")).toBe("selected");
    expect(next.searchParams.get("corpus_version_id")).toBe("");
    const newest = links(html).find((link) => link.label === "Newest first")!.url;
    expect(newest.searchParams.has("sibling_cursor")).toBe(false);
    expect(newest.searchParams.get("as_of")).toBe("2026-01-01T00:00:00Z");
    expect(newest.searchParams.get("sibling_order")).toBe("desc");
  });
});

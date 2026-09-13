import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PayloadFields, ExtractionPagination } from "./display";
import { initialFixture } from "../../lib/extraction/fixture";
describe("extraction read display", () => {
  it("renders candidate text verbatim and escapes markup without numerical conversion", () => {
    const markup = renderToStaticMarkup(
      <PayloadFields payload={initialFixture().proposals[2]!.payload} />,
    );
    expect(markup).toContain("9007199254740993");
    expect(markup).toContain("null");
    expect(markup).toContain("&lt;script&gt;");
    expect(markup).not.toContain("<script>");
    expect(markup).toContain("Read-only candidate fields");
  });
  it("keeps cursors opaque on known paths and offers no automatic all-page load", () => {
    const markup = renderToStaticMarkup(
      <ExtractionPagination
        path="/extractions"
        query={{ state: "needs_review" }}
        page={{ next_cursor: "opaque:a", previous_cursor: null, limit: 50 }}
      />,
    );
    expect(markup).toContain("cursor=opaque%3Aa");
    expect(markup).toContain("state=needs_review");
    expect(markup).toContain("Previous page</span>");
  });
});

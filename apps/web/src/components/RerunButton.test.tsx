import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { rerunAction } from "../lib/observatory/actions";
import { RerunButton } from "./RerunButton";

const QUERY_ID = "eeeeeeee-0000-4000-8000-000000000001";
const RUN_ID = "ffffffff-0000-4000-8000-000000000001";

describe("RerunButton rendering", () => {
  it("carries the parent query and run ids as hidden fields", () => {
    const markup = renderToStaticMarkup(<RerunButton queryId={QUERY_ID} runId={RUN_ID} />);
    expect(markup).toContain(`value="${QUERY_ID}"`);
    expect(markup).toContain(`value="${RUN_ID}"`);
    expect(markup).toContain('name="queryId"');
    expect(markup).toContain('name="runId"');
  });

  it("names itself as an unchanged, parent-linked rerun", () => {
    const markup = renderToStaticMarkup(<RerunButton queryId={QUERY_ID} runId={RUN_ID} />);
    expect(markup).toContain("Rerun (unchanged, parent-linked)");
  });

  it("is wired to the shared rerun server action", () => {
    const element = RerunButton({ queryId: QUERY_ID, runId: RUN_ID });
    expect(element.props.action).toBe(rerunAction);
  });
});

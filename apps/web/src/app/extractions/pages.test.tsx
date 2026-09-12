import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
vi.mock("../../components/extraction/SourceLinks", () => ({
  SourceLinks: () => <p>Source context tested separately</p>,
}));
import Queue from "./page";
import Proposal from "./[id]/page";
import Runs from "../extraction-runs/page";
import Run from "../extraction-runs/[runId]/page";
import Events from "../extraction-runs/[runId]/events/page";
import Approved from "../approved-extractions/[recordId]/page";
import Versions from "../approved-extractions/[recordId]/versions/page";
import Version from "../approved-extractions/[recordId]/versions/[versionId]/page";
import LoadingQueue from "./loading";
import LoadingRuns from "../extraction-runs/loading";
import LoadingApproved from "../approved-extractions/loading";
import { FIXTURE_RUN, FIXTURE_RECORD, fixtureId } from "../../lib/extraction/fixture";
const pages = [
  ["Extraction review", () => Queue({})],
  ["arr proposal", () => Proposal({ params: Promise.resolve({ id: fixtureId(3) }) })],
  ["Extraction runs", () => Runs({})],
  ["Execution steps in order", () => Run({ params: Promise.resolve({ runId: FIXTURE_RUN }) })],
  ["Stored extraction events", () => Events({ params: Promise.resolve({ runId: FIXTURE_RUN }) })],
  [
    "arr approved record",
    () => Approved({ params: Promise.resolve({ recordId: FIXTURE_RECORD }) }),
  ],
  [
    "Immutable approval history",
    () => Versions({ params: Promise.resolve({ recordId: FIXTURE_RECORD }) }),
  ],
  [
    "Immutable approved version",
    () =>
      Version({ params: Promise.resolve({ recordId: FIXTURE_RECORD, versionId: fixtureId(8) }) }),
  ],
] as const;
beforeEach(() => vi.stubEnv("FEL_EVIDENCE_SOURCE", "fixture"));
afterEach(() => vi.unstubAllEnvs());
describe("mounted extraction pages", () => {
  it.each([LoadingQueue, LoadingRuns, LoadingApproved])(
    "announces pending navigation",
    (Loading) => {
      const html = renderToStaticMarkup(<Loading />);
      expect(html).toContain('role="status"');
      expect(html).toContain('aria-busy="true"');
      expect(html).toContain("Loading extraction view");
    },
  );
  it.each(pages)("renders %s against real fixture source guards", async (title, load) => {
    const html = renderToStaticMarkup(await load());
    expect(html).toContain(title);
    expect(html).not.toContain("Extraction view unavailable");
    expect(html).toContain("Synthetic fixture mode");
  });
  it.each(pages)("fails %s honestly when configuration is absent", async (_title, load) => {
    vi.stubEnv("FEL_EVIDENCE_SOURCE", "");
    const html = renderToStaticMarkup(await load());
    expect(html).toContain("Extraction view unavailable");
    expect(html).not.toContain("synthetic-fixture-only");
  });
  it("ignores an unrelated query parameter instead of blanking the route", async () => {
    const html = renderToStaticMarkup(
      await Queue({ searchParams: Promise.resolve({ utm_source: "email" }) }),
    );
    expect(html).not.toContain("Extraction view unavailable");
    expect(html).toContain("Extraction review");
  });
  it("describes the queue it actually loaded", async () => {
    const unfiltered = renderToStaticMarkup(await Queue({}));
    expect(unfiltered).toContain('<option value="" selected="">All states</option>');
    const filtered = renderToStaticMarkup(
      await Queue({ searchParams: Promise.resolve({ state: "needs_review" }) }),
    );
    expect(filtered).toContain('<option selected="">needs_review</option>');
  });
  it("keeps empty queue and invalid cursor outcomes explicit", async () => {
    expect(
      renderToStaticMarkup(await Queue({ searchParams: Promise.resolve({ state: "accepted" }) })),
    ).toContain("No proposals on this page");
    expect(
      renderToStaticMarkup(
        await Queue({ searchParams: Promise.resolve({ cursor: "foreign:100" }) }),
      ),
    ).toContain("Extraction view unavailable");
  });
});

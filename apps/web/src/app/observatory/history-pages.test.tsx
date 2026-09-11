import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/observatory/server", () => ({ getObservatorySource: vi.fn() }));
vi.mock("../../lib/data/server", () => ({ getEvidenceSource: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import RunPage from "./runs/[runId]/page";
import HistoryPage from "./runs/[runId]/history/page";
import ComparePage from "./compare/page";
import { getObservatorySource } from "../../lib/observatory/server";
import { getEvidenceSource } from "../../lib/data/server";
import { MockObservatorySource } from "../../lib/observatory/mock-source";
import { FixtureEvidenceSource } from "../../lib/data/fixture-source";
import { EvidenceContractError } from "../../lib/data/http-source";
import { ObservatoryApiError, ObservatoryContractError } from "../../lib/observatory/errors";
import {
  MOCK_RUN_ID,
  MOCK_RERUN_ID,
  MOCK_QUERY_ID,
  MOCK_EVENTS,
} from "../../lib/observatory/fixtures/synthetic-trace";

let source: MockObservatorySource;
let evidence: FixtureEvidenceSource;
const params = () => Promise.resolve({ runId: MOCK_RUN_ID });

beforeEach(() => {
  vi.resetAllMocks();
  source = new MockObservatorySource();
  evidence = new FixtureEvidenceSource();
  vi.mocked(getObservatorySource).mockReturnValue(source);
  vi.mocked(getEvidenceSource).mockReturnValue(evidence);
});

describe("bounded stored run and event pages", () => {
  it("requests one explicit history page and resolves reader links only under the trace's immutable scope", async () => {
    const query = vi.spyOn(source, "getQuery");
    const resolve = vi.spyOn(evidence, "resolveDocumentVersions");
    const trace = await source.getRun(MOCK_RUN_ID);
    const html = renderToStaticMarkup(
      await RunPage({
        params: params(),
        searchParams: Promise.resolve({
          order: "desc",
          feedback: "recorded",
          error: "invalid_scope",
        }),
      }),
    );
    expect(query).toHaveBeenCalledExactlyOnceWith(MOCK_QUERY_ID, {
      limit: 50,
      cursor: undefined,
      order: "desc",
    });
    expect(resolve).toHaveBeenCalledWith(
      [...new Set(trace.candidates.map((candidate) => candidate.document_version_id))],
      { asOf: trace.plan.effective_as_of, corpusVersionId: trace.plan.corpus_version_id },
    );
    expect(html).toContain('aria-label="Run history pages"');
    expect(html).toContain("Feedback recorded.");
    expect(html).toContain("Action failed: invalid_scope");
    expect(html).toContain(`/observatory/compare?a=${MOCK_RUN_ID}&amp;b=${MOCK_RERUN_ID}`);
    expect(html).toContain(`/observatory/runs/${MOCK_RUN_ID}/history`);
  });

  it("forwards opaque run cursors and does not offer comparison when this page has only the selected run", async () => {
    const page = await source.getQuery(MOCK_QUERY_ID);
    const selected = page.runs.find((run) => run.run_id === MOCK_RUN_ID)!;
    vi.spyOn(source, "getQuery").mockResolvedValue({
      ...page,
      runs: [selected],
      runPage: {
        items: [selected],
        limit: 50,
        nextCursor: "next+/=",
        previousCursor: "previous+/=",
      },
    });
    const html = renderToStaticMarkup(
      await RunPage({
        params: params(),
        searchParams: Promise.resolve({
          cursor: "current",
          order: "desc",
          error: "<script>secret</script>",
        }),
      }),
    );
    expect(source.getQuery).toHaveBeenCalledWith(MOCK_QUERY_ID, {
      limit: 50,
      cursor: "current",
      order: "desc",
    });
    expect(html).toContain("cursor=next%2B%2F%3D");
    expect(html).toContain("cursor=previous%2B%2F%3D");
    expect(html).not.toContain("Compare with run");
    expect(html).not.toContain("secret");
  });

  it("retains event history as the recovery route when a complete trace exceeds its limit", async () => {
    vi.spyOn(source, "getRun").mockRejectedValue(new ObservatoryApiError(413, "/run", "too_large"));
    const query = vi.spyOn(source, "getQuery");
    const html = renderToStaticMarkup(await RunPage({ params: params() }));
    expect(html).toContain("Evidence exceeds the read limit");
    expect(html).toContain(`/observatory/runs/${MOCK_RUN_ID}/history`);
    expect(html).not.toContain("Stored replay");
    expect(query).not.toHaveBeenCalled();
  });

  it("fails closed on query-history integrity errors and propagates unexpected trace errors", async () => {
    vi.spyOn(source, "getQuery").mockRejectedValue(
      new ObservatoryContractError("private malformed page"),
    );
    const html = renderToStaticMarkup(await RunPage({ params: params() }));
    expect(html).toContain("Evidence response rejected");
    expect(html).not.toContain("private malformed page");
    const error = new Error("unexpected trace failure");
    vi.spyOn(source, "getRun").mockRejectedValue(error);
    await expect(RunPage({ params: params() })).rejects.toBe(error);
  });

  it("keeps a readable trace when reader lookup is unavailable, but rejects invalid mappings", async () => {
    vi.spyOn(evidence, "resolveDocumentVersions").mockRejectedValueOnce(new Error("offline"));
    expect(renderToStaticMarkup(await RunPage({ params: params() }))).toContain("Retrieval run");
    vi.mocked(evidence.resolveDocumentVersions).mockRejectedValueOnce(
      new EvidenceContractError("wrong version"),
    );
    expect(renderToStaticMarkup(await RunPage({ params: params() }))).toContain(
      "Evidence response rejected",
    );
  });

  it("renders event history independently of a complete trace with forward/backward navigation", async () => {
    const history = vi.spyOn(source, "getEventHistory").mockResolvedValue({
      run_id: MOCK_RUN_ID,
      items: [MOCK_EVENTS[0]!],
      next_cursor: "after",
      previous_cursor: "before",
    });
    const trace = vi.spyOn(source, "getRun");
    const html = renderToStaticMarkup(
      await HistoryPage({
        params: params(),
        searchParams: Promise.resolve({ cursor: "resume", order: "desc" }),
      }),
    );
    expect(history).toHaveBeenCalledExactlyOnceWith(MOCK_RUN_ID, {
      limit: 50,
      cursor: "resume",
      order: "desc",
    });
    expect(trace).not.toHaveBeenCalled();
    expect(html).toContain(MOCK_EVENTS[0]!.type);
    expect(html).toContain("cursor=after");
    expect(html).toContain("cursor=before");
    expect(html).toContain("order=desc");
  });

  it("handles an empty event page without hiding the link back to the run", async () => {
    vi.spyOn(source, "getEventHistory").mockResolvedValue({
      run_id: MOCK_RUN_ID,
      items: [],
      next_cursor: null,
      previous_cursor: null,
    });
    const html = renderToStaticMarkup(await HistoryPage({ params: params() }));
    expect(html).toContain("Back to retrieval run");
    expect(html.match(/aria-disabled="true"/g)).toHaveLength(2);
    expect(html).not.toContain("<li");
  });

  it("renders safe event-page failures and rethrows unexpected ones", async () => {
    vi.spyOn(source, "getEventHistory").mockRejectedValueOnce(
      new ObservatoryApiError(422, "/events", "invalid_scope"),
    );
    expect(renderToStaticMarkup(await HistoryPage({ params: params() }))).toContain(
      "Invalid evidence scope",
    );
    const error = new Error("unexpected history failure");
    vi.mocked(source.getEventHistory).mockRejectedValueOnce(error);
    await expect(HistoryPage({ params: params() })).rejects.toBe(error);
  });
});

describe("stored run comparisons", () => {
  it("does not fetch runs until both identifiers exist", async () => {
    const getRun = vi.spyOn(source, "getRun");
    expect(renderToStaticMarkup(await ComparePage({}))).toContain("Provide two run ids");
    expect(
      renderToStaticMarkup(
        await ComparePage({ searchParams: Promise.resolve({ a: MOCK_RUN_ID }) }),
      ),
    ).toContain("Provide two run ids");
    expect(getRun).not.toHaveBeenCalled();
  });

  it("loads the exact two chosen traces and links back to the first", async () => {
    const getRun = vi.spyOn(source, "getRun");
    const html = renderToStaticMarkup(
      await ComparePage({ searchParams: Promise.resolve({ a: MOCK_RUN_ID, b: MOCK_RERUN_ID }) }),
    );
    expect(getRun.mock.calls).toEqual([[MOCK_RUN_ID], [MOCK_RERUN_ID]]);
    expect(html).toContain(`/observatory/runs/${MOCK_RUN_ID}`);
    expect(html).toContain("Run comparison");
  });

  it("shows bounded-read failures instead of a partial comparison and propagates unknown failures", async () => {
    vi.spyOn(source, "getRun").mockRejectedValueOnce(
      new ObservatoryApiError(413, "/run", "too_large"),
    );
    expect(
      renderToStaticMarkup(
        await ComparePage({ searchParams: Promise.resolve({ a: MOCK_RUN_ID, b: MOCK_RERUN_ID }) }),
      ),
    ).toContain("Evidence exceeds the read limit");
    const error = new Error("unexpected comparison failure");
    vi.mocked(source.getRun).mockRejectedValue(error);
    await expect(
      ComparePage({ searchParams: Promise.resolve({ a: MOCK_RUN_ID, b: MOCK_RERUN_ID }) }),
    ).rejects.toBe(error);
  });
});

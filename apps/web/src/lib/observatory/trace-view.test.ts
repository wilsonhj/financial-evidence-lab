import { describe, expect, it } from "vitest";

import type { Candidate, RetrievalTrace } from "./query-source";
import {
  claimViews,
  decisionTimeline,
  isRenderableAsSupported,
  laneColumns,
  partitionCandidates,
  readerHref,
} from "./trace-view";
import { MOCK_TRACE } from "./fixtures/synthetic-trace";

const trace = MOCK_TRACE;

function candidate(overrides: Partial<Candidate>): Candidate {
  return {
    item_id: "10101010-0000-4000-8000-0000000000ff",
    kind: "passage",
    contributions: [
      {
        lane: "dense",
        variant_index: 0,
        lane_rank: 1,
        raw_score: "0.5",
        rrf_contribution: "0.01",
        timing_ms: 1,
      },
    ],
    fused_score: "0.01",
    accepted: true,
    source_span_id: "cccccccc-0000-4000-8000-000000000001",
    document_version_id: "aaaaaaaa-0000-4000-8000-000000001001",
    published_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("isRenderableAsSupported", () => {
  it("requires the server to accept the candidate and its publish date within the cutoff", () => {
    expect(isRenderableAsSupported(candidate({}), trace.plan)).toBe(true);
    expect(isRenderableAsSupported(candidate({ accepted: false }), trace.plan)).toBe(false);
    // Accepted but published after the effective cutoff: never supported.
    expect(
      isRenderableAsSupported(candidate({ published_at: "2026-12-31T00:00:00Z" }), trace.plan),
    ).toBe(false);
  });
});

describe("partitionCandidates", () => {
  it("reclassifies an accepted-but-future candidate as rejected, never supported", () => {
    const future = candidate({
      item_id: "10101010-0000-4000-8000-0000000000aa",
      published_at: "2026-12-31T00:00:00Z",
    });
    const local: RetrievalTrace = { ...trace, candidates: [candidate({}), future] };
    const { supported, rejected } = partitionCandidates(local);
    expect(supported.map((c) => c.item_id)).not.toContain(future.item_id);
    expect(rejected.find((r) => r.candidate.item_id === future.item_id)?.code).toBe(
      "temporal_after_cutoff",
    );
  });

  it("keeps server rejection codes and never surfaces future/cross-version as supported", () => {
    const { supported, rejected } = partitionCandidates(trace);
    const supportedIds = supported.map((c) => c.item_id);
    // The committed future and cross-version fixtures are rejected, not supported.
    expect(supportedIds).not.toContain("10101010-0000-4000-8000-000000000005"); // future
    expect(supportedIds).not.toContain("10101010-0000-4000-8000-000000000006"); // cross-version
    expect(rejected.map((r) => r.code)).toContain("cross_version");
    expect(rejected.map((r) => r.code)).toContain("dedupe_near_duplicate");
    // Every supported candidate passes the guard.
    expect(supported.every((c) => isRenderableAsSupported(c, trace.plan))).toBe(true);
  });
});

describe("claimViews", () => {
  it("downgrades a supported claim that cites a non-supported item to unverifiable", () => {
    const local: RetrievalTrace = {
      ...trace,
      candidates: [candidate({ item_id: "10101010-0000-4000-8000-000000000001" })],
      claims: [
        {
          id: "20202020-0000-4000-8000-0000000000a1",
          text: "cites a rejected item",
          status: "supported",
          citations: [
            {
              item_id: "10101010-0000-4000-8000-deadbeef0000",
              source_span_id: "cccccccc-0000-4000-8000-000000000001",
              status: "entailed",
              numeric_checks: {},
            },
          ],
        },
      ],
    };
    expect(claimViews(local)[0]!.displayStatus).toBe("unverifiable");
    expect(claimViews(local)[0]!.downgraded).toBe(true);
  });

  it("downgrades a supported claim whose citation matches the item but not the span", () => {
    const accepted = candidate({ item_id: "10101010-0000-4000-8000-000000000001" });
    const local: RetrievalTrace = {
      ...trace,
      candidates: [accepted],
      claims: [
        {
          id: "20202020-0000-4000-8000-0000000000b1",
          text: "right item, wrong span",
          status: "supported",
          citations: [
            {
              item_id: accepted.item_id,
              // Correct item, but a different span than the accepted candidate's.
              source_span_id: "cccccccc-0000-4000-8000-0000000000ff",
              status: "entailed",
              numeric_checks: {},
            },
          ],
        },
      ],
    };
    expect(claimViews(local)[0]!.displayStatus).toBe("unverifiable");
    expect(claimViews(local)[0]!.downgraded).toBe(true);
  });

  it("passes a supported claim through when its citations are all supported", () => {
    const views = claimViews(trace);
    const supported = views.find((v) => v.claim.status === "supported");
    expect(supported?.displayStatus).toBe("supported");
    expect(supported?.downgraded).toBe(false);
  });
});

describe("laneColumns", () => {
  it("orders each lane by lane_rank and marks supported rows via the guard", () => {
    const columns = laneColumns(trace);
    const dense = columns.dense;
    expect(dense.map((row) => row.contribution.lane_rank)).toEqual(
      [...dense.map((row) => row.contribution.lane_rank)].sort((a, b) => a - b),
    );
    const futureRow = dense.find(
      (row) => row.candidate.item_id === "10101010-0000-4000-8000-000000000005",
    );
    expect(futureRow?.supported).toBe(false);
  });
});

describe("decisionTimeline", () => {
  it("returns decisions ordered by occurrence", () => {
    const stamps = decisionTimeline(trace).map((entry) => Date.parse(entry.occurredAt));
    expect(stamps).toEqual([...stamps].sort((a, b) => a - b));
  });
});

describe("readerHref", () => {
  it("builds a span deep link when the version resolves and null otherwise", () => {
    const map = { "aaaaaaaa-0000-4000-8000-000000001001": "aaaaaaaa-0000-4000-8000-000000000001" };
    const href = readerHref(candidate({}), map);
    expect(href).toBe(
      "/reader/aaaaaaaa-0000-4000-8000-000000000001?span=cccccccc-0000-4000-8000-000000000001",
    );
    expect(readerHref(candidate({ document_version_id: "unknown" }), map)).toBeNull();
  });

  it("deep-links to the citation's span when overridden, not the candidate's", () => {
    const map = { "aaaaaaaa-0000-4000-8000-000000001001": "aaaaaaaa-0000-4000-8000-000000000001" };
    const citationSpan = "cccccccc-0000-4000-8000-0000000000ff";
    const href = readerHref(candidate({}), map, citationSpan);
    expect(href).toBe(
      "/reader/aaaaaaaa-0000-4000-8000-000000000001?span=cccccccc-0000-4000-8000-0000000000ff",
    );
    // Never the candidate's own (different) span.
    expect(href).not.toContain("cccccccc-0000-4000-8000-000000000001");
  });
});

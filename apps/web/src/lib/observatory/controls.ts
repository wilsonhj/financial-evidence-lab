import type { CreateQuery } from "./query-source";
import { LANES, type Lane } from "./trace-view";

// Contract bounds (openapi CreateQuery). Controls must never let the user leave
// these ranges: out-of-bounds input is rejected before a request is made.
export const QUESTION_MAX = 4000;
export const TOP_K_MIN = 1;
export const TOP_K_MAX = 100;
export const FILTER_MAX_ITEMS = 20;
export const LANE_MAX_ITEMS = LANES.length; // 4

export interface ControlsInput {
  question: string;
  lanes: string[];
  topK?: string;
  asOf?: string;
  forms?: string;
  periods?: string;
}

export interface ControlsResult {
  errors: string[];
  query?: CreateQuery;
}

function splitList(raw: string | undefined): string[] {
  return (raw ?? "")
    .split(/[,\n]/)
    .map((value) => value.trim())
    .filter(Boolean);
}

/**
 * Validates and normalises raw control input against the frozen contract
 * bounds, producing a CreateQuery only when every field is in range. Lanes
 * outside the enum, a top_k off the 1..100 range, an unparseable cutoff, or
 * too many form/period filters are rejected rather than silently clamped.
 */
export function validateControls(input: ControlsInput): ControlsResult {
  const errors: string[] = [];

  const question = input.question.trim();
  if (question.length < 1) errors.push("Question is required.");
  if (question.length > QUESTION_MAX)
    errors.push(`Question must be ${QUESTION_MAX} characters or fewer.`);

  const lanes = input.lanes.filter((lane): lane is Lane =>
    (LANES as readonly string[]).includes(lane),
  );
  if (lanes.length !== input.lanes.length) errors.push("Unknown retrieval lane selected.");
  if (new Set(lanes).size !== lanes.length) errors.push("Lanes must be unique.");
  if (lanes.length > LANE_MAX_ITEMS) errors.push(`Select at most ${LANE_MAX_ITEMS} lanes.`);

  let topK: number | undefined;
  if (input.topK !== undefined && input.topK.trim() !== "") {
    topK = Number(input.topK);
    if (!Number.isInteger(topK) || topK < TOP_K_MIN || topK > TOP_K_MAX) {
      errors.push(`Top-k must be an integer between ${TOP_K_MIN} and ${TOP_K_MAX}.`);
      topK = undefined;
    }
  }

  let asOf: string | undefined;
  if (input.asOf !== undefined && input.asOf.trim() !== "") {
    asOf = input.asOf.trim();
    if (Number.isNaN(Date.parse(asOf))) {
      errors.push("Cutoff must be a valid date-time.");
      asOf = undefined;
    }
  }

  const forms = splitList(input.forms);
  if (forms.length > FILTER_MAX_ITEMS) errors.push(`At most ${FILTER_MAX_ITEMS} form filters.`);
  const periods = splitList(input.periods);
  if (periods.length > FILTER_MAX_ITEMS) errors.push(`At most ${FILTER_MAX_ITEMS} period filters.`);

  if (errors.length > 0) return { errors };

  const query: CreateQuery = {
    question,
    ...(lanes.length > 0 ? { lanes } : {}),
    ...(topK !== undefined ? { top_k: topK } : {}),
    ...(asOf ? { as_of: asOf } : {}),
    ...(forms.length > 0 ? { forms } : {}),
    ...(periods.length > 0 ? { periods } : {}),
  };
  return { errors: [], query };
}

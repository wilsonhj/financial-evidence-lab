export type DeskTheme = "system" | "light" | "oled";
export type EvidenceSourceId = "sec-10q-nrr" | "call-turn-48";
export type GuidanceApprovalId = "C-109-revenue" | "C-109-gross-margin";

export interface ReviewDecision {
  conflictId: "C-104";
  sourceId: EvidenceSourceId;
  rationale: string;
}

export interface GuidanceApproval {
  claimId: GuidanceApprovalId;
  approved: boolean;
}

export interface AppliedFacts {
  modelVersion: "v19";
  decision: ReviewDecision;
  approvalIds: GuidanceApprovalId[];
}

const requiredGuidanceApprovalIds: GuidanceApprovalId[] = ["C-109-revenue", "C-109-gross-margin"];

export function isValidDeskTheme(value: string | null): value is DeskTheme {
  return value === "system" || value === "light" || value === "oled";
}

export function resolveDeskTheme(value: string | null): DeskTheme {
  return isValidDeskTheme(value) ? value : "system";
}

type ThemeStorage = {
  setItem(key: string, value: string): void;
};

function defaultThemeStorage(): ThemeStorage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function writeStoredTheme(
  theme: DeskTheme,
  storage: ThemeStorage | null = defaultThemeStorage(),
): void {
  if (storage === null) return;
  try {
    storage.setItem("fel-theme", theme);
  } catch {
    // Storage can throw when blocked (private mode, iframe). Cookie + dataset remain.
  }
}

export function canSaveResolution(sourceId: EvidenceSourceId | null, rationale: string): boolean {
  return sourceId !== null && rationale.trim().length >= 24;
}

export function buildReviewDecision(
  sourceId: EvidenceSourceId | null,
  rationale: string,
): ReviewDecision | null {
  if (sourceId === null || !canSaveResolution(sourceId, rationale)) return null;
  return {
    conflictId: "C-104",
    sourceId,
    rationale: rationale.trim(),
  };
}

export function canApplyApprovedFacts(
  decision: ReviewDecision | null,
  approvals: GuidanceApproval[],
): boolean {
  const approvalIds = approvals.map((approval) => approval.claimId);
  return (
    decision !== null &&
    approvals.length === requiredGuidanceApprovalIds.length &&
    new Set(approvalIds).size === requiredGuidanceApprovalIds.length &&
    approvals.every((approval) => approval.approved) &&
    requiredGuidanceApprovalIds.every((claimId) => approvalIds.includes(claimId))
  );
}

export function buildAppliedFacts(
  decision: ReviewDecision | null,
  approvals: GuidanceApproval[],
): AppliedFacts | null {
  if (!canApplyApprovedFacts(decision, approvals) || decision === null) return null;
  return {
    modelVersion: "v19",
    decision,
    approvalIds: [...requiredGuidanceApprovalIds],
  };
}

export function resolveVisibleClaimId<ClaimId extends string>(
  currentClaimId: ClaimId | null,
  visibleClaimIds: ClaimId[],
): ClaimId | null {
  if (currentClaimId && visibleClaimIds.includes(currentClaimId)) return currentClaimId;
  return visibleClaimIds[0] ?? null;
}

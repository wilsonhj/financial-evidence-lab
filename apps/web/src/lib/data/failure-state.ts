import type { EvidenceFailureStateKind } from "../../components/EvidenceFailureState";
import { EvidenceApiError, EvidenceContractError } from "./http-source";
import { EvidenceConfigurationError } from "./runtime-config";

export function evidenceFailureState(error: unknown): EvidenceFailureStateKind | null {
  if (error instanceof EvidenceApiError) return error.kind;
  if (error instanceof EvidenceContractError) return "integrity";
  if (error instanceof EvidenceConfigurationError) return "configuration";
  return null;
}

import { DeploymentGuardError } from "../../../../../../lib/deployment-mode";
import { getExtractionSource } from "../../../../../../lib/extraction/source";
import { failure } from "../../../../../../lib/extraction/transport";
export const dynamic = "force-dynamic";
export async function GET(request: Request, context: { params: Promise<{ runId: string }> }) {
  try {
    return await getExtractionSource().request(
      `runs/${(await context.params).runId}/events`,
      request,
    );
  } catch (error) {
    return failure(
      503,
      error instanceof DeploymentGuardError ? "PUBLIC_AUTH_NOT_READY" : "EXTRACTION_UNAVAILABLE",
    );
  }
}

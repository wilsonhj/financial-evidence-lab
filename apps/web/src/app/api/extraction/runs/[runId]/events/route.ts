import { getExtractionSource } from "../../../../../../lib/extraction/source";
import { failure } from "../../../../../../lib/extraction/transport";
export const dynamic = "force-dynamic";
export async function GET(request: Request, context: { params: Promise<{ runId: string }> }) {
  try {
    return await getExtractionSource().request(
      `runs/${(await context.params).runId}/events`,
      request,
    );
  } catch {
    return failure(503, "EXTRACTION_UNAVAILABLE");
  }
}

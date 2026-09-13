import { getExtractionSource } from "../../../../lib/extraction/source";
import { failure } from "../../../../lib/extraction/transport";
export const dynamic = "force-dynamic";
export async function GET(request: Request, context: { params: Promise<{ path: string[] }> }) {
  try {
    return await getExtractionSource().request((await context.params).path.join("/"), request);
  } catch {
    return failure(503, "EXTRACTION_UNAVAILABLE");
  }
}
export const POST = GET;
export const DELETE = GET;

import { validateTelemetryBatch } from "../../../lib/telemetry-validation";

/**
 * Dedicated web-layer client telemetry ingest (issue #138). POST only.
 * Gated by `FEL_WEB_TELEMETRY=1`: the feature does not exist at all (404)
 * unless explicitly enabled, mirroring the fail-closed posture of the rest
 * of the app's runtime configuration. The raw request body is never echoed
 * back, on either the success or the failure path.
 */

function enabled(): boolean {
  return process.env.FEL_WEB_TELEMETRY === "1";
}

export async function POST(request: Request): Promise<Response> {
  if (!enabled()) {
    return new Response(null, { status: 404 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return new Response(null, { status: 400 });
  }

  const events = validateTelemetryBatch(body);
  if (events === null) {
    return new Response(null, { status: 400 });
  }

  for (const event of events) {
    console.log(
      JSON.stringify({
        level: "info",
        event: "web.telemetry",
        name: event.name,
        ms: event.ms ?? null,
        attrs: event.attrs ?? null,
      }),
    );
  }

  return new Response(null, { status: 204 });
}

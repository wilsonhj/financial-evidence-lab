import { NextResponse, type NextRequest } from "next/server";
import { assertDeploymentMode } from "./lib/deployment-mode";

export function proxy(request: NextRequest): Response {
  try {
    assertDeploymentMode();
    return NextResponse.next();
  } catch {
    const headers = { "cache-control": "no-store" };
    if (request.nextUrl.pathname.startsWith("/api/")) {
      return Response.json(
        {
          error: {
            code: "PUBLIC_AUTH_NOT_READY",
            message: "Service unavailable",
            request_id: "web-deployment",
          },
        },
        { status: 503, headers },
      );
    }
    return new Response("Service unavailable", { status: 503, headers });
  }
}
export const config = {
  matcher: [
    "/",
    "/desk/:path*",
    "/reader/:path*",
    "/observatory/:path*",
    "/extractions/:path*",
    "/extraction-runs/:path*",
    "/approved-extractions/:path*",
    "/api/extraction/:path*",
  ],
};

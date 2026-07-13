import { health } from "@/lib/health";

/** Mirrors the API /health contract so platform probes can be wired later. */
export function GET(): Response {
  return Response.json(health("fel-web"));
}

export interface HealthStatus {
  status: "ok";
  service: string;
}

/**
 * Framework-free health descriptor mirroring the API `/health` contract.
 * The Next.js App Router runtime and its dependencies are introduced by
 * M0-LOCAL (T0002); the scaffold keeps the web package framework-agnostic.
 */
export function health(service: string): HealthStatus {
  return { status: "ok", service };
}

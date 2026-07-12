export interface HealthStatus {
  status: "ok";
  service: string;
  version: string;
}

/**
 * Framework-free health descriptor mirroring the API `/health` contract
 * (status, service, version). The Next.js App Router runtime and its
 * dependencies are introduced by T0002; the scaffold keeps the web package
 * framework-agnostic.
 */
export function health(service: string, version = "0.0.0"): HealthStatus {
  return { status: "ok", service, version };
}

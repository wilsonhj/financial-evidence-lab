import { env as serverEnvironment } from "node:process";
import { closeSync, openSync, readSync } from "node:fs";

export type DeploymentEnvironment = Readonly<Record<string, string | undefined>>;
export class EvidenceConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EvidenceConfigurationError";
  }
}
export class DeploymentGuardError extends EvidenceConfigurationError {
  constructor() {
    super("PUBLIC_AUTH_NOT_READY");
    this.name = "DeploymentGuardError";
  }
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const TARGET = /^[a-zA-Z0-9][a-zA-Z0-9_-]{2,79}$/;
const FIELDS = [
  "org",
  "user",
  "workspace",
  "entity",
  "policy",
  "document",
  "version",
  "section",
  "span",
  "corpus",
];
function refuse(): never {
  throw new DeploymentGuardError();
}
function mockClaims(token: string | undefined): Record<string, unknown> {
  if (!token || token.length > 8192 || !/^mock\.[A-Za-z0-9_-]+$/.test(token)) refuse();
  const bytes = Buffer.from(token.slice(5), "base64url");
  if (bytes.toString("base64url") !== token.slice(5)) refuse();
  const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  if (!value || typeof value !== "object" || Array.isArray(value)) refuse();
  const claims = value as Record<string, unknown>;
  if (
    typeof claims.org_id !== "string" ||
    !UUID.test(claims.org_id) ||
    typeof claims.sub !== "string" ||
    !UUID.test(claims.sub) ||
    !["owner", "editor", "reviewer", "viewer"].includes(String(claims.role))
  )
    refuse();
  return claims;
}
function upstream(env: DeploymentEnvironment): URL {
  if (env.FEL_EVIDENCE_SOURCE !== "http" || env.FEL_AUTH_MODE !== "mock" || !env.FEL_API_BASE_URL)
    refuse();
  const url = new URL(env.FEL_API_BASE_URL);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  )
    refuse();
  return url;
}
function manifest(path: string | undefined): Record<string, string> {
  if (!path) refuse();
  const fd = openSync(path, "r");
  let size = 0;
  const bytes = Buffer.alloc(16385);
  try {
    while (size < bytes.length) {
      const count = readSync(fd, bytes, size, bytes.length - size, null);
      if (!count) break;
      size += count;
    }
  } finally {
    closeSync(fd);
  }
  if (size > 16384) refuse();
  const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(0, size));
  const value: unknown = JSON.parse(text);
  if (!value || typeof value !== "object" || Array.isArray(value)) refuse();
  const data = value as Record<string, string>;
  const keys = [...FIELDS, "schema_version", "target"].sort();
  if (
    JSON.stringify(Object.keys(data).sort()) !== JSON.stringify(keys) ||
    FIELDS.some((key) => typeof data[key] !== "string" || !UUID.test(data[key]!)) ||
    data.schema_version !== "extraction-cross-stack/v1" ||
    typeof data.target !== "string"
  )
    refuse();
  if (JSON.stringify(Object.fromEntries(keys.map((key) => [key, data[key]]))) !== text) refuse();
  return data;
}
/** Operator-selected mode only. No headers, URL parameters or hostname select trust. */
export function assertDeploymentMode(
  env: DeploymentEnvironment = serverEnvironment,
): "fixture" | "reader-smoke" | "synthetic-http" {
  try {
    const mode = env.FEL_DEPLOYMENT_MODE;
    if (mode === "fixture") {
      if (env.FEL_EVIDENCE_SOURCE !== "fixture" || env.FEL_API_BEARER_TOKEN) refuse();
      return mode;
    }
    if (mode === "reader-smoke") {
      upstream(env);
      if (!TARGET.test(env.FEL_READER_SMOKE_TARGET ?? "")) refuse();
      if (env.FEL_API_BEARER_TOKEN !== "invalid") mockClaims(env.FEL_API_BEARER_TOKEN);
      return mode;
    }
    if (mode === "synthetic-http") {
      const url = upstream(env);
      if (
        !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) ||
        env.FEL_ALLOW_MOCK_LLM !== "1" ||
        !TARGET.test(env.FEL_SYNTHETIC_HTTP_TARGET ?? "")
      )
        refuse();
      const data = manifest(env.CROSS_STACK_MANIFEST);
      const claims = mockClaims(env.FEL_API_BEARER_TOKEN);
      if (
        data.target !== env.FEL_SYNTHETIC_HTTP_TARGET ||
        env.FEL_WORKSPACE_ID !== data.workspace ||
        env.FEL_ENTITY_IDS !== data.entity ||
        claims.org_id !== data.org ||
        claims.sub !== data.user ||
        claims.role !== "owner"
      )
        refuse();
      return mode;
    }
  } catch {
    /* Discard all parser/filesystem diagnostics and their sensitive inputs. */
  }
  return refuse();
}

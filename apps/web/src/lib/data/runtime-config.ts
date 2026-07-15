export type EvidenceRuntimeConfig =
  | { mode: "fixture" }
  | {
      mode: "http";
      baseUrl: string;
      token: string;
      entityIds: string[];
      asOf?: string;
      corpusVersionId?: string;
    };

export class EvidenceConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EvidenceConfigurationError";
  }
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const OFFSET_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

function required(env: Readonly<Record<string, string | undefined>>, name: string): string {
  const value = env[name]?.trim();
  if (!value) throw new EvidenceConfigurationError(`HTTP evidence mode requires ${name}`);
  return value;
}

/** Parses only server runtime variables. Never import this module from a client component. */
export function loadEvidenceRuntimeConfig(
  env: Readonly<Record<string, string | undefined>> = process.env,
): EvidenceRuntimeConfig {
  const mode = env.FEL_EVIDENCE_SOURCE?.trim();
  if (mode === "fixture") return { mode };
  if (mode !== "http") {
    throw new EvidenceConfigurationError(
      "FEL_EVIDENCE_SOURCE must be explicitly set to fixture or http",
    );
  }

  const rawBaseUrl = required(env, "FEL_API_BASE_URL");
  let url: URL;
  try {
    url = new URL(rawBaseUrl);
  } catch {
    throw new EvidenceConfigurationError("FEL_API_BASE_URL must be an absolute HTTP(S) URL");
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new EvidenceConfigurationError(
      "FEL_API_BASE_URL must be an HTTP(S) URL without credentials, query, or fragment",
    );
  }
  const loopback = ["localhost", "127.0.0.1", "::1"].includes(url.hostname);
  if (env.NODE_ENV === "production" && url.protocol !== "https:" && !loopback) {
    throw new EvidenceConfigurationError(
      "FEL_API_BASE_URL must use HTTPS outside local development",
    );
  }

  const entityIds = required(env, "FEL_ENTITY_IDS")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  if (entityIds.length === 0 || entityIds.some((value) => !UUID.test(value))) {
    throw new EvidenceConfigurationError("FEL_ENTITY_IDS must be a comma-separated UUID list");
  }

  const asOf = env.FEL_AS_OF?.trim() || undefined;
  if (asOf && (!OFFSET_TIMESTAMP.test(asOf) || Number.isNaN(Date.parse(asOf)))) {
    throw new EvidenceConfigurationError(
      "FEL_AS_OF must be an RFC 3339 timestamp with an explicit UTC offset",
    );
  }

  const corpusVersionId = env.FEL_CORPUS_VERSION_ID?.trim() || undefined;
  if (corpusVersionId && !UUID.test(corpusVersionId)) {
    throw new EvidenceConfigurationError("FEL_CORPUS_VERSION_ID must be a UUID");
  }

  return {
    mode,
    baseUrl: url.toString().replace(/\/$/, ""),
    token: required(env, "FEL_API_BEARER_TOKEN"),
    entityIds: [...new Set(entityIds)],
    ...(asOf ? { asOf } : {}),
    ...(corpusVersionId ? { corpusVersionId } : {}),
  };
}

import "node:process";
import { loadObservatoryRuntimeConfig } from "../observatory/runtime-config";
import { guards, etag, uuid } from "./contracts";
import { resolveRoute, queryFor, matchesResource } from "./routes";

export type Config =
  { mode: "fixture" } | { mode: "http"; baseUrl: string; token: string; workspaceId: string };
export function loadConfig(env?: Readonly<Record<string, string | undefined>>): Config {
  const config = loadObservatoryRuntimeConfig(env);
  return config.mode === "mock" ? { mode: "fixture" } : config;
}
export function failure(status: number, code: string): Response {
  return Response.json(
    {
      error: {
        code,
        message: "Extraction request could not be completed",
        request_id: "web-extraction",
      },
    },
    { status, headers: { "cache-control": "no-store" } },
  );
}
class BodyTooLarge extends Error {}
export async function boundedText(
  body: ReadableStream<Uint8Array> | null,
  limit: number,
): Promise<string> {
  if (!body) return "";
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0,
    result = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) return result + decoder.decode();
      size += value.byteLength;
      if (size > limit) throw new BodyTooLarge("Body exceeds limit");
      result += decoder.decode(value, { stream: true });
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
/** No browser authorization, cookies or arbitrary locations enter the upstream request. */
export async function requestExtraction(
  config: Extract<Config, { mode: "http" }>,
  path: string,
  request: Request,
  fetcher: typeof fetch = fetch,
): Promise<Response> {
  const route = resolveRoute(path, request.method, config.workspaceId);
  if (!route) return failure(422, "VALIDATION_ERROR");
  let query: string;
  try {
    query = queryFor(route, new URL(request.url).searchParams);
  } catch {
    return failure(422, "VALIDATION_ERROR");
  }
  const headers = new Headers({
    authorization: `Bearer ${config.token}`,
    accept: route.stream ? "text/event-stream" : "application/json",
  });
  let body: string | undefined;
  if (request.method !== "GET") {
    if (
      request.headers.get("origin") !==
        `${new URL(request.url).protocol}//${request.headers.get("host") ?? new URL(request.url).host}` ||
      (request.headers.has("sec-fetch-site") &&
        request.headers.get("sec-fetch-site") !== "same-origin")
    )
      return failure(403, "FORBIDDEN");
    const key = request.headers.get("idempotency-key");
    if (!key || key.length > 200 || !/^[A-Za-z0-9_-]+$/.test(key))
      return failure(422, "VALIDATION_ERROR");
    headers.set("idempotency-key", key);
    const match = request.headers.get("if-match");
    if (request.method === "DELETE" || path.endsWith("/corrections")) {
      if (!etag(match)) return failure(422, "VALIDATION_ERROR");
      headers.set("if-match", match);
    }
    if (route.input) {
      if (request.headers.get("content-type")?.split(";")[0]?.trim() !== "application/json")
        return failure(415, "VALIDATION_ERROR");
      try {
        body = await boundedText(request.body, 1024 * 1024);
      } catch (error) {
        return error instanceof BodyTooLarge
          ? failure(413, "EXTRACTION_TOO_LARGE")
          : failure(422, "VALIDATION_ERROR");
      }
      try {
        if (!route.input(JSON.parse(body))) return failure(422, "VALIDATION_ERROR");
      } catch {
        return failure(422, "VALIDATION_ERROR");
      }
      headers.set("content-type", "application/json");
    } else {
      try {
        await boundedText(request.body, 0);
      } catch {
        return failure(422, "VALIDATION_ERROR");
      }
    }
  }
  if (route.stream) {
    const last = request.headers.get("last-event-id");
    if (last !== null) {
      if (!/^[1-9]\d*$/.test(last) || !Number.isSafeInteger(Number(last)))
        return failure(422, "VALIDATION_ERROR");
      headers.set("last-event-id", last);
    }
  }
  try {
    const upstream = await fetcher(`${config.baseUrl}${route.upstream}${query}`, {
      method: request.method,
      headers,
      body,
      signal: request.signal,
      redirect: "manual",
      cache: "no-store",
    });
    if (upstream.status >= 300 && upstream.status < 400) {
      await upstream.body?.cancel();
      return failure(502, "UPSTREAM_UNAVAILABLE");
    }
    const outputHeaders = new Headers({ "cache-control": "no-store" });
    if (upstream.ok && route.stream) {
      if (
        !upstream.headers.get("content-type")?.startsWith("text/event-stream") ||
        !upstream.body
      ) {
        await upstream.body?.cancel();
        return failure(502, "INVALID_RESPONSE");
      }
      outputHeaders.set("content-type", "text/event-stream");
      outputHeaders.set("x-accel-buffering", "no");
      return new Response(upstream.body, { status: upstream.status, headers: outputHeaders });
    }
    if (!upstream.headers.get("content-type")?.startsWith("application/json")) {
      await upstream.body?.cancel();
      return failure(502, "INVALID_RESPONSE");
    }
    const data: unknown = JSON.parse(
      await boundedText(upstream.body, upstream.ok ? 8 * 1024 * 1024 : 65536),
    );
    if (!upstream.ok) {
      if (!guards.error(data)) return failure(502, "INVALID_RESPONSE");
      return Response.json(
        {
          error: {
            code: data.error.code,
            message: "Extraction request could not be completed",
            request_id: data.error.request_id,
            ...(uuid(data.error.details?.resource)
              ? { details: { resource: data.error.details.resource } }
              : {}),
          },
        },
        { status: upstream.status, headers: outputHeaders },
      );
    }
    if (!route.output(data) || !matchesResource(route, data, new URL(request.url).searchParams))
      return failure(502, "INVALID_RESPONSE");
    const tag = upstream.headers.get("etag");
    if (route.etag && !etag(tag)) return failure(502, "INVALID_RESPONSE");
    if (tag && etag(tag)) outputHeaders.set("etag", tag);
    const location = upstream.headers.get("location");
    if (location) {
      const target = new URL(location, config.baseUrl);
      const base = new URL(config.baseUrl);
      const match =
        /^\/v1\/(extraction-runs|approved-extractions)\/([0-9a-f-]+)(?:\/versions\/([0-9a-f-]+))?$/i.exec(
          target.pathname,
        );
      if (
        target.origin !== base.origin ||
        target.username ||
        target.password ||
        target.search ||
        target.hash ||
        !match ||
        !uuid(match[2]) ||
        (match[3] !== undefined && !uuid(match[3])) ||
        !(match[1] === "extraction-runs"
          ? guards.run(data) && !match[3] && data.id.toLowerCase() === match[2].toLowerCase()
          : guards.approved(data) &&
            data.record_id.toLowerCase() === match[2].toLowerCase() &&
            (!match[3] || data.version_id.toLowerCase() === match[3].toLowerCase()))
      )
        return failure(502, "INVALID_RESPONSE");
      outputHeaders.set(
        "location",
        `/api/extraction/${match[1] === "extraction-runs" ? "runs" : "approved"}/${match[2]}${match[3] ? `/versions/${match[3]}` : ""}`,
      );
    }
    return Response.json(data, { status: upstream.status, headers: outputHeaders });
  } catch (error) {
    return error instanceof BodyTooLarge
      ? failure(413, "EXTRACTION_TOO_LARGE")
      : failure(502, "UPSTREAM_UNAVAILABLE");
  }
}

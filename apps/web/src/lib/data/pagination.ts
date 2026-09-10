import type { Page, PageOptions } from "./evidence-source";

type ContractError = new (reason: string) => Error;

export function pageQuery(options: PageOptions, ErrorType: ContractError): URLSearchParams {
  const limit = options.limit ?? (options.cursor ? undefined : 50);
  if (
    (limit !== undefined && (!Number.isInteger(limit) || limit < 1 || limit > 200)) ||
    (options.order !== undefined && options.order !== "asc" && options.order !== "desc") ||
    (options.cursor !== undefined && (!options.cursor || options.cursor.length > 2048))
  ) {
    throw new ErrorType("invalid page options");
  }
  const query = new URLSearchParams();
  if (limit !== undefined) query.set("limit", String(limit));
  if (options.cursor) query.set("cursor", options.cursor);
  if (options.order) query.set("order", options.order);
  return query;
}

export function readPage<T>(
  items: T[],
  headers: Headers,
  options: PageOptions,
  ErrorType: ContractError,
): Page<T> {
  const rawLimit = headers.get("X-FEL-Page-Limit");
  const limit = Number(rawLimit);
  const nextCursor = headers.get("X-FEL-Next-Cursor");
  const previousCursor = headers.get("X-FEL-Previous-Cursor");
  if (
    !rawLimit ||
    !/^\d+$/.test(rawLimit) ||
    !Number.isInteger(limit) ||
    limit < 1 ||
    limit > 200 ||
    (options.limit !== undefined && limit !== options.limit) ||
    items.length > limit ||
    [nextCursor, previousCursor].some(
      (cursor) => cursor !== null && (!cursor || cursor.length > 2048 || cursor === options.cursor),
    ) ||
    (nextCursor !== null && nextCursor === previousCursor) ||
    (items.length === 0 && (nextCursor || previousCursor))
  ) {
    throw new ErrorType("invalid or non-progressing page metadata");
  }
  return { items, nextCursor, previousCursor, limit };
}

/** Fixture continuations carry the same scope/order/limit constraints as HTTP pages. */
export function fixturePage<T>(
  items: T[],
  options: PageOptions,
  scope: string,
  ErrorType: ContractError,
): Page<T> {
  pageQuery(options, ErrorType);
  let limit = options.limit ?? 50;
  let offset = 0;
  let order = options.order ?? "asc";
  if (options.cursor) {
    try {
      const parsed = JSON.parse(Buffer.from(options.cursor, "base64url").toString("utf8"));
      if (
        Object.keys(parsed).sort().join(",") !== "limit,offset,order,scope" ||
        Buffer.from(JSON.stringify(parsed)).toString("base64url") !== options.cursor ||
        parsed.scope !== scope ||
        !Number.isInteger(parsed.offset) ||
        parsed.offset < 0 ||
        !Number.isInteger(parsed.limit) ||
        parsed.limit < 1 ||
        parsed.limit > 200 ||
        !["asc", "desc"].includes(parsed.order) ||
        (options.limit !== undefined && options.limit !== parsed.limit) ||
        (options.order !== undefined && options.order !== parsed.order)
      )
        throw new Error();
      limit = parsed.limit;
      offset = parsed.offset;
      order = parsed.order;
    } catch {
      throw new ErrorType("invalid fixture cursor scope");
    }
  }
  const ordered = order === "desc" ? [...items].reverse() : items;
  if (offset >= ordered.length && offset !== 0)
    throw new ErrorType("cursor is outside this history");
  const cursor = (at: number) =>
    Buffer.from(JSON.stringify({ scope, offset: at, limit, order })).toString("base64url");
  return {
    items: ordered.slice(offset, offset + limit),
    limit,
    nextCursor: offset + limit < ordered.length ? cursor(offset + limit) : null,
    previousCursor: offset > 0 ? cursor(Math.max(0, offset - limit)) : null,
  };
}

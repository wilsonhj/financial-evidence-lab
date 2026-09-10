import Link from "next/link";

/** Links always target a known application route; cursors remain opaque query values. */
export function PageNavigation({
  path,
  params = {},
  nextCursor,
  previousCursor,
  order = "asc",
  cursorKey = "cursor",
  orderKey = "order",
  label = "Pages",
}: {
  path: string;
  params?: Record<string, string>;
  nextCursor: string | null;
  previousCursor: string | null;
  order?: "asc" | "desc";
  cursorKey?: string;
  orderKey?: string;
  label?: string;
}) {
  const href = (direction: "asc" | "desc", cursor?: string) => {
    const query = new URLSearchParams(params);
    query.delete(cursorKey);
    query.set(orderKey, direction);
    if (cursor) query.set(cursorKey, cursor);
    return `${path}?${query}`;
  };
  return (
    <nav className="obs-actions" aria-label={label}>
      <Link href={href("asc")}>Oldest first</Link>
      {" · "}
      <Link href={href("desc")}>Newest first</Link>
      {" · "}
      {previousCursor ? (
        <Link href={href(order, previousCursor)}>Previous page</Link>
      ) : (
        <span aria-disabled="true">Previous page</span>
      )}
      {" · "}
      {nextCursor ? (
        <Link href={href(order, nextCursor)}>Next page</Link>
      ) : (
        <span aria-disabled="true">Next page</span>
      )}
    </nav>
  );
}

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

let storedTheme: string | undefined;

// Invoke the async page with a request cookie store, then render the real
// DeskClient to verify that the server-selected theme reaches the shell.
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      name === "fel-theme" && storedTheme !== undefined ? { value: storedTheme } : undefined,
  }),
}));

import DeskPage from "./page";

describe("DeskPage theme from cookie", () => {
  it.each([
    ["oled", "oled"],
    ["light", "light"],
    ["system", "system"],
    [undefined, "system"],
    ["chartreuse", "system"],
  ])("renders cookie %s as shell theme %s", async (cookie, expected) => {
    storedTheme = cookie;
    const markup = renderToStaticMarkup(await DeskPage());
    expect(markup).toContain(`data-testid="desk-shell" data-fel-theme="${expected}"`);
  });
});

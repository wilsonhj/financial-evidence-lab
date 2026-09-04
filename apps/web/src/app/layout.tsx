import type { Metadata } from "next";
import type { ReactNode } from "react";
import { cookies } from "next/headers";
import Link from "next/link";

import { resolveDeskTheme } from "./desk/desk-state";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Financial Evidence Lab",
    template: "%s — Financial Evidence Lab",
  },
  description: "Evidence reader for ingested financial filings.",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const storedTheme = (await cookies()).get("fel-theme")?.value;
  const theme = resolveDeskTheme(storedTheme ?? null);

  return (
    <html lang="en" data-fel-theme={theme}>
      <body>
        <header className="site-header">
          <h1>
            <Link href="/">Financial Evidence Lab</Link>
          </h1>
          <p className="tagline">Version-pinned evidence reader</p>
          <nav className="site-nav" aria-label="Primary navigation">
            <Link href="/desk" data-testid="link-update-desk">
              Update Desk
            </Link>
            <Link href="/" data-testid="link-filings">
              Filings
            </Link>
            <Link href="/observatory" data-testid="link-observatory">
              Observatory
            </Link>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}

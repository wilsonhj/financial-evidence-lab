import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Financial Evidence Lab",
    template: "%s — Financial Evidence Lab",
  },
  description: "Evidence reader for ingested financial filings.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a href="#main-content" className="skip-link">
          Skip to main content
        </a>
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

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
        <header className="site-header">
          <h1>
            <Link href="/">Financial Evidence Lab</Link>
          </h1>
          <p className="tagline">Evidence Reader — fixture corpus (M1)</p>
        </header>
        {children}
      </body>
    </html>
  );
}

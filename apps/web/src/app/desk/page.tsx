import Link from "next/link";
import type { Metadata } from "next";
import { cookies } from "next/headers";

import DeskClient from "./DeskClient";
import { resolveDeskTheme } from "./desk-state";

export const metadata: Metadata = {
  title: "Earnings Update Desk",
  description: "Evidence-linked earnings review, extraction approval, and model impact preview.",
};

export default async function DeskPage() {
  const theme = resolveDeskTheme((await cookies()).get("fel-theme")?.value ?? null);

  return (
    <>
      <nav aria-label="Extraction review">
        <Link href="/extractions">Open extraction review</Link>
      </nav>
      <DeskClient initialTheme={theme} />
    </>
  );
}

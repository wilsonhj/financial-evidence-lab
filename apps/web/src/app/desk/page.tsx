import type { Metadata } from "next";

import DeskClient from "./DeskClient";

export const metadata: Metadata = {
  title: "Earnings Update Desk",
  description: "Evidence-linked earnings review, extraction approval, and model impact preview.",
};

export default function DeskPage() {
  return <DeskClient />;
}

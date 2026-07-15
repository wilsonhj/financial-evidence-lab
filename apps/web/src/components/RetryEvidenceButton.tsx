"use client";

import { useRouter } from "next/navigation";

export function RetryEvidenceButton() {
  const router = useRouter();
  return (
    <button type="button" className="retry-button" onClick={() => router.refresh()}>
      Try again
    </button>
  );
}

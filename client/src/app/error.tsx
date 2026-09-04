"use client";

import { useEffect } from "react";
import { StatePanel } from "@/components/ui/state-panel";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { console.error(error); }, [error]);
  return <StatePanel state="fatal" onRetry={reset} />;
}

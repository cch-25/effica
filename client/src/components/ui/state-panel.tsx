import { AlertCircle, CircleDashed, LockKeyhole, RefreshCw } from "lucide-react";
import type { ResourceState } from "@/lib/api/types";
import { commonStates } from "@/mocks/fixtures/states";
import { Button } from "./button";

export function StatePanel({ state, onRetry }: { state: Exclude<ResourceState, "ready">; onRetry?: () => void }) {
  const content = commonStates[state];
  const Icon = state === "loading" || state === "processing" ? CircleDashed : state === "unauthorized" || state === "consent-required" ? LockKeyhole : AlertCircle;
  return (
    <section className={`state-panel state-panel--${state}`} role="status" aria-live="polite" aria-busy={state === "loading" || state === "processing"}>
      <Icon aria-hidden="true" size={22} />
      <div><h3>{content.title}</h3><p>{content.description}</p></div>
      {onRetry && <Button variant="secondary" onClick={onRetry}><RefreshCw size={15} aria-hidden="true" /> 다시 시도</Button>}
    </section>
  );
}

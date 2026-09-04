"use client";

import { useEffect, useRef } from "react";
import { ApiError, apiRequest } from "@/lib/api/client";
import { isMockMode } from "@/lib/api/mode";
import type { ReadResult, ReadSessionView } from "@/lib/api/contracts";

type ActiveDwell = {
  sessionId: string;
  startedAt: number;
  reporting: boolean;
};

export function ArticleDwellTracker({ articleId }: { articleId: string }) {
  const active = useRef<ActiveDwell | null>(null);

  useEffect(() => {
    let disposed = false;

    const report = (event?: Event) => {
      if (isMockMode() && (document.visibilityState === "hidden" || (event?.type === "pagehide" && event.isTrusted))) return;
      const session = active.current;
      if (!session || session.reporting) return;
      session.reporting = true;
      const elapsedMs = Math.max(0, Math.round(performance.now() - session.startedAt));
      void apiRequest<ReadResult>(`/read-sessions/${encodeURIComponent(session.sessionId)}/return`, {
        method: "POST",
        body: JSON.stringify({ client_elapsed_ms: elapsedMs }),
        keepalive: true,
        authFailureMode: "return-error",
      }).catch(() => undefined);
    };

    const begin = async () => {
      try {
        const session = await apiRequest<ReadSessionView>(`/articles/${encodeURIComponent(articleId)}/read-sessions`, {
          method: "POST",
          body: JSON.stringify({ return_path: `/articles/${articleId}` }),
          authFailureMode: "return-error",
        });
        active.current = { sessionId: session.read_session_id, startedAt: performance.now(), reporting: false };
        const redirect = new URL(session.redirect_url, window.location.origin);
        if (redirect.pathname.startsWith("/api/v1/r/")) {
          await fetch(`${redirect.pathname}${redirect.search}`, {
            credentials: "include",
            redirect: "manual",
          }).catch(() => undefined);
        }
        if (disposed) report();
      } catch (error) {
        if (!(error instanceof ApiError && [401, 403, 409].includes(error.status))) throw error;
      }
    };

    const startTimer = window.setTimeout(() => void begin().catch(() => undefined), 0);
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") report();
    };
    window.addEventListener("pagehide", report);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      disposed = true;
      window.clearTimeout(startTimer);
      window.removeEventListener("pagehide", report);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      report();
    };
  }, [articleId]);

  return null;
}

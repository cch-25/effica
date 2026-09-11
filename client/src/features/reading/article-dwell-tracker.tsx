"use client";

import { useEffect } from "react";
import { apiRequest } from "@/lib/api/client";
import { isMockMode } from "@/lib/api/mode";
import type { ReadResult, ReadSessionView } from "@/lib/api/contracts";

type ActiveDwell = {
  startedAt: number;
  ready: Promise<ReadSessionView>;
  reporting: boolean;
};

export function ArticleDwellTracker({ articleId }: { articleId: string }) {
  useEffect(() => {
    let disposed = false;
    let visible = document.visibilityState !== "hidden";
    let active: ActiveDwell | null = null;

    const report = () => {
      const session = active;
      if (!session || session.reporting) return;
      session.reporting = true;
      const stoppedAt = performance.now();
      // Finish any in-flight creation/redirect before returning it. A new
      // visible session starts only after this return, avoiding overlap errors.
      void session.ready.then((created) => apiRequest<ReadResult>(`/read-sessions/${encodeURIComponent(created.read_session_id)}/return`, {
          method: "POST",
          body: JSON.stringify({ client_elapsed_ms: Math.max(0, Math.round(stoppedAt - session.startedAt)) }),
          keepalive: true,
          authFailureMode: "return-error",
        })).then(() => {
          active = null;
          if (!disposed && visible) begin();
        }).catch(() => {
          // An uncertain return may still be active server-side. Do not create
          // an overlapping session automatically after a network failure.
        });
    };

    const begin = () => {
      if (disposed || !visible || active) return;
      const session: ActiveDwell = {
        startedAt: performance.now(),
        reporting: false,
        ready: apiRequest<ReadSessionView>(`/articles/${encodeURIComponent(articleId)}/read-sessions`, {
          method: "POST",
          body: JSON.stringify({ return_path: `/articles/${articleId}` }),
          authFailureMode: "return-error",
        }).then(async (created) => {
          const redirect = new URL(created.redirect_url, window.location.origin);
          if (redirect.pathname.startsWith("/api/v1/r/")) {
            await fetch(`${redirect.pathname}${redirect.search}`, {
              credentials: "include",
              redirect: "manual",
            }).catch(() => undefined);
          }
          session.startedAt = performance.now();
          return created;
        }),
      };
      active = session;
      void session.ready.catch(() => { if (active === session) active = null; });
    };

    const startTimer = window.setTimeout(begin, 0);
    const onVisibilityChange = () => {
      if (isMockMode() && document.visibilityState === "hidden") return;
      visible = document.visibilityState !== "hidden";
      if (visible) begin();
      else report();
    };
    const onPageHide = (event: PageTransitionEvent) => {
      if (isMockMode() && event.isTrusted) return;
      visible = false;
      report();
    };
    const onPageShow = () => {
      visible = document.visibilityState !== "hidden";
      begin();
    };
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("pageshow", onPageShow);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      disposed = true;
      window.clearTimeout(startTimer);
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("pageshow", onPageShow);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      report();
    };
  }, [articleId]);

  return null;
}

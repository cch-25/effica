"use client";

import { usePathname } from "next/navigation";
import { useLayoutEffect } from "react";

/**
 * Next.js preserves the current scroll position when the next page is already
 * visible in the viewport. EFFICA treats every pathname change as a fresh page,
 * so route transitions (including browser back/forward) always start at the top.
 */
export function NavigationScrollReset() {
  const pathname = usePathname();

  useLayoutEffect(() => {
    const previousScrollRestoration = window.history.scrollRestoration;

    // Browser history restoration can run after React's layout effects and
    // overwrite the reset below. The app owns restoration for its whole life.
    window.history.scrollRestoration = "manual";
    return () => {
      window.history.scrollRestoration = previousScrollRestoration;
    };
  }, []);

  useLayoutEffect(() => {
    const resetScroll = () => {
      const root = document.documentElement;
      const previousScrollBehavior = root.style.scrollBehavior;

      // Global smooth scrolling must not animate a page transition from the old
      // position. Restore the inline value immediately after the synchronous reset.
      root.style.scrollBehavior = "auto";
      window.scrollTo({ top: 0, left: 0, behavior: "auto" });
      root.style.scrollBehavior = previousScrollBehavior;
    };

    resetScroll();
    let finalFrame = 0;
    const frame = window.requestAnimationFrame(() => {
      resetScroll();
      finalFrame = window.requestAnimationFrame(resetScroll);
    });
    return () => {
      window.cancelAnimationFrame(frame);
      window.cancelAnimationFrame(finalFrame);
    };
  }, [pathname]);

  return null;
}

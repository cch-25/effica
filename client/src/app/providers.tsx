"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { NavigationScrollReset } from "@/components/layout/navigation-scroll-reset";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { isMockMode } from "@/lib/api/mode";
import { PROFILE_UPDATED_KEY } from "@/lib/api/profile-sync";

export function Providers({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  }));

  useEffect(() => {
    if (isMockMode()) {
      void import("@/mocks/browser").then(({ startMockWorker }) => startMockWorker());
    }
  }, []);

  useEffect(() => {
    const handleRedirect = (event: Event) => router.push((event as CustomEvent<string>).detail);
    window.addEventListener("api-auth-redirect", handleRedirect);
    return () => window.removeEventListener("api-auth-redirect", handleRedirect);
  }, [router]);

  useEffect(() => {
    const refreshProfile = (event: StorageEvent) => {
      if (event.key !== PROFILE_UPDATED_KEY || event.newValue === null) return;
      void client.invalidateQueries({ queryKey: ["me"] });
      void client.invalidateQueries({ queryKey: ["visualization", "points"] });
    };
    window.addEventListener("storage", refreshProfile);
    return () => window.removeEventListener("storage", refreshProfile);
  }, [client]);

  return (
    <QueryClientProvider client={client}>
      <NavigationScrollReset />
      <ErrorBoundary>{children}</ErrorBoundary>
    </QueryClientProvider>
  );
}

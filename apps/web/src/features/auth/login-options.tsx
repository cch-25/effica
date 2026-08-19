"use client";

import { ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { StatePanel } from "@/components/ui/state-panel";
import { apiRequest } from "@/lib/api/client";
import { isMockMode } from "@/lib/api/mode";

type Provider = "google";

export function LoginOptions({ returnTo }: { returnTo: string }) {
  const router = useRouter();
  const query = useQuery({ queryKey: ["auth", "providers"], queryFn: () => apiRequest<Provider[]>("/auth/providers") });
  const begin = async () => {
    const provider: Provider = "google";
    const callback = `${window.location.origin}/api/v1/auth/${provider}/callback`;
    const params = new URLSearchParams({ redirect_uri: callback, returnTo });
    const startPath = `/api/v1/auth/${provider}/start?${params}`;
    if (isMockMode()) {
      const response = await fetch(startPath, { redirect: "manual" });
      const location = response.headers.get("Location") || "/onboarding/consent";
      router.push(location);
      return;
    }
    window.open(startPath, "_self", "noopener");
  };

  if (query.isError) return <StatePanel state="error" onRetry={() => void query.refetch()} />;
  if (query.isPending) return <StatePanel state="loading" />;
  if (!query.data.includes("google")) {
    return <StatePanel state="error" onRetry={() => void query.refetch()} />;
  }
  return <div className="oauth-list"><Button variant="secondary" className="oauth-button" onClick={() => void begin()}><ShieldCheck size={16} /> Google로 계속하기</Button></div>;
}

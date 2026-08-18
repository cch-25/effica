"use client";

import { MessageCircle, Search, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { StatePanel } from "@/components/ui/state-panel";
import { apiRequest } from "@/lib/api/client";
import { isMockMode } from "@/lib/api/mode";

type Provider = "kakao" | "naver" | "google" | "mock";

const labels: Record<Provider, string> = { kakao: "Kakao", naver: "Naver", google: "Google", mock: "로컬 mock" };

function ProviderIcon({ provider }: { provider: Provider }) {
  if (provider === "kakao") return <MessageCircle size={16} />;
  if (provider === "google") return <Search size={16} />;
  if (provider === "naver") return <strong>N</strong>;
  return <ShieldCheck size={16} />;
}

export function LoginOptions({ returnTo }: { returnTo: string }) {
  const router = useRouter();
  const query = useQuery({ queryKey: ["auth", "providers"], queryFn: () => apiRequest<Provider[]>("/auth/providers") });
  const begin = (provider: Provider) => {
    if (provider === "mock" && isMockMode()) {
      router.push("/onboarding/consent");
      return;
    }
    const callback = `${window.location.origin}/api/v1/auth/${provider}/callback`;
    const query = new URLSearchParams({ redirect_uri: callback, returnTo });
    window.open(`/api/v1/auth/${provider}/start?${query}`, "_self", "noopener");
  };

  if (query.isError) return <StatePanel state="error" onRetry={() => void query.refetch()} />;
  if (query.isPending) return <StatePanel state="loading" />;
  const providers = query.data;
  if (providers.length === 0) return <StatePanel state="empty" />;
  return <div className="oauth-list">{providers.map((provider) => <Button key={provider} variant="secondary" className="oauth-button" onClick={() => begin(provider)}><ProviderIcon provider={provider} /> {labels[provider]}로 계속하기</Button>)}</div>;
}

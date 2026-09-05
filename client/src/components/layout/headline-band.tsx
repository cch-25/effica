"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api/client";
import { isMockMode } from "@/lib/api/mode";
import type { FeedPageDto } from "@/lib/api/mappers";

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  apos: "'",
  gt: ">",
  hellip: "…",
  ldquo: "“",
  lsquo: "‘",
  lt: "<",
  middot: "·",
  nbsp: " ",
  quot: "\"",
  rdquo: "”",
  rsquo: "’",
};

export function decodeHeadlineEntities(value: string) {
  let decoded = value;
  for (let pass = 0; pass < 2; pass += 1) {
    decoded = decoded.replace(/&(#x[\da-f]+|#\d+|[a-z][\da-z]+);/gi, (entity, code: string) => {
      if (code.startsWith("#")) {
        const hex = code[1]?.toLowerCase() === "x";
        const point = Number.parseInt(code.slice(hex ? 2 : 1), hex ? 16 : 10);
        if (!Number.isFinite(point) || point < 0 || point > 0x10ffff) return entity;
        return String.fromCodePoint(point);
      }
      return NAMED_ENTITIES[code.toLowerCase()] ?? entity;
    });
  }
  return decoded;
}

export function HeadlineBand() {
  const mock = isMockMode();
  const feed = useQuery({
    queryKey: ["headline-band", "latest"],
    queryFn: () => apiRequest<FeedPageDto>("/feed?mode=balanced"),
    enabled: !mock,
    staleTime: 60_000,
  });
  const latest = feed.data?.items
    .slice()
    .sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""))
    .slice(0, 5)
    .map((item) => ({ id: item.article_id, title: decodeHeadlineEntities(item.title), href: `/articles/${item.article_id}` }));
  const headlines = latest ?? [];
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    if (headlines.length < 2 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => setActiveIndex((current) => (current + 1) % headlines.length), 5_000);
    return () => window.clearInterval(timer);
  }, [headlines.length]);

  const active = headlines.length ? headlines[activeIndex % headlines.length] : undefined;
  const statusMessage = mock || (!feed.isPending && !feed.isError)
    ? "현재 표시할 최신 기사가 없습니다."
    : feed.isError
      ? "최신 기사를 불러오지 못했습니다."
      : "최신 기사를 불러오는 중입니다.";

  return (
    <header className="headline-band" aria-label="최신 기사">
      {active ? (
        <Link className="headline-band__story" href={active.href}>
          <span key={`${active.id}-${activeIndex}`} className="headline-band__story-text">{active.title}</span>
        </Link>
      ) : (
        <span className="headline-band__story" role="status" aria-live="polite">
          <span className="headline-band__story-text">{statusMessage}</span>
        </span>
      )}
    </header>
  );
}

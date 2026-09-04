"use client";

import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api/client";
import { isMockMode } from "@/lib/api/mode";
import type { FeedPageDto } from "@/lib/api/mappers";

type Headline = { id: string; title: string; href: string };

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

const VERIFIED_HEADLINES: Headline[] = [
  {
    id: "newstomato-20260826-approval",
    title: "이 대통령 지지율 첫 30%대…부정평가 57.9%",
    href: "https://www3.newstomato.com/ReadNews.aspx?no=1311426",
  },
  {
    id: "sbs-20260826-police",
    title: "\"경찰 권력에 국민 우려 커\"…민주 \"개혁 추진\"",
    href: "https://news.sbs.co.kr/news/programMain.do?cooper=SBSNEWS&plink=GNB",
  },
  {
    id: "sbs-20260826-tax",
    title: "'황제 사택' 인테리어에 관리비까지…\"1조 9천억 탈루\"",
    href: "https://news.sbs.co.kr/news/programMain.do?cooper=SBSNEWS&plink=GNB",
  },
  {
    id: "sbs-20260826-bonus",
    title: "\"성과급 60%는 주식\" 합의안 부결…재협상 불가피",
    href: "https://news.sbs.co.kr/news/programMain.do?cooper=SBSNEWS&plink=GNB",
  },
  {
    id: "sbs-20260826-diplomacy",
    title: "'김정은과 찰칵' 또 올려…'비핵화' 피한 한미 통화",
    href: "https://news.sbs.co.kr/news/programMain.do?cooper=SBSNEWS&plink=GNB",
  },
];

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
  const headlines = latest?.length ? latest : VERIFIED_HEADLINES;
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    if (headlines.length < 2 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => setActiveIndex((current) => (current + 1) % headlines.length), 5_000);
    return () => window.clearInterval(timer);
  }, [headlines.length]);

  const active = headlines[activeIndex % headlines.length];
  const text = <span key={`${active.id}-${activeIndex}`} className="headline-band__story-text">{active.title}</span>;

  return (
    <header className="headline-band" aria-label="최신 기사">
      <span className="headline-band__label">최신 기사</span>
      {active.href.startsWith("http") ? (
        <a className="headline-band__story" href={active.href} target="_blank" rel="noreferrer">{text}<span className="headline-band__destination">외부 기사</span><ExternalLink size={13} aria-hidden="true" /><span className="sr-only">새 창에서 열림</span></a>
      ) : (
        <Link className="headline-band__story" href={active.href}>{text}</Link>
      )}
    </header>
  );
}

"use client";

import { Avatar } from "@base-ui/react/avatar";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, BookOpenText, Boxes, CircleGauge, Compass, FileText, Home, Landmark, Newspaper, Settings, Share2, SlidersHorizontal, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

const userNav = [
  { href: "/", label: "홈", icon: Home },
  { href: "/issues", label: "이슈", icon: Newspaper },
  { href: "/visualization", label: "관점 지도", icon: Compass },
  { href: "/progress", label: "나의 기록", icon: CircleGauge },
];

const adminNav = [
  { href: "/admin/sources", label: "출처", icon: Landmark },
  { href: "/admin/crawls", label: "수집", icon: Boxes },
  { href: "/admin/issues", label: "이슈", icon: Newspaper },
  { href: "/admin/models", label: "모델", icon: Sparkles },
  { href: "/admin/weights", label: "가중치", icon: SlidersHorizontal },
  { href: "/admin/autopilot", label: "Auto Pilot", icon: CircleGauge },
  { href: "/admin/jobs", label: "작업", icon: BarChart3 },
  { href: "/admin/audit", label: "감사 로그", icon: FileText },
  { href: "/admin/metrics/efficacy", label: "효능감", icon: BookOpenText },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const admin = pathname.startsWith("/admin");
  const minimal = pathname === "/login" || pathname.startsWith("/onboarding");
  const nav = admin ? adminNav : userNav;

  if (minimal) return <main className="minimal-shell">{children}</main>;

  return (
    <div className={admin ? "shell shell--admin" : "shell"}>
      <a className="skip-link" href="#main-content">본문으로 건너뛰기</a>
      <aside className="sidebar">
        <Link href={admin ? "/admin/sources" : "/"} className="brand" aria-label="사이: 홈">
          <Avatar.Root className="brand__mark" aria-hidden="true"><Avatar.Fallback>사이</Avatar.Fallback></Avatar.Root>
          <span><strong>SAI</strong><small>{admin ? "운영 관제" : "관점 사이를 읽다"}</small></span>
        </Link>
        <nav aria-label={admin ? "관리자 메뉴" : "주요 메뉴"}>
          {nav.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === href : pathname.startsWith(href);
            return <Link key={href} href={href} className={active ? "nav-link is-active" : "nav-link"} aria-current={active ? "page" : undefined}><Icon size={18} aria-hidden="true" />{label}</Link>;
          })}
        </nav>
        <div className="sidebar__foot">
          {admin ? <Link href="/" className="nav-link"><Compass size={18} /> 사용자 웹</Link> : <><Link href="/share/new" className="nav-link"><Share2 size={18} /> 공유 카드</Link><Link href="/settings/privacy" className="nav-link"><Settings size={18} /> 개인정보</Link></>}
          <Link href="/login" className="profile-chip"><Avatar.Root className="profile-avatar"><Avatar.Fallback>김</Avatar.Fallback></Avatar.Root><span><strong>김사이</strong><small>{admin ? "Admin" : "Member"}</small></span></Link>
        </div>
      </aside>
      <main id="main-content" className="main-content" tabIndex={-1}>{children}</main>
      {!admin && <nav className="bottom-nav" aria-label="모바일 주요 메뉴">{userNav.map(({ href, label, icon: Icon }) => <Link key={href} href={href} aria-current={pathname === href ? "page" : undefined}><Icon size={20} /><span>{label}</span></Link>)}</nav>}
    </div>
  );
}

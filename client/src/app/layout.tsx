import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import "./base-ui.css";
import "./comparison-visualization.css";
import "./consumption.css";
import "./art-direction.css";
import "./graphs.css";
import "./readability.css";
import "./accent-colors.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/layout/app-shell";
import { serverApiRequest } from "@/lib/api/server";
import type { UserView } from "@/lib/api/contracts";
import { isMockMode } from "@/lib/api/mode";

const newspaperFont = localFont({
  src: [
    { path: "../../public/fonts/ChosunShinMyungjo.woff2", weight: "400", style: "normal" },
    { path: "../../public/fonts/ChosunBoldMyungjo.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-newspaper", display: "swap", preload: true,
});

export const metadata: Metadata = {
  title: { default: "EFFICA | 관점 사이를 읽다", template: "%s | EFFICA" },
  description: "같은 이슈를 여러 관점에서 읽고, 근거를 비교하는 뉴스 플랫폼",
  icons: {
    icon: "/effica.svg",
    shortcut: "/effica.svg",
    apple: "/effica.svg",
  },
};

const MOCK_MEMBER: UserView = {
  id: "01HZZZZZZZZZZZZZZZZZZZZZZ1",
  display_name: "Mock 사용자",
  role: "MEMBER",
  consent_complete: true,
  onboarding_complete: true,
  behavioral_profile_active: false,
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const user = isMockMode() ? MOCK_MEMBER : await serverApiRequest<UserView>("/me").catch(() => null);
  return (
    <html lang="ko" className={newspaperFont.variable} data-scroll-behavior="smooth">
      <body>
        <div className="app-root">
          <Providers><AppShell user={user} editionDate={new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "long", day: "numeric", weekday: "long", timeZone: "Asia/Seoul" }).format(new Date())}>{children}</AppShell></Providers>
        </div>
      </body>
    </html>
  );
}

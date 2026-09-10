import Link from "next/link";

export function NewspaperMasthead({ date, section = "종합", compact = false }: { date: string; section?: string; compact?: boolean }) {
  return <header className={`newspaper-masthead${compact ? " newspaper-masthead--compact" : ""}`}>
    <div className="newspaper-masthead__top"><span>보도 비교와 관점 분석</span><span>EFFICA NEWS</span><span>{section}</span></div>
    <div className="newspaper-masthead__identity">
      <div className="newspaper-masthead__note"><strong>같은 사실, 다른 시선</strong><span>여러 출처를 함께 읽습니다.</span></div>
      <Link href="/" className="newspaper-masthead__name" aria-label="EFFICA 홈">에피카<span>EFFICA</span></Link>
      <div className="newspaper-masthead__note newspaper-masthead__note--right"><strong>관점 사이를 읽다</strong><span>근거를 살피고 판단은 독자에게.</span></div>
    </div>
    <div className="newspaper-masthead__edition"><span>{date}</span><span>뉴스를 읽는 또 하나의 관점</span><span>{section}판</span></div>
  </header>;
}

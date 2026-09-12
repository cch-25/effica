import Link from "next/link";

export function NewspaperMasthead({ date, section = "종합", compact = false }: { date: string; section?: string; compact?: boolean }) {
  return <header className={`newspaper-masthead${compact ? " newspaper-masthead--compact" : ""}`}>
    <div className="newspaper-masthead__identity">
      <div className="newspaper-masthead__note"><strong>보도 비교와 관점 분석</strong><span>같은 사실을 여러 출처로 읽습니다.</span></div>
      <Link href="/" className="newspaper-masthead__name" aria-label="EFFICA 홈"><span className="newspaper-masthead__title">에피카</span><span className="newspaper-masthead__subtitle">EFFICA NEWS</span></Link>
      <div className="newspaper-masthead__note newspaper-masthead__note--right"><strong>근거를 살피고 판단은 독자에게</strong><span>기사 분석 / 보도 비교 / 독자 기록</span></div>
    </div>
    <div className="newspaper-masthead__edition"><span>{date}</span><span>뉴스를 읽는 또 하나의 관점</span><span>{section}판</span></div>
  </header>;
}

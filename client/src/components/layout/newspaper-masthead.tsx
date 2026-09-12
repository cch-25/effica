import Link from "next/link";

export function NewspaperMasthead({ date, compact = false }: { date: string; section?: string; compact?: boolean }) {
  return <header className={`newspaper-masthead${compact ? " newspaper-masthead--compact" : ""}`}>
    <div className="newspaper-masthead__identity">
      <div className="newspaper-masthead__note"><span>{date}</span></div>
      <Link href="/" className="newspaper-masthead__name" aria-label="EFFICA 홈"><span className="newspaper-masthead__title">에피카</span><span className="newspaper-masthead__subtitle">EFFICA NEWS</span></Link>
      <div className="newspaper-masthead__note newspaper-masthead__note--right"><span>같은 사실, 여러 관점</span></div>
    </div>

  </header>;
}

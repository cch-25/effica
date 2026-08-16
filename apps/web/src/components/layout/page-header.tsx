import type { ReactNode } from "react";

const sectionCodes: Array<[RegExp, string]> = [
  [/^Issues?\b/i, "02"],
  [/^Perspective\b/i, "03"],
  [/^My activity\b/i, "04"],
  [/^Political\b/i, "05"],
  [/^Share\b/i, "06"],
  [/^Settings\b/i, "07"],
  [/^Collection\b/i, "01"],
  [/^Ingestion\b/i, "02"],
  [/^Issue desk\b/i, "03"],
  [/^Model\b/i, "04"],
  [/^Weight\b/i, "05"],
  [/^Auto Pilot\b/i, "06"],
  [/^MariaDB\b/i, "07"],
  [/^Audit\b/i, "08"],
  [/^Protected\b/i, "09"],
  [/./, "08"],
];

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  const explicitCode = eyebrow.match(/\b\d{2}\b/)?.[0];
  const register = explicitCode ?? sectionCodes.find(([pattern]) => pattern.test(eyebrow))?.[1] ?? "08";
  const accent = Number(register) % 3 === 0 ? "red" : Number(register) % 2 === 0 ? "blue" : "yellow";

  return (
    <header className="page-header" data-accent={accent}>
      <div className="page-header__register" aria-hidden="true"><span>{register}</span><small>SECTION<br />INDEX</small></div>
      <div className="page-header__body"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="page-header__description">{description}</p></div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  );
}

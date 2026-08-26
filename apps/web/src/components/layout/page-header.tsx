import type { ReactNode } from "react";

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div className="page-header__body"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="page-header__description">{description}</p></div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  );
}

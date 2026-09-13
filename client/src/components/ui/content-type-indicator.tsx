import styles from "./content-type-indicator.module.css";
import type { ReactNode } from "react";

const issueOrdinalCharacters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

export function issueOrdinalLabel(index: number): string {
  if (!Number.isInteger(index) || index < 0) return "";

  let value = index + 1;
  let label = "";
  do {
    value -= 1;
    label = issueOrdinalCharacters[value % issueOrdinalCharacters.length] + label;
    value = Math.floor(value / issueOrdinalCharacters.length);
  } while (value > 0);

  return label;
}

export function ContentTypeIndicator({ kind, issueOrdinal }: { kind: "issue" | "article"; issueOrdinal?: number }) {
  const issueLabel = issueOrdinal === undefined ? "" : issueOrdinalLabel(issueOrdinal);
  const label = kind === "issue" ? `이슈${issueLabel ? ` ${issueLabel}` : ""}` : "기사";

  return <span className={`${styles.indicator} ${styles[kind]}`} data-content-type={kind}>{label}</span>;
}

export function ContentTypeLine({ children, kind, issueOrdinal }: { children: ReactNode; kind: "issue" | "article"; issueOrdinal?: number }) {
  return <span className={styles.line} data-content-type-line>
    <ContentTypeIndicator kind={kind} issueOrdinal={issueOrdinal} />
    <span className={styles.copy} data-content-type-copy>{children}</span>
  </span>;
}

import { IssuesBrowser } from "@/features/issues/issues-browser";
import { issues } from "@/mocks/fixtures/content";

export const metadata = { title: "이슈" };

export default function IssuesPage() {
  return <IssuesBrowser fallback={issues} />;
}

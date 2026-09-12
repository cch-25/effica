import { IssuesBrowser } from "@/features/issues/issues-browser";
import { issues } from "@/mocks/fixtures/content";

export default function HomePage() { return <IssuesBrowser fallback={issues} />; }

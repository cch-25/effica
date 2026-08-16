import Link from "next/link";
import { StatePanel } from "@/components/ui/state-panel";

export default function NotFound() {
  return <><StatePanel state="fatal" /><Link className="button button--primary" href="/" style={{ marginTop: "1rem" }}>홈으로 돌아가기</Link></>;
}

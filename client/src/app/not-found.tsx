import { StatePanel } from "@/components/ui/state-panel";
import { ButtonLink } from "@/components/ui/button";

export default function NotFound() {
  return <><StatePanel state="fatal" /><ButtonLink href="/" style={{ marginTop: "1rem" }}>홈으로 돌아가기</ButtonLink></>;
}

import { PageHeader } from "@/components/layout/page-header";
import { ButtonLink } from "@/components/ui/button";

export default function NotFound() {
  return <div className="newspaper-not-found"><PageHeader eyebrow="독자 안내 / 404" title="요청하신 지면을 찾을 수 없습니다" description="주소가 바뀌었거나 더 이상 제공하지 않는 자료입니다. 종합 1면이나 이슈 목록에서 다른 기사를 찾아보세요." /><div className="form-actions"><ButtonLink href="/">홈으로 돌아가기</ButtonLink><ButtonLink variant="secondary" href="/issues">이슈 찾아보기</ButtonLink></div></div>;
}

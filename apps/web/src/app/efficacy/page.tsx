import { PageHeader } from "@/components/layout/page-header";
import { EfficacyForm } from "@/features/efficacy/efficacy-form";

export default function EfficacyPage() { return <><PageHeader eyebrow="Political efficacy" title="이해한다는 감각의 변화" description="반복 설문의 개인 추이입니다. 변화는 상관관계이며 서비스 사용의 인과 효과로 표현하지 않습니다." /><div className="grid grid--3"><section className="card metric"><small>기준선</small><strong>52</strong><span>2026. 05. 12.</span></section><section className="card metric"><small>최근 측정</small><strong>64</strong><span>2026. 08. 12.</span></section><section className="card metric"><small>개인 변화</small><strong>+12</strong><span>normalized score</span></section></div><div style={{ marginTop: "1rem" }}><EfficacyForm /></div></>; }

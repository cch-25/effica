import { PageHeader } from "@/components/layout/page-header";
import { VisualizationExplorer } from "@/features/visualization/visualization-explorer";

export default function VisualizationPage() {
  return <div className="visualization-page"><PageHeader eyebrow="관점 지도" title="기사 관점 지도" description="기사의 편향과 표현 강도를 입체적으로 비교하세요. 점을 선택하면 분석 수치와 기사로 이어집니다." /><VisualizationExplorer /></div>;
}

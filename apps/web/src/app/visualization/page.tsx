import { PageHeader } from "@/components/layout/page-header";
import { VisualizationExplorer } from "@/features/visualization/visualization-explorer";

export default function VisualizationPage() {
  return <div className="visualization-page"><PageHeader eyebrow="관점 지도" title="두 기준으로 읽는 관점" description="편향성과 과장성 두 기준을 보여주며, 분석 신뢰도는 보조 정보로 제공합니다." /><VisualizationExplorer /></div>;
}

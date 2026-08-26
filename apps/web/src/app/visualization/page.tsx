import { PageHeader } from "@/components/layout/page-header";
import { VisualizationExplorer } from "@/features/visualization/visualization-explorer";

export default function VisualizationPage() {
  return <div className="visualization-page"><PageHeader eyebrow="관점 지도" title="나의 기준에서 본 기사 지형" description="개인 프로필과 기사 좌표의 거리를 비교하고, 전체 분포는 왜곡 없이 함께 보여줍니다." /><VisualizationExplorer /></div>;
}

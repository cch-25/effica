import { PageHeader } from "@/components/layout/page-header";
import { VisualizationExplorer } from "@/features/visualization/visualization-explorer";

export default function VisualizationPage() {
  return <div className="visualization-page"><PageHeader eyebrow="관점 지도" title="기사 관점 지도" description="가로는 편향성, 세로는 과장성입니다. 각 점은 실제 기사 수치이며 배경은 기사가 모인 구간을 보여줍니다." /><VisualizationExplorer /></div>;
}

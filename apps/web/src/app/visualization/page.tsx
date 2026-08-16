import { PageHeader } from "@/components/layout/page-header";
import { VisualizationExplorer } from "@/features/visualization/visualization-explorer";

export default function VisualizationPage() { return <><PageHeader eyebrow="Perspective atlas" title="관점을 좌표로, 좌표를 맥락으로" description="기사·언론사·사용자의 관찰값을 3축으로 탐색합니다. 3D를 사용하지 않아도 2D 투영과 정렬 가능한 표에서 동일한 데이터에 접근할 수 있습니다." /><VisualizationExplorer /></>; }

"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { Group } from "three";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { StatePanel } from "@/components/ui/state-panel";
import { Tabs } from "@/components/ui/tabs";
import { visualizationPoints } from "@/mocks/fixtures/content";
import type { VisualizationPoint } from "@/lib/api/types";

function PointCloud({ points, selected, onSelect, rotation }: { points: VisualizationPoint[]; selected: string; onSelect: (id: string) => void; rotation: [number, number] }) {
  const group = useRef<Group>(null);
  useFrame(() => { if (group.current) { group.current.rotation.x = rotation[0]; group.current.rotation.y = rotation[1]; } });
  const color = { article: "#000", source: "#525252", user: "#a3a3a3" };
  return <group ref={group}>{points.map((point) => <mesh key={point.id} position={[point.x / 23, point.y / 23, point.z / 23]} onClick={(event) => { event.stopPropagation(); onSelect(point.id); }}><sphereGeometry args={[selected === point.id ? .22 : .14, 18, 18]} /><meshStandardMaterial color={selected === point.id ? "#2457e6" : color[point.type]} emissive={selected === point.id ? "#2457e6" : "#000"} emissiveIntensity={selected === point.id ? .35 : 0} /></mesh>)}<gridHelper args={[10, 10, "#d4d4d4", "#e5e5e5"]} rotation={[Math.PI / 2, 0, 0]} /></group>;
}

export function VisualizationExplorer() {
  const [mode, setMode] = useState<"3d" | "2d" | "table">("3d");
  const [projection, setProjection] = useState<"xy" | "xz" | "yz">("xy");
  const [selected, setSelected] = useState(visualizationPoints[0].id);
  const [zoom, setZoom] = useState(9);
  const [rotation, setRotation] = useState<[number, number]>([-.25, .4]);
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const [sort, setSort] = useState<keyof Pick<VisualizationPoint, "label" | "x" | "y" | "z" | "confidence">>("label");
  const webglAvailable = useSyncExternalStore(
    () => () => undefined,
    () => "WebGLRenderingContext" in window && !new URLSearchParams(window.location.search).has("webgl-off"),
    () => true,
  );
  const effectiveMode = !webglAvailable && mode === "3d" ? "2d" : mode;
  const current = visualizationPoints.find((point) => point.id === selected) ?? visualizationPoints[0];
  const [horizontal, vertical] = projection.split("") as Array<"x" | "y" | "z">;
  const sorted = useMemo(() => [...visualizationPoints].sort((a, b) => typeof a[sort] === "string" ? String(a[sort]).localeCompare(String(b[sort]), "ko") : Number(a[sort]) - Number(b[sort])), [sort]);
  return <>
    {!webglAvailable && <div style={{ marginBottom: "1rem" }}><StatePanel state="partial" /></div>}
    <div className="admin-toolbar"><Tabs label="시각화 방식" value={effectiveMode} onChange={setMode} items={[{ value: "3d", label: "3D", disabled: !webglAvailable }, { value: "2d", label: "2D 투영" }, { value: "table", label: "데이터 표" }]} /><div className="page-header__actions"><Button variant="secondary" className="button--icon" aria-label="축소" onClick={() => setZoom(Math.min(14, zoom + 1))}><ZoomOut size={16} /></Button><Button variant="secondary" className="button--icon" aria-label="확대" onClick={() => setZoom(Math.max(5, zoom - 1))}><ZoomIn size={16} /></Button><Button variant="secondary" onClick={() => { setZoom(9); setRotation([-.25, .4]); }}><RotateCcw size={16} /> 초기화</Button></div></div>
    <div className="legend" aria-label="포인트 범례"><span><i /> 기사</span><span><i /> 언론사</span><span><i /> 사용자 응답 결과</span><span>크기: 선택 상태 · 위치: 3축 좌표</span></div>
    <div style={{ marginTop: ".8rem" }}>
      {effectiveMode === "3d" && <div className="viz-canvas" onPointerDown={(event) => setDrag({ x: event.clientX, y: event.clientY })} onPointerMove={(event) => { if (!drag) return; setRotation(([x,y]) => [x + (event.clientY-drag.y)*.005, y + (event.clientX-drag.x)*.005]); setDrag({ x: event.clientX, y: event.clientY }); }} onPointerUp={() => setDrag(null)} onPointerLeave={() => setDrag(null)}><Canvas camera={{ position: [0, 0, zoom], fov: 50 }}><ambientLight intensity={1.8} /><directionalLight position={[3, 4, 5]} intensity={2} /><PointCloud points={visualizationPoints} selected={selected} onSelect={setSelected} rotation={rotation} /></Canvas></div>}
      {effectiveMode === "2d" && <><Tabs className="tabs-root--spaced" label="2D 투영 축 선택" value={projection} onChange={setProjection} items={[{ value: "xy", label: "경제 × 사회문화" }, { value: "xz", label: "경제 × 국가·대외" }, { value: "yz", label: "사회문화 × 국가·대외" }]} /><div className="projection" aria-label={`${horizontal.toUpperCase()}축과 ${vertical.toUpperCase()}축 2D 투영`}>{visualizationPoints.map((point) => <Button key={point.id} variant="ghost" className={`projection__point projection__point--${point.type}`} data-selected={selected === point.id ? "" : undefined} style={{ left: `${(point[horizontal] + 100) / 2}%`, top: `${100 - (point[vertical] + 100) / 2}%` }} onClick={() => setSelected(point.id)} aria-label={`${point.label}, ${horizontal.toUpperCase()} ${point[horizontal]}, ${vertical.toUpperCase()} ${point[vertical]}`}><span className="projection__label">{point.label}</span></Button>)}</div></>}
      {effectiveMode === "table" && <div className="table-wrap"><table className="data-table"><thead><tr><th><Button variant="ghost" className="table-sort" onClick={() => setSort("label")}>이름</Button></th><th>유형</th>{(["x","y","z","confidence"] as const).map((key) => <th key={key}><Button variant="ghost" className="table-sort" onClick={() => setSort(key)}>{key === "confidence" ? "신뢰도" : key.toUpperCase()}</Button></th>)}<th>버전</th></tr></thead><tbody>{sorted.map((point) => <tr key={point.id}><td><Button variant="ghost" className="table-sort" onClick={() => setSelected(point.id)}>{point.label}</Button></td><td>{point.type}</td><td>{point.x}</td><td>{point.y}</td><td>{point.z}</td><td>{Math.round(point.confidence*100)}%</td><td>{point.scoreVersion}</td></tr>)}</tbody></table></div>}
    </div>
    <section className="card card--padded" style={{ marginTop: "1rem" }} aria-live="polite"><div className="issue-card__top"><Badge tone="info">{current.type}</Badge><Badge>{current.scoreVersion}</Badge></div><h2 style={{ marginTop: ".7rem" }}>{current.label}</h2><div className="grid grid--4"><div className="metric"><small>경제 X</small><strong>{current.x}</strong></div><div className="metric"><small>사회문화 Y</small><strong>{current.y}</strong></div><div className="metric"><small>국가·대외 Z</small><strong>{current.z}</strong></div><div className="metric"><small>Confidence</small><strong>{Math.round(current.confidence*100)}%</strong></div></div><p style={{ color: "var(--muted)" }}>관찰 시각 {current.observedAt} · 과장성 {current.sensationalism}</p><div className="section-head"><h3>날짜·score version 시계열</h3></div><div className="timeline" aria-label={`${current.label} 좌표 시계열`}><div><time>2026-06-16</time><span style={{ width: `${Math.abs(current.x - 6) + 22}%` }} /><strong>{current.scoreVersion}-2 · X {current.x - 6}</strong></div><div><time>2026-07-16</time><span style={{ width: `${Math.abs(current.x - 3) + 22}%` }} /><strong>{current.scoreVersion}-1 · X {current.x - 3}</strong></div><div><time>2026-08-16</time><span style={{ width: `${Math.abs(current.x) + 22}%` }} /><strong>{current.scoreVersion} · X {current.x}</strong></div></div></section>
  </>;
}

"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Minus, Move, Plus, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { GraphAxes, GraphPoint, GraphView } from "./graph-model";
import type { createGraphScene } from "./three-scene";

type Props = {
  axes: GraphAxes;
  points: GraphPoint[];
  selectedId: string;
  title: string;
  onSelect?: (ids: string[]) => void;
  emptyMessage?: string;
};

export function InteractiveGraph({ axes, points, selectedId, title, onSelect, emptyMessage }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const runtime = useRef<ReturnType<typeof createGraphScene> | null>(null);
  const latest = useRef({ points, selectedId, onSelect });
  const [status, setStatus] = useState<"loading" | "ready" | "unavailable">("loading");
  const [interactive, setInteractive] = useState(false);
  const [view, setView] = useState<GraphView>("space");
  const instructionsId = useId();
  useEffect(() => {
    latest.current = { points, selectedId, onSelect };
    runtime.current?.update(points, selectedId);
  }, [points, selectedId, onSelect]);

  useEffect(() => {
    const node = host.current;
    if (!node) return;
    let cancelled = false;
    const lost = (event: Event) => { event.preventDefault(); setStatus("unavailable"); };
    node.addEventListener("webglcontextlost", lost, true);
    void import("./three-scene").then(({ createGraphScene }) => {
      if (cancelled) return;
      const scene = createGraphScene(node, axes, (ids) => latest.current.onSelect?.(ids), () => setView("space"));
      runtime.current = scene;
      scene.update(latest.current.points, latest.current.selectedId);
      const enabled = matchMedia("(pointer: fine)").matches;
      scene.setInteractive(enabled); setInteractive(enabled); setStatus("ready");
    }).catch(() => { if (!cancelled) setStatus("unavailable"); });
    return () => {
      cancelled = true; node.removeEventListener("webglcontextlost", lost, true);
      runtime.current?.dispose(); runtime.current = null;
    };
  }, [axes]);

  function changeView(next: GraphView) { setView(next); runtime.current?.setView(next); }

  return <div className="graph-3d" data-status={status} data-view={view}>
    <div className="graph-3d__toolbar">
      <div className="graph-3d__views" role="group" aria-label="그래프 보기 방식">
        {([["space", "입체"], ["front", "정면"], ["top", "위에서"]] as const).map(([value, label]) => <Button key={value} variant="ghost" aria-pressed={view === value} disabled={status !== "ready"} onClick={() => changeView(value)}>{label}</Button>)}
      </div>
      <div className="graph-3d__tools" role="group" aria-label="3D 시점 조절">
        <Button variant="ghost" aria-label="마우스와 터치로 회전" aria-pressed={interactive} disabled={status !== "ready"} onClick={() => { setInteractive(!interactive); runtime.current?.setInteractive(!interactive); }}><Move size={15} /></Button>
        <Button variant="ghost" aria-label="확대" disabled={status !== "ready"} onClick={() => runtime.current?.zoom(.15)}><Plus size={15} /></Button>
        <Button variant="ghost" aria-label="축소" disabled={status !== "ready"} onClick={() => runtime.current?.zoom(-.15)}><Minus size={15} /></Button>
        <Button variant="ghost" aria-label="처음 시점으로" disabled={status !== "ready"} onClick={() => changeView("space")}><RotateCcw size={15} /></Button>
      </div>
    </div>
    <div className="graph-3d__viewport">
      <div className="graph-3d__canvas article-space__canvas" ref={host} role="img" aria-label={title} aria-describedby={instructionsId} tabIndex={0}
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "+", "=", "-"].includes(event.key)) return;
          event.preventDefault();
          if (event.key === "Home") changeView("space");
          else if (["+", "=", "-"].includes(event.key)) runtime.current?.zoom(event.key === "-" ? -.15 : .15);
          else runtime.current?.rotate(event.key === "ArrowLeft" ? -.15 : event.key === "ArrowRight" ? .15 : 0, event.key === "ArrowUp" ? -.12 : event.key === "ArrowDown" ? .12 : 0);
        }} />
      {status !== "ready" ? <div className="graph-3d__fallback" role="status">
        <strong>{status === "loading" ? "3D 그래프를 불러오는 중" : "이 브라우저에서는 3D를 표시할 수 없습니다."}</strong>
        {status === "unavailable" && <span>그래프 아래의 수치와 자료 목록을 확인해 주세요.</span>}
      </div> : emptyMessage && !points.length ? <p className="graph-3d__empty">{emptyMessage}</p> : null}
    </div>
    <p className="graph-3d__instructions" id={instructionsId}>{interactive ? "드래그로 회전" : "회전 버튼을 켜면 터치로 조작"} / 방향키로 시점 이동{view === "front" ? ` / 깊이: ${axes[2].label}` : view === "top" ? ` / 높이: ${axes[1].label}` : ""}</p>
    <dl className="graph-3d__axis-key">
      {axes.map((axis, index) => <div key={axis.label}><dt>{index === 0 ? "가로" : index === 1 ? "높이" : "깊이"} <strong>{axis.label}</strong></dt><dd>{axis.low} <span aria-hidden="true">→</span> {axis.high}</dd></div>)}
    </dl>
  </div>;
}

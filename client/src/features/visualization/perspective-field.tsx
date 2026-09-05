"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Box, ChevronLeft, ChevronRight, Minus, Move, Plus, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { VisualizationPoint } from "@/lib/api/types";
import { clamp, makeSpaceData, signed } from "./field-model";
import type { SpaceCamera, createSpace } from "./space-renderer";

export type { FieldView } from "./field-model";
type SpaceRuntime = ReturnType<typeof createSpace>;
const initialCamera = (): SpaceCamera => ({ alpha: 21, beta: 34, distance: 215, center: [0, 0, 0] });

type Props = {
  points: VisualizationPoint[];
  selectedId: string;
  anchorId: string | undefined;
  title: string;
  onSelect: (id: string) => void;
};

export function PerspectiveField({ points, selectedId, anchorId, title, onSelect }: Props) {
  const element = useRef<HTMLDivElement>(null);
  const runtime = useRef<SpaceRuntime | null>(null);
  const camera = useRef(initialCamera());
  const cameraScale = useRef(1);
  const latest = useRef({ points, selectedId, onSelect });
  const [status, setStatus] = useState<"loading" | "ready" | "unavailable">("loading");
  const [rotate, setRotate] = useState(false);
  const data = useMemo(() => makeSpaceData(points), [points]);
  const measured = points.filter((point) => point.type !== "user" && point.sensationalism !== null);
  const selected = points.find((point) => point.id === selectedId);
  const index = measured.findIndex((point) => point.id === selectedId);
  const anchor = points.find((point) => point.id === anchorId && point.type === "user");

  useEffect(() => { latest.current = { points, selectedId, onSelect }; }, [points, selectedId, onSelect]);

  useEffect(() => {
    const node = element.current;
    if (!node) return;
    let cancelled = false;
    let observer: ResizeObserver | undefined;
    const fitScale = () => Math.max(1, 500 / Math.max(1, node.clientWidth));
    cameraScale.current = fitScale();
    const unavailable = (event: Event) => { event.preventDefault(); setStatus("unavailable"); };
    node.addEventListener("webglcontextlost", unavailable, true);
    void import("./space-renderer").then((module) => {
      if (cancelled) return;
      const space = module.createSpace(node, { ...camera.current, distance: camera.current.distance * fitScale() }, (datum) => {
        const activeIndex = datum.ids.indexOf(latest.current.selectedId);
        latest.current.onSelect(datum.ids[(activeIndex + 1) % datum.ids.length]);
      }, (next) => {
        camera.current = { ...next, distance: next.distance / cameraScale.current };
        node.dataset.camera = `${camera.current.alpha},${camera.current.beta},${camera.current.distance}`;
      });
      runtime.current = space;
      const canRotate = matchMedia("(pointer: fine)").matches;
      setRotate(canRotate);
      space.chart.setOption({ grid3D: { viewControl: { rotateSensitivity: canRotate ? 1 : 0, minDistance: 150 * cameraScale.current, maxDistance: 340 * cameraScale.current } } });
      let previousWidth = node.clientWidth;
      observer = new ResizeObserver(() => {
        space.chart.resize();
        if (node.clientWidth !== previousWidth) {
          previousWidth = node.clientWidth;
          cameraScale.current = fitScale();
          space.chart.setOption({ grid3D: { viewControl: {
            ...camera.current,
            distance: camera.current.distance * fitScale(),
            minDistance: 150 * fitScale(),
            maxDistance: 340 * fitScale(),
          } } });
        }
      });
      observer.observe(node);
      setStatus("ready");
    }).catch(() => { if (!cancelled) setStatus("unavailable"); });
    return () => {
      cancelled = true;
      observer?.disconnect();
      node.removeEventListener("webglcontextlost", unavailable, true);
      runtime.current?.dispose();
      runtime.current = null;
    };
  }, []);

  useEffect(() => {
    if (status !== "ready" || !runtime.current) return;
    const space = runtime.current;
    void import("./space-renderer").then(({ spaceSeries }) => {
      if (space.chart.isDisposed()) return;
      space.chart.setOption({ series: spaceSeries(data, selectedId, space.colors) });
    });
  }, [data, selectedId, status]);

  function moveCamera(next: Partial<SpaceCamera>) {
    camera.current = { ...camera.current, ...next };
    const scale = cameraScale.current;
    runtime.current?.chart.setOption({ grid3D: { viewControl: { ...camera.current, distance: camera.current.distance * scale, minDistance: 150 * scale, maxDistance: 340 * scale } } });
    if (element.current) element.current.dataset.camera = `${camera.current.alpha},${camera.current.beta},${camera.current.distance}`;
  }

  return (
    <div className="article-space" data-status={status}>
      <div className="article-space__topline">
        <span><Box size={14} /> 관점 공간</span>
        <span>{measured.length}개 자료{anchor ? ` / 나의 편향 ${signed(anchor.x)}` : ""}</span>
      </div>
      <div className="article-space__viewport" data-rotate={rotate || undefined}>
        <div ref={element} className="article-space__canvas" role="img" aria-label={title} tabIndex={0} aria-describedby="space-instructions"
          onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home"].includes(event.key)) return;
            event.preventDefault();
            if (event.key === "Home") moveCamera(initialCamera());
            else if (event.key === "ArrowLeft" || event.key === "ArrowRight") moveCamera({ beta: camera.current.beta + (event.key === "ArrowLeft" ? -15 : 15) });
            else moveCamera({ alpha: clamp(camera.current.alpha + (event.key === "ArrowUp" ? 10 : -10), 5, 80) });
          }} />
        {status !== "ready" ? <div className="article-space__fallback" role="status"><Box size={24} /><strong>{status === "loading" ? "3D 관점 공간을 불러오는 중" : "이 브라우저에서는 3D를 표시할 수 없습니다."}</strong>{status === "unavailable" ? <span>아래 자료 목록에서 분석 수치를 확인할 수 있습니다.</span> : null}</div> : null}
        {status === "ready" && !measured.length ? <p className="article-space__empty">좌표를 표시할 측정 자료가 없습니다.</p> : null}
        {selected && selected.type !== "user" ? <dl className="article-space__readout" aria-label="선택한 자료의 공간 좌표">
          <div><dt>편향</dt><dd>{signed(selected.x)}</dd></div>
          <div><dt>과장</dt><dd>{selected.sensationalism === null ? "미측정" : Math.round(selected.sensationalism)}</dd></div>
          <div><dt>신뢰도</dt><dd>{Math.round(selected.confidence * 100)}%</dd></div>
        </dl> : null}
        <div className="article-space__tools" role="group" aria-label="3D 시점 조절">
          <Button variant="ghost" aria-label="마우스와 터치로 회전" aria-pressed={rotate} disabled={status !== "ready"} onClick={() => { setRotate(!rotate); runtime.current?.chart.setOption({ grid3D: { viewControl: { rotateSensitivity: rotate ? 0 : 1 } } }); }}><Move size={15} /></Button>
          <Button variant="ghost" aria-label="확대" disabled={status !== "ready"} onClick={() => moveCamera({ distance: clamp(camera.current.distance - 25, 150, 340) })}><Plus size={15} /></Button>
          <Button variant="ghost" aria-label="축소" disabled={status !== "ready"} onClick={() => moveCamera({ distance: clamp(camera.current.distance + 25, 150, 340) })}><Minus size={15} /></Button>
          <Button variant="ghost" aria-label="처음 시점으로" disabled={status !== "ready"} onClick={() => moveCamera(initialCamera())}><RotateCcw size={15} /></Button>
        </div>
        <nav className="article-space__navigation" aria-label="그래프 자료 선택">
          <span>{index < 0 ? "0" : index + 1} / {measured.length}</span>
          <Button variant="ghost" aria-label="이전 자료" disabled={index <= 0} onClick={() => measured[index - 1] && onSelect(measured[index - 1].id)}><ChevronLeft size={17} /></Button>
          <Button variant="ghost" aria-label="다음 자료" disabled={index >= measured.length - 1} onClick={() => measured[index + 1] && onSelect(measured[index + 1].id)}><ChevronRight size={17} /></Button>
        </nav>
      </div>
      <div className="article-space__caption"><span><i /> 자료 <i className="is-selected" /> 선택</span><p id="space-instructions">{rotate ? "드래그로 회전" : "회전 버튼으로 조작 활성화"} / 방향키로 시점 이동 / 숫자는 동일 좌표의 자료 수</p></div>
    </div>
  );
}

import { init, use as registerCharts, type EChartsType } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { TooltipComponent } from "echarts/components";
import { Scatter3DChart } from "echarts-gl/charts";
import { Grid3DComponent } from "echarts-gl/components";
import type { SpaceDatum } from "./field-model";

registerCharts([CanvasRenderer, TooltipComponent, Scatter3DChart as never, Grid3DComponent as never]);

export type SpaceCamera = { alpha: number; beta: number; distance: number; center: number[] };

const escapeHtml = (value: string) => value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");

export function spaceSeries(data: SpaceDatum[], selectedId: string, colors: { accent: string; selected: string; ink: string }) {
  const common = {
    type: "scatter3D", coordinateSystem: "cartesian3D", symbol: "circle",
    label: {
      show: true,
      position: "inside",
      distance: 0,
      fontSize: 11,
      formatter: (params: { data: SpaceDatum }) => params.data.ids.length > 1 ? String(params.data.ids.length) : "",
    },
    emphasis: { label: { show: false } },
  };
  return [
    {
      ...common, id: "articles", name: "자료",
      data: data.filter((datum) => !datum.ids.includes(selectedId)),
      symbolSize: (_: number[], params: { data: SpaceDatum }) => 18 + Math.min(12, Math.log2(params.data.ids.length) * 4),
      itemStyle: { color: colors.accent, opacity: .95, borderColor: colors.ink, borderWidth: 1 },
      label: { ...common.label, color: "#ffffff" },
    },
    {
      ...common, id: "selected", name: "선택한 자료",
      data: data.filter((datum) => datum.ids.includes(selectedId)),
      symbolSize: (_: number[], params: { data: SpaceDatum }) => 27 + Math.min(10, Math.log2(params.data.ids.length) * 4),
      itemStyle: { color: colors.selected, opacity: 1, borderColor: colors.ink, borderWidth: 2.5 },
      label: { ...common.label, color: colors.ink },
    },
  ];
}

export function createSpace(element: HTMLDivElement, camera: SpaceCamera, onSelect: (datum: SpaceDatum) => void, onCamera: (camera: SpaceCamera) => void) {
  const style = getComputedStyle(element);
  const token = (name: string) => style.getPropertyValue(name).trim();
  const colors = { accent: token("--peer-color-accent"), selected: token("--effica-butter"), ink: token("--peer-color-ink") };
  const background = token("--peer-color-canvas");
  const font = token("--peer-font-sans");
  const chart = init(element, undefined, { renderer: "canvas", devicePixelRatio: Math.min(devicePixelRatio, 2) });
  const axisLabel = { color: colors.ink, fontFamily: font, fontSize: 11, margin: 7 };
  const axis = {
    type: "value", min: 0, max: 100, interval: 25,
    axisLine: { lineStyle: { color: colors.ink, width: 1.5 } },
    axisTick: { show: false }, axisLabel,
    nameTextStyle: { color: colors.ink, fontFamily: font, fontSize: 12, fontWeight: "bold" },
    splitLine: { show: true, lineStyle: { color: colors.ink, width: 1, opacity: .23 } },
    splitArea: { show: true, areaStyle: { color: [background, "#fffdf7"] } },
  };
  try {
    chart.setOption({
      backgroundColor: background,
      textStyle: { fontFamily: font },
      animation: !matchMedia("(prefers-reduced-motion: reduce)").matches,
      animationDurationUpdate: 180,
      tooltip: {
        show: true, trigger: "item", confine: true,
        backgroundColor: colors.ink, borderWidth: 0, padding: [10, 12],
        extraCssText: "border-radius:0;box-shadow:none;max-width:260px;white-space:normal;word-break:keep-all;pointer-events:none;",
        textStyle: { color: "#ffffff", fontFamily: font, fontSize: 12 },
        formatter: (params: { data?: SpaceDatum }) => {
          const datum = params.data;
          if (!datum?.ids) return "";
          const [bias, confidence, sensationalism] = datum.value;
          const title = datum.ids.length > 1 ? `같은 좌표의 자료 ${datum.ids.length}개` : datum.name;
          return `<strong>${escapeHtml(title)}</strong><br/>편향 ${Math.round(bias)} / 과장 ${Math.round(sensationalism)} / 신뢰도 ${Math.round(confidence)}%${datum.ids.length > 1 ? "<br/>누르면 다음 자료를 선택합니다." : ""}`;
        },
      },
      grid3D: {
        boxWidth: 125, boxDepth: 95, boxHeight: 90,
        environment: background,
        axisPointer: { show: true, lineStyle: { color: colors.ink, width: 1.2, opacity: .7 }, label: { show: false } },
        light: { main: { intensity: .8, shadow: false }, ambient: { intensity: 1 } },
        viewControl: { ...camera, minDistance: 150, maxDistance: Math.max(340, camera.distance), minAlpha: 5, maxAlpha: 80, damping: .8, autoRotate: false, rotateSensitivity: 1, zoomSensitivity: 0, panSensitivity: 0 },
        postEffect: { enable: false }, temporalSuperSampling: { enable: true },
      },
      xAxis3D: { ...axis, min: -100, max: 100, interval: 50, name: "편향성", nameGap: 22, axisLabel: { ...axisLabel, formatter: (value: number) => `${value > 0 ? "+" : ""}${value}` } },
      yAxis3D: { ...axis, name: "분석 신뢰도", nameGap: 24, axisLabel: { ...axisLabel, formatter: (value: number) => `${value}%` } },
      zAxis3D: { ...axis, name: "과장성", nameGap: 18 },
      series: spaceSeries([], "", colors),
    } as Parameters<EChartsType["setOption"]>[0]);
  } catch (error) {
    chart.dispose();
    throw error;
  }
  let touchStart: { x: number; y: number; id: number } | null = null;
  chart.on("click", (params) => {
    const datum = params.data as SpaceDatum | undefined;
    if (datum?.ids) onSelect(datum);
  });
  chart.on("mouseup", (params) => {
    const native = (params.event as { event?: Event } | undefined)?.event;
    const datum = params.data as SpaceDatum | undefined;
    // GL forwards a touch tap as `touchend` instead of `click`.
    if (native?.type === "touchend" && touchStart && datum?.ids) {
      touchStart = null;
      onSelect(datum);
    }
  });
  chart.on("grid3dcamerachanged", (params) => {
    const next = params as unknown as Partial<SpaceCamera>;
    onCamera({ alpha: next.alpha ?? camera.alpha, beta: next.beta ?? camera.beta, distance: next.distance ?? camera.distance, center: next.center ?? camera.center });
  });
  // ECharts GL's picking reads mouse offsets from the native event. TouchEvent
  // has no offsets, so supply the equivalent chart-local coordinates before
  // ZRender receives it. Keep touch scrolling and rotation under its control.
  const touchCoordinates = (event: TouchEvent) => {
    const touch = event.changedTouches[0];
    if (!touch) return;
    if (event.type === "touchstart") touchStart = event.touches.length === 1 ? { x: touch.clientX, y: touch.clientY, id: touch.identifier } : null;
    if (touchStart && (touch.identifier !== touchStart.id || Math.hypot(touch.clientX - touchStart.x, touch.clientY - touchStart.y) > 8)) touchStart = null;
    if ("offsetX" in event) return;
    const rect = element.getBoundingClientRect();
    Object.defineProperties(event, {
      offsetX: { value: touch.clientX - rect.left },
      offsetY: { value: touch.clientY - rect.top },
    });
  };
  const touchEvents = ["touchstart", "touchmove", "touchend"] as const;
  touchEvents.forEach((name) => element.addEventListener(name, touchCoordinates, { capture: true, passive: true }));
  return { chart, colors, dispose() {
    touchEvents.forEach((name) => element.removeEventListener(name, touchCoordinates, true));
    chart.dispose();
  } };
}

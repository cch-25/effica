"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import * as THREE from "three";
import type { VisualizationPoint } from "@/lib/api/types";

type PerspectiveFieldProps = {
  points: VisualizationPoint[];
  selectedId: string;
  anchorId: string | undefined;
  title: string;
};

type GraphDomain = {
  biasExtent: number;
  sensationalismMax: number;
};

const subscribeStatic = () => () => undefined;
const getForcedFallback = () => new URLSearchParams(window.location.search).has("webgl-off");
const getServerFallback = () => false;

function useReducedMotion() {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return reduced;
}

function sensationalism(point: VisualizationPoint) {
  return point.type === "user" ? 0 : point.sensationalism ?? 0;
}

function getGraphDomain(points: VisualizationPoint[]): GraphDomain {
  const biasMaximum = Math.max(0, ...points.map((point) => Math.abs(point.x)));
  const sensationalismMaximum = Math.max(0, ...points.map(sensationalism));
  return {
    biasExtent: Math.min(100, Math.max(40, Math.ceil(biasMaximum / 10) * 10)),
    sensationalismMax: Math.min(100, Math.max(40, Math.ceil(sensationalismMaximum / 10) * 10)),
  };
}

function terrainPoints(points: VisualizationPoint[]) {
  const articles = points.filter((point) => point.type === "article");
  return articles.length ? articles : points.filter((point) => point.type !== "user");
}

function densityAt(
  bias: number,
  exaggeration: number,
  articles: VisualizationPoint[],
  domain: GraphDomain,
) {
  const biasBandwidth = domain.biasExtent * 0.24;
  const exaggerationBandwidth = domain.sensationalismMax * 0.22;
  return articles.reduce((sum, point) => {
    const biasDistance = (bias - point.x) / biasBandwidth;
    const exaggerationDistance = (exaggeration - sensationalism(point)) / exaggerationBandwidth;
    return sum + Math.exp(-0.5 * (biasDistance ** 2 + exaggerationDistance ** 2));
  }, 0);
}

function surfaceColor(normalizedDensity: number) {
  const blue = new THREE.Color("#7893e5");
  const mint = new THREE.Color("#9cc9aa");
  const butter = new THREE.Color("#f3d36f");
  const coral = new THREE.Color("#f08a73");
  if (normalizedDensity < 0.36) return blue.lerp(mint, normalizedDensity / 0.36);
  if (normalizedDensity < 0.72) return mint.lerp(butter, (normalizedDensity - 0.36) / 0.36);
  return butter.lerp(coral, (normalizedDensity - 0.72) / 0.28);
}

function surfaceHeight(density: number, maximum: number) {
  return 0.08 + (maximum > 0 ? density / maximum : 0) * 2.45;
}

function graphPosition(point: VisualizationPoint, domain: GraphDomain) {
  return new THREE.Vector3(
    THREE.MathUtils.clamp(point.x / domain.biasExtent, -1, 1) * 3.6,
    0,
    2.7 - (THREE.MathUtils.clamp(sensationalism(point), 0, domain.sensationalismMax) / domain.sensationalismMax) * 5.4,
  );
}

function disposeScene(scene: THREE.Scene) {
  scene.traverse((object) => {
    const renderable = object as THREE.Object3D & {
      geometry?: THREE.BufferGeometry;
      material?: THREE.Material | THREE.Material[];
    };
    renderable.geometry?.dispose();
    if (!renderable.material) return;
    (Array.isArray(renderable.material) ? renderable.material : [renderable.material]).forEach((item) => {
      const mapped = item as THREE.Material & { map?: THREE.Texture | null };
      mapped.map?.dispose();
      item.dispose();
    });
  });
}

function createSelectionLabel(label: string) {
  const labelCanvas = document.createElement("canvas");
  labelCanvas.width = 256;
  labelCanvas.height = 84;
  const context = labelCanvas.getContext("2d");
  if (!context) return null;
  context.fillStyle = "#11110f";
  context.fillRect(10, 10, 236, 64);
  context.fillStyle = "#ffffff";
  context.font = "700 30px ui-monospace, SFMono-Regular, Menlo, monospace";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(label, 128, 43);
  const texture = new THREE.CanvasTexture(labelCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
  sprite.scale.set(1.15, 0.38, 1);
  sprite.renderOrder = 10;
  return sprite;
}

function addLine(
  parent: THREE.Object3D,
  points: THREE.Vector3[],
  color = "#555550",
  opacity = 0.75,
) {
  const line = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(points),
    new THREE.LineBasicMaterial({ color, transparent: opacity < 1, opacity }),
  );
  parent.add(line);
}

function TerrainCanvas({
  points,
  selectedId,
  anchorId,
  onUnavailable,
  reducedMotion,
}: Pick<PerspectiveFieldProps, "points" | "selectedId" | "anchorId"> & {
  onUnavailable: () => void;
  reducedMotion: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (navigator.userAgent.toLowerCase().includes("jsdom")) {
      onUnavailable();
      return;
    }

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: "high-performance" });
    } catch {
      onUnavailable();
      return;
    }

    renderer.setClearColor("#f5f5f1", 1);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.8));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
    camera.position.set(6.15, 5.25, 7.7);
    camera.lookAt(0, 0.75, 0);

    const world = new THREE.Group();
    world.scale.setScalar(reducedMotion ? 1 : 0.92);
    scene.add(world);

    scene.add(new THREE.HemisphereLight("#ffffff", "#9a9a90", 3.2));
    const keyLight = new THREE.DirectionalLight("#ffffff", 4.2);
    keyLight.position.set(-4, 8, 6);
    scene.add(keyLight);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(7.65, 5.75),
      new THREE.MeshStandardMaterial({ color: "#e9e9e4", roughness: 0.92, metalness: 0 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.035;
    world.add(floor);

    const domain = getGraphDomain(points);
    const articles = terrainPoints(points);
    const xSegments = 42;
    const zSegments = 32;
    const surfaceGeometry = new THREE.PlaneGeometry(7.2, 5.4, xSegments, zSegments);
    const positions = surfaceGeometry.attributes.position;
    const densities: number[] = [];

    for (let index = 0; index < positions.count; index += 1) {
      const worldX = positions.getX(index);
      const worldZ = -positions.getY(index);
      const bias = (worldX / 3.6) * domain.biasExtent;
      const exaggeration = ((2.7 - worldZ) / 5.4) * domain.sensationalismMax;
      densities.push(densityAt(bias, exaggeration, articles, domain));
    }

    const maximumDensity = Math.max(0, ...densities);
    const colors: number[] = [];
    densities.forEach((density, index) => {
      const normalized = maximumDensity > 0 ? density / maximumDensity : 0;
      positions.setZ(index, surfaceHeight(density, maximumDensity));
      const color = surfaceColor(normalized);
      colors.push(color.r, color.g, color.b);
    });
    surfaceGeometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    surfaceGeometry.computeVertexNormals();

    const surface = new THREE.Mesh(
      surfaceGeometry,
      new THREE.MeshPhysicalMaterial({
        vertexColors: true,
        roughness: 0.46,
        metalness: 0.02,
        clearcoat: 0.2,
        side: THREE.DoubleSide,
      }),
    );
    surface.rotation.x = -Math.PI / 2;
    world.add(surface);

    const wireframe = new THREE.Mesh(
      surfaceGeometry.clone(),
      new THREE.MeshBasicMaterial({ color: "#171714", wireframe: true, transparent: true, opacity: 0.42 }),
    );
    wireframe.rotation.x = -Math.PI / 2;
    wireframe.position.y = 0.012;
    world.add(wireframe);

    addLine(world, [new THREE.Vector3(-3.82, 0.01, 2.88), new THREE.Vector3(3.82, 0.01, 2.88)], "#11110f", 0.9);
    addLine(world, [new THREE.Vector3(-3.82, 0.01, 2.88), new THREE.Vector3(-3.82, 0.01, -2.88)], "#11110f", 0.9);
    addLine(world, [new THREE.Vector3(0, 0.015, 2.88), new THREE.Vector3(0, 0.015, -2.88)], "#555550", 0.6);

    const selected = points.find((point) => point.id === selectedId) ?? points[0];
    const selectedIndex = points.findIndex((point) => point.id === selected.id);
    const selectedPosition = graphPosition(selected, domain);
    const selectedDensity = densityAt(selected.x, sensationalism(selected), articles, domain);
    const selectedHeight = surfaceHeight(selectedDensity, maximumDensity);
    const anchor = points.find((point) => point.id === anchorId);
    const anchorPosition = anchor ? graphPosition(anchor, domain) : null;
    const anchorDensity = anchor ? densityAt(anchor.x, sensationalism(anchor), articles, domain) : 0;
    const anchorHeight = anchor ? surfaceHeight(anchorDensity, maximumDensity) : 0;

    if (anchor && anchorPosition && anchor.id !== selected.id) {
      addLine(world, [
        new THREE.Vector3(anchorPosition.x, anchorHeight + 0.08, anchorPosition.z),
        new THREE.Vector3(selectedPosition.x, selectedHeight + 0.08, selectedPosition.z),
      ], "#d84235", 0.9);
      const anchorMarker = new THREE.Mesh(
        new THREE.SphereGeometry(0.14, 24, 16),
        new THREE.MeshPhysicalMaterial({ color: "#d84235", roughness: 0.35, clearcoat: 0.45 }),
      );
      anchorMarker.position.set(anchorPosition.x, anchorHeight + 0.14, anchorPosition.z);
      world.add(anchorMarker);
    }

    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(0.17, 28, 18),
      new THREE.MeshPhysicalMaterial({ color: "#11110f", roughness: 0.28, clearcoat: 0.65 }),
    );
    marker.position.set(selectedPosition.x, selectedHeight + 0.15, selectedPosition.z);
    world.add(marker);

    addLine(world, [
      new THREE.Vector3(selectedPosition.x, selectedHeight + 0.18, selectedPosition.z),
      new THREE.Vector3(selectedPosition.x, selectedHeight + 0.68, selectedPosition.z),
    ], "#11110f", 1);

    const selectedLabel = createSelectionLabel(`선택 ${String(selectedIndex + 1).padStart(2, "0")}`);
    if (selectedLabel) {
      selectedLabel.position.set(selectedPosition.x, selectedHeight + 0.88, selectedPosition.z);
      world.add(selectedLabel);
    }

    const resize = () => {
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.render(scene, camera);
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    resize();

    const timer = new THREE.Timer();
    timer.connect(document);
    let animationFrame = 0;
    const renderFrame = (timestamp: number) => {
      timer.update(timestamp);
      const elapsed = timer.getElapsed();
      const entrance = Math.min(1, elapsed / 0.9);
      const entranceEase = 1 - Math.pow(1 - entrance, 3);
      world.scale.setScalar(0.92 + entranceEase * 0.08);
      marker.scale.setScalar(1 + Math.sin(elapsed * 2.2) * 0.045);
      renderer.render(scene, camera);
      animationFrame = window.requestAnimationFrame(renderFrame);
    };

    if (reducedMotion) renderer.render(scene, camera);
    else animationFrame = window.requestAnimationFrame(renderFrame);

    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      timer.dispose();
      disposeScene(scene);
      renderer.dispose();
    };
  }, [anchorId, onUnavailable, points, reducedMotion, selectedId]);

  return <canvas ref={canvasRef} className="perspective-field__canvas" aria-hidden="true" />;
}

function fallbackColor(normalizedDensity: number) {
  if (normalizedDensity > 0.74) return "#f08a73";
  if (normalizedDensity > 0.48) return "#f3d36f";
  if (normalizedDensity > 0.22) return "#9cc9aa";
  return "#7893e5";
}

function PerspectiveFallback({ points, title, selectedId, anchorId }: Pick<PerspectiveFieldProps, "points" | "title" | "selectedId" | "anchorId">) {
  const domain = getGraphDomain(points);
  const articles = terrainPoints(points);
  const columns = 16;
  const rows = 10;
  const samples = Array.from({ length: columns * rows }, (_, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    const bias = -domain.biasExtent + (column / (columns - 1)) * domain.biasExtent * 2;
    const exaggeration = domain.sensationalismMax - (row / (rows - 1)) * domain.sensationalismMax;
    return { column, row, density: densityAt(bias, exaggeration, articles, domain) };
  });
  const maximumDensity = Math.max(0, ...samples.map((sample) => sample.density));
  const selected = points.find((point) => point.id === selectedId) ?? points[0];
  const selectedIndex = points.findIndex((point) => point.id === selected.id);
  const selectedX = 76 + ((selected.x + domain.biasExtent) / (domain.biasExtent * 2)) * 568;
  const selectedY = 424 - (sensationalism(selected) / domain.sensationalismMax) * 350;
  const anchor = points.find((point) => point.id === anchorId);
  const anchorX = anchor ? 76 + ((anchor.x + domain.biasExtent) / (domain.biasExtent * 2)) * 568 : 0;
  const anchorY = anchor ? 424 - (sensationalism(anchor) / domain.sensationalismMax) * 350 : 0;

  return (
    <svg className="perspective-field__fallback" viewBox="0 0 720 520" role="img" aria-label={title}>
      <title>{title}</title>
      <desc>가로축은 편향성, 세로축은 과장성이며 색이 따뜻할수록 해당 구간에 분석된 기사가 많이 모여 있습니다.</desc>
      <rect width="720" height="520" fill="#f5f5f1" />
      {samples.map(({ column, row, density }) => (
        <rect
          key={`${column}-${row}`}
          x={76 + column * (568 / columns)}
          y={74 + row * (350 / rows)}
          width={568 / columns + 1}
          height={350 / rows + 1}
          fill={fallbackColor(maximumDensity ? density / maximumDensity : 0)}
          stroke="#11110f"
          strokeOpacity=".28"
        />
      ))}
      <line x1="360" y1="74" x2="360" y2="424" stroke="#11110f" strokeWidth="2" />
      {anchor && anchor.id !== selected.id ? <><line x1={anchorX} y1={anchorY} x2={selectedX} y2={selectedY} stroke="#d84235" strokeWidth="3" /><circle cx={anchorX} cy={anchorY} r="9" fill="#d84235" stroke="#ffffff" strokeWidth="3" /></> : null}
      <circle cx={selectedX} cy={selectedY} r="10" fill="#11110f" stroke="#ffffff" strokeWidth="4" />
      <rect x={selectedX - 34} y={selectedY - 46} width="68" height="28" fill="#11110f" />
      <text x={selectedX} y={selectedY - 27} fill="#ffffff" fontSize="12" fontWeight="700" textAnchor="middle">선택 {String(selectedIndex + 1).padStart(2, "0")}</text>
    </svg>
  );
}

export function PerspectiveField(props: PerspectiveFieldProps) {
  const reducedMotion = useReducedMotion();
  const [webglUnavailable, setWebglUnavailable] = useState(false);
  const forcedFallback = useSyncExternalStore(subscribeStatic, getForcedFallback, getServerFallback);
  const handleUnavailable = useCallback(() => setWebglUnavailable(true), []);
  const domain = getGraphDomain(props.points);
  const articleCount = terrainPoints(props.points).length;

  return (
    <div className="perspective-field">
      <div className="perspective-field__hud" aria-hidden="true">
        <span className="perspective-field__title"><strong>{props.anchorId ? "나의 기준 기사 지형" : "기사 분포 지형"}</strong><small>가로 = 편향 · 안쪽 = 과장성 · 언덕 = 기사 밀집도</small></span>
        <span>기사 {articleCount}개 기준</span>
      </div>
      {webglUnavailable || forcedFallback ? (
        <PerspectiveFallback points={props.points} title={props.title} selectedId={props.selectedId} anchorId={props.anchorId} />
      ) : (
        <TerrainCanvas points={props.points} selectedId={props.selectedId} anchorId={props.anchorId} reducedMotion={reducedMotion} onUnavailable={handleUnavailable} />
      )}
      <div className="perspective-field__axes" aria-hidden="true">
        <span>← 좌편향 −{domain.biasExtent}</span>
        <span>중립 0</span>
        <span>+{domain.biasExtent} 우편향 →</span>
      </div>
      <div className="perspective-field__depth" aria-hidden="true">과장성 · 낮음 0 → 높음 {domain.sensationalismMax}</div>
    </div>
  );
}

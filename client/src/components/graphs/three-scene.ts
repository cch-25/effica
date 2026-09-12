import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { graphPosition, graphValue, type GraphAxes, type GraphPoint, type GraphRegion, type GraphView } from "./graph-model";
import { createGraphStage } from "./graph-stage";

export function createGraphScene(host: HTMLDivElement, axes: GraphAxes, onPick: (ids: string[]) => void, onOrbit: () => void, regions: GraphRegion[] = []) {
  const theme = getComputedStyle(host);
  const accent = new THREE.Color(theme.getPropertyValue("--peer-color-accent").trim()).getHex();
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0xffffff, 0);
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const stage = createGraphStage(renderer, scene);
  const camera = new THREE.OrthographicCamera(-3, 3, 2, -2, .1, 100);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enablePan = false;
  controls.enableZoom = false;
  controls.minPolarAngle = .001;
  controls.maxPolarAngle = Math.PI / 2;
  controls.minAzimuthAngle = -Math.PI / 2;
  controls.maxAzimuthAngle = Math.PI / 2;
  controls.rotateSpeed = .55;
  controls.enabled = false;
  renderer.domElement.style.touchAction = "pan-y";
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const overlay = document.createElement("div");
  overlay.className = "graph-3d__labels";
  overlay.setAttribute("aria-hidden", "true");
  host.appendChild(overlay);
  const tooltip = document.createElement("div");
  tooltip.className = "graph-3d__tooltip";
  tooltip.hidden = true;
  host.appendChild(tooltip);
  const axisLabels: { element: HTMLSpanElement; position: THREE.Vector3; axis: number; offset: [number, number] }[] = [];
  const dimensions = [1.2, .825, .825];
  const geometries: THREE.BufferGeometry[] = [];
  const materials: THREE.Material[] = [];
  function lines(points: number[][], color: number, opacity = 1, dashed = false) {
    const geometry = new THREE.BufferGeometry().setFromPoints(points.map((p) => new THREE.Vector3(...p)));
    const material = dashed
      ? new THREE.LineDashedMaterial({ color, transparent: true, opacity, dashSize: .045, gapSize: .035 })
      : new THREE.LineBasicMaterial({ color, transparent: true, opacity });
    geometries.push(geometry); materials.push(material);
    const line = new THREE.LineSegments(geometry, material);
    line.computeLineDistances();
    return line;
  }
  const grid: number[][] = [];
  for (let step = 0; step <= 4; step++) {
    const x = -1.2 + step * .6;
    const y = -.825 + step * .4125;
    const z = -.825 + step * .4125;
    grid.push([x, -.825, -.825], [x, -.825, .825], [-1.2, -.825, z], [1.2, -.825, z]);
    grid.push([x, -.825, -.825], [x, .825, -.825], [-1.2, y, -.825], [1.2, y, -.825]);
  }
  scene.add(lines(grid, 0x687080, .19));
  const sideGrid = lines(Array.from({ length: 5 }, (_, i) => [
    [-1.2, -.825 + i * .4125, -.825], [-1.2, -.825 + i * .4125, .825],
    [-1.2, -.825, -.825 + i * .4125], [-1.2, .825, -.825 + i * .4125],
  ]).flat(), 0x687080, .19);
  scene.add(sideGrid);
  if (regions.length) scene.add(lines([
    [-1.2, 0, 0], [1.2, 0, 0], [0, -.825, 0], [0, .825, 0], [0, 0, -.825], [0, 0, .825],
  ], 0x687080, .45, true));
  const regionLabels = regions.map(region => {
    const element = document.createElement("span");
    element.className = "graph-3d__region";
    element.textContent = region.label;
    overlay.appendChild(element);
    return { element, position: new THREE.Vector3(...graphPosition(region.values, axes)) };
  });
  // Three outer rulers stay separate from the selected point's projection guides.
  axes.forEach((axis, index) => {
    const a = [-1.2, -.825, .825];
    const b = [...a];
    b[index] = index === 2 ? -.825 : dimensions[index];
    [0, .5, 1].forEach((fraction) => {
      if (fraction === 0 && index === 2 && !axis.showPoles) return;
      const position = new THREE.Vector3(...a);
      position.setComponent(index, index === 2 ? .825 - fraction * 1.65 : -dimensions[index] + fraction * dimensions[index] * 2);
      const label = document.createElement("span");
      const value = axis.min + (axis.reversed ? 1 - fraction : fraction) * (axis.max - axis.min);
      const pole = axis.showPoles && fraction !== .5;
      label.className = pole ? "graph-3d__pole" : "graph-3d__tick";
      label.textContent = pole ? value === axis.min ? axis.low : axis.high : graphValue(value, axis);
      overlay.appendChild(label);
      axisLabels.push({ element: label, position, axis: index, offset: index === 0 ? [0, 15] : index === 2 && pole ? [20, 12] : [pole ? -34 : -18, 0] });
    });
    const position = new THREE.Vector3(...b);
    const label = document.createElement("span");
    label.className = "graph-3d__axis-name";
    label.textContent = axis.label;
    overlay.appendChild(label);
    axisLabels.push({ element: label, position, axis: index, offset: index === 0 ? [0, 35] : [0, -27] });
  });
  const sphere = new THREE.SphereGeometry(1, 32, 24);
  const ink = new THREE.MeshPhysicalMaterial({ color: 0x555b65, roughness: .18, metalness: .8, clearcoat: 1 });
  const selectedMaterial = new THREE.MeshPhysicalMaterial({ color: accent, roughness: .17, metalness: .55, clearcoat: 1, clearcoatRoughness: .1 });
  const haloGeometry = new THREE.TorusGeometry(1, .035, 8, 64);
  const haloMaterial = new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: .75, depthTest: false });
  geometries.push(sphere, haloGeometry); materials.push(ink, selectedMaterial, haloMaterial);
  const halo = new THREE.Mesh(haloGeometry, haloMaterial);
  halo.renderOrder = 3; halo.visible = false; scene.add(halo);
  const guide = lines(Array.from({ length: 6 }, () => [0, 0, 0]), accent, .65, true);
  guide.visible = false; scene.add(guide);
  const projections = new THREE.Group(); scene.add(projections);
  const sliceMaterial = new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: .055, side: THREE.DoubleSide, depthWrite: false });
  const sliceLineMaterial = new THREE.LineBasicMaterial({ color: accent, transparent: true, opacity: .22 });
  materials.push(sliceMaterial, sliceLineMaterial);
  const slices = [[1.65, 1.65], [2.4, 1.65], [2.4, 1.65]].map(([w, h], index) => {
    const geometry = new THREE.PlaneGeometry(w, h);
    const edgeGeometry = new THREE.EdgesGeometry(geometry);
    geometries.push(geometry, edgeGeometry);
    const plane = new THREE.Mesh(geometry, sliceMaterial);
    plane.add(new THREE.LineSegments(edgeGeometry, sliceLineMaterial));
    if (index === 0) plane.rotation.y = Math.PI / 2;
    if (index === 1) plane.rotation.x = -Math.PI / 2;
    projections.add(plane); return plane;
  });
  const projectionGeometry = new THREE.RingGeometry(.033, .05, 32);
  const projectionMaterial = new THREE.MeshBasicMaterial({ color: accent, side: THREE.DoubleSide, depthTest: false });
  geometries.push(projectionGeometry); materials.push(projectionMaterial);
  const projectionDots = Array.from({ length: 3 }, (_, index) => {
    const dot = new THREE.Mesh(projectionGeometry, projectionMaterial);
    if (index === 0) dot.rotation.y = Math.PI / 2;
    if (index === 1) dot.rotation.x = -Math.PI / 2;
    dot.renderOrder = 2; projections.add(dot); return dot;
  });
  let showProjections = true;
  let selectionFrame = 0;
  let selectionGlow = 1;
  let activePosition: THREE.Vector3 | undefined;
  const profile = axes.every(axis => axis.min === -100);
  let points: { data: GraphPoint; mesh: THREE.Mesh; label: HTMLSpanElement | null }[] = [];
  let selectedId = "";
  let hovered: GraphPoint | undefined;
  let width = 1, height = 1, frame = 0, disposed = false;
  let view: GraphView = "space";
  const project = (position: THREE.Vector3) => {
    const vector = position.clone().project(camera);
    return { x: (vector.x + 1) * width / 2, y: (1 - vector.y) * height / 2 };
  };
  function place(element: HTMLElement, position: THREE.Vector3, offset = [0, 0]) {
    const p = project(position);
    p.x += offset[0]; p.y += offset[1];
    if (element.classList.contains("graph-3d__pole") && p.x > -20 && p.x < width + 20) {
      const inset = Math.max(20, element.offsetWidth / 2 + 4);
      p.x = Math.max(inset, Math.min(width - inset, p.x));
    }
    element.style.left = `${p.x}px`; element.style.top = `${p.y}px`;
    element.style.visibility = p.x < 20 || p.x > width - 20 || p.y < 14 || p.y > height - 14 ? "hidden" : "visible";
    return p;
  }
  function render() {
    if (disposed) return;
    halo.quaternion.copy(camera.quaternion);
    const pixel = (camera.top - camera.bottom) / height / camera.zoom;
    const selectedRadius = profile ? 13 : 8.5;
    const pointRadius = Math.max(3.5, 6 - Math.log2(Math.max(1, points.length / 24)) * .45);
    halo.scale.setScalar(pixel * (selectedRadius + 5 + (1 - selectionGlow) * 8));
    haloMaterial.opacity = .25 + selectionGlow * .5;
    points.forEach(({ data, mesh }) => mesh.scale.setScalar(pixel * (data.ids.includes(selectedId) ? selectedRadius : data === hovered ? 8 : pointRadius)));
    stage.setPlanar(view !== "space");
    sideGrid.visible = view === "side";
    projections.visible = Boolean(activePosition) && showProjections;
    slices.forEach((slice, i) => { slice.visible = view === "space" || (view === "front" && i === 2) || (view === "top" && i === 1) || (view === "side" && i === 0); });
    sliceMaterial.opacity = (view === "space" ? .055 : .025) * selectionGlow;
    renderer.render(scene, camera);
    const occupied: { left: number; right: number; top: number; bottom: number }[] = [];
    // Compute collision boxes in graph coordinates. Off-screen layout and page
    // scrolling must not affect whether a label is displayed.
    const labelPriority = (element: HTMLElement) => element.classList.contains("graph-3d__pole") ? 2 : element.classList.contains("graph-3d__axis-name") ? 1 : 0;
    for (const label of [...axisLabels].sort((a, b) => labelPriority(b.element) - labelPriority(a.element))) {
      label.element.hidden = (view === "front" && label.axis === 2) || (view === "top" && label.axis === 1) || (view === "side" && label.axis === 0);
      const position = label.position.clone();
      if (view === "space" && label.axis === 0) { position.y = -1.02; position.z = .98; }
      // In side view, the depth ruler becomes the horizontal axis.
      const offset = view === "side" && label.axis === 2 ? [0, label.element.classList.contains("graph-3d__axis-name") ? 35 : 15]
        : view === "space" && label.axis === 0 ? [0, label.element.classList.contains("graph-3d__axis-name") ? 32 : 13] : label.offset;
      let p = place(label.element, position, offset);
      if (!label.element.hidden && label.element.style.visibility !== "hidden") {
        const labelWidth = label.element.offsetWidth || (label.element.textContent?.length ?? 1) * 7;
        const bounds = () => ({ left: p.x - labelWidth / 2, right: p.x + labelWidth / 2, top: p.y - 7, bottom: p.y + 7 });
        let rect = bounds();
        const collides = () => occupied.some(r => r.left - 4 < rect.right && r.right + 4 > rect.left && r.top - 2 < rect.bottom && r.bottom + 2 > rect.top);
        // Semantic endpoints must remain readable when the narrow layout
        // brings the rulers together. Move locally before hiding a pole.
        if (label.element.classList.contains("graph-3d__pole") && collides()) {
          for (const shift of [18, -18, 36, -36]) {
            p = place(label.element, position, [offset[0], offset[1] + shift]);
            rect = bounds();
            if (label.element.style.visibility !== "hidden" && !collides()) break;
          }
        }
        if (collides()) label.element.style.visibility = "hidden";
        else occupied.push(rect);
      }
    }
    for (const label of regionLabels) {
      label.element.hidden = view === "top" || view === "side";
      place(label.element, label.position);
      const p = project(label.position);
      const labelWidth = label.element.offsetWidth;
      const rect = { left: p.x - labelWidth / 2, right: p.x + labelWidth / 2, top: p.y - 9, bottom: p.y + 9 };
      const selected = activePosition ? project(activePosition) : null;
      if (occupied.some(r => r.left - 4 < rect.right && r.right + 4 > rect.left && r.top - 4 < rect.bottom && r.bottom + 4 > rect.top)
        || (selected && selected.x > rect.left - 22 && selected.x < rect.right + 22 && selected.y > rect.top - 22 && selected.y < rect.bottom + 22)) label.element.style.visibility = "hidden";
      else if (!label.element.hidden) occupied.push(rect);
    }
    points.forEach(({ mesh, label }) => { if (label) place(label, mesh.position); });
    host.dataset.camera = `${camera.position.toArray().map((v) => v.toFixed(3)).join(",")},${camera.zoom.toFixed(2)}`;
  }
  function resize() {
    width = Math.max(1, host.clientWidth); height = Math.max(1, host.clientHeight);
    const aspect = width / height;
    const span = Math.max(3.5, 4.35 / aspect);
    camera.left = -span * aspect / 2; camera.right = span * aspect / 2;
    camera.top = span / 2; camera.bottom = -span / 2;
    camera.updateProjectionMatrix(); renderer.setSize(width, height); render();
  }
  function setView(next: GraphView, animate = true) {
    cancelAnimationFrame(frame);
    view = next; tooltip.hidden = true;
    const destination = new THREE.Vector3(...(next === "front" ? [0, 0, 6] : next === "top" ? [0, 6, .006] : next === "side" ? [6, 0, 0] : [2.6, 1.9, 5.4]));
    const start = camera.position.clone(), startZoom = camera.zoom;
    const started = performance.now();
    function step(now: number) {
      const t = !animate || reducedMotion.matches ? 1 : Math.min(1, (now - started) / 620);
      const ease = t * t * (3 - 2 * t);
      camera.position.lerpVectors(start, destination, ease);
      camera.zoom = startZoom + (1 - startZoom) * ease;
      camera.lookAt(0, 0, 0); camera.updateProjectionMatrix(); render();
      if (t < 1) frame = requestAnimationFrame(step);
      else controls.update();
    }
    step(started);
  }
  controls.addEventListener("change", render);
  const orbitStart = () => { cancelAnimationFrame(frame); view = "space"; tooltip.hidden = true; onOrbit(); };
  controls.addEventListener("start", orbitStart);
  const observer = new ResizeObserver(resize); observer.observe(host);
  let down: { x: number; y: number; id: number } | undefined;
  let dragged = false;
  function pick(event: PointerEvent) {
    const rect = host.getBoundingClientRect();
    const x = event.clientX - rect.left, y = event.clientY - rect.top;
    return points.map((point) => {
      const p = project(point.mesh.position);
      return { point, distance: Math.hypot(x - p.x, y - p.y), depth: point.mesh.position.distanceTo(camera.position) };
    }).filter((p) => p.distance < 15).sort((a, b) => a.distance - b.distance || a.depth - b.depth)[0]?.point;
  }
  const pointerDown = (event: PointerEvent) => { down = { x: event.clientX, y: event.clientY, id: event.pointerId }; dragged = false; };
  const pointerMove = (event: PointerEvent) => {
    if (down && Math.hypot(event.clientX - down.x, event.clientY - down.y) > 6) dragged = true;
    if (event.buttons || event.pointerType === "touch") { tooltip.hidden = true; return; }
    const hit = pick(event);
    hovered = hit?.data;
    renderer.domElement.style.cursor = hit ? "pointer" : controls.enabled ? "grab" : "default";
    tooltip.hidden = !hit;
    if (hit) {
      tooltip.replaceChildren();
      const title = document.createElement("strong");
      title.textContent = hit.data.label;
      const values = document.createElement("span");
      values.textContent = axes.map((axis, i) => `${axis.label} ${graphValue(hit.data.values[i], axis)}`).join(" / ");
      tooltip.append(title, values);
      if (hit.data.ids.length > 1) { const hint = document.createElement("span"); hint.textContent = `같은 좌표 ${hit.data.ids.length}개 / 다시 누르면 다음 자료`; tooltip.append(hint); }
      const p = project(hit.mesh.position);
      tooltip.style.left = `${Math.max(8, Math.min(width - Math.min(260, width - 16) - 8, p.x + 16))}px`;
      tooltip.style.top = `${Math.max(8, Math.min(height - tooltip.offsetHeight - 8, p.y - tooltip.offsetHeight - 12))}px`;
    }
    render();
  };
  const pointerUp = (event: PointerEvent) => {
    if (down?.id === event.pointerId && !dragged && Math.hypot(event.clientX - down.x, event.clientY - down.y) < 6) {
      const hit = pick(event); if (hit) onPick(hit.data.ids);
    }
    down = undefined;
  };
  const pointerLeave = () => { tooltip.hidden = true; hovered = undefined; render(); };
  const pointerCancel = () => { down = undefined; pointerLeave(); };
  host.addEventListener("pointerdown", pointerDown, true);
  host.addEventListener("pointermove", pointerMove);
  host.addEventListener("pointerup", pointerUp);
  host.addEventListener("pointerleave", pointerLeave);
  host.addEventListener("pointercancel", pointerCancel);
  setView("space", false); resize();
  return {
    setView,
    setProjections(visible: boolean) { showProjections = visible; render(); },
    setInteractive(enabled: boolean) { controls.enabled = enabled; renderer.domElement.style.touchAction = enabled ? "none" : "pan-y"; },
    zoom(amount: number) { cancelAnimationFrame(frame); camera.zoom = THREE.MathUtils.clamp(camera.zoom + amount, .8, 1.65); camera.updateProjectionMatrix(); render(); },
    rotate(horizontal: number, vertical: number) {
      cancelAnimationFrame(frame); view = "space"; onOrbit();
      const spherical = new THREE.Spherical().setFromVector3(camera.position);
      spherical.theta = THREE.MathUtils.clamp(spherical.theta + horizontal, -Math.PI / 2, Math.PI / 2);
      spherical.phi = THREE.MathUtils.clamp(spherical.phi + vertical, .15, Math.PI / 2);
      camera.position.setFromSpherical(spherical); controls.update(); render();
    },
    update(data: GraphPoint[], selected: string) {
      const changed = selected !== selectedId;
      selectedId = selected; tooltip.hidden = true;
      points.forEach(({ mesh, label }) => { scene.remove(mesh); label?.remove(); });
      points = data.map((datum) => {
        const mesh = new THREE.Mesh(sphere, datum.ids.includes(selected) ? selectedMaterial : ink);
        mesh.position.set(...graphPosition(datum.values, axes));
        // Uncalibrated cast shadows can look like extra observations. Only the
        // measuring stage casts shadows; data uses explicit projection markers.
        scene.add(mesh);
        let label: HTMLSpanElement | null = null;
        if (datum.ids.length > 1) {
          label = document.createElement("span"); label.className = "graph-3d__count"; label.textContent = String(datum.ids.length); overlay.appendChild(label);
        }
        return { data: datum, mesh, label };
      });
      const active = points.find((point) => point.data.ids.includes(selected));
      activePosition = active?.mesh.position;
      halo.visible = guide.visible = Boolean(active);
      if (active) {
        const p = active.mesh.position;
        halo.position.copy(p);
        slices[0].position.x = p.x; slices[1].position.y = p.y; slices[2].position.z = p.z;
        projectionDots[0].position.set(-1.2, p.y, p.z);
        projectionDots[1].position.set(p.x, -.82, p.z);
        projectionDots[2].position.set(p.x, p.y, -.823);
        const values = [p.x, p.y, p.z, p.x, -.825, p.z, p.x, -.825, p.z, p.x, -.825, .825, p.x, -.825, p.z, -1.2, -.825, p.z, p.x, p.y, p.z, -1.2, p.y, p.z, -1.2, p.y, p.z, -1.2, p.y, .825];
        guide.geometry.setAttribute("position", new THREE.Float32BufferAttribute(values, 3));
        guide.geometry.computeBoundingSphere(); guide.computeLineDistances();
      }
      if (changed) {
        cancelAnimationFrame(selectionFrame);
        const started = performance.now();
        const reveal = (now: number) => {
          selectionGlow = reducedMotion.matches ? 1 : Math.min(1, (now - started) / 460);
          render();
          if (selectionGlow < 1 && !disposed) selectionFrame = requestAnimationFrame(reveal);
        };
        reveal(started);
      }
      render();
    },
    dispose() {
      disposed = true; cancelAnimationFrame(frame); cancelAnimationFrame(selectionFrame); observer.disconnect(); controls.dispose();
      host.removeEventListener("pointerdown", pointerDown, true); host.removeEventListener("pointermove", pointerMove);
      host.removeEventListener("pointerup", pointerUp); host.removeEventListener("pointerleave", pointerLeave); host.removeEventListener("pointercancel", pointerCancel);
      geometries.forEach((geometry) => geometry.dispose()); materials.forEach((material) => material.dispose());
      stage.dispose(); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); overlay.remove(); tooltip.remove();
    },
  };
}

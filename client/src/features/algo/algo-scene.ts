import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { SIGNALS, rankingExample, weightedScore, type AlgorithmState } from "./algo-model";

const INK = 0x24352e;
const GREEN = 0x27835a;
const WHITE = 0xfafbf7;
type Moving = { object: THREE.Object3D; position: THREE.Vector3; scale: THREE.Vector3 };

export function createAlgorithmScene(host: HTMLDivElement, initial: AlgorithmState) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.setClearColor(0xf0f3ee);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.setAttribute("aria-hidden", "true");
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-6, 6, 3, -3, .1, 80);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enabled = false;
  controls.enablePan = false;
  controls.enableZoom = false;
  controls.minPolarAngle = .25;
  controls.maxPolarAngle = Math.PI / 2;
  controls.minAzimuthAngle = -.7;
  controls.maxAzimuthAngle = .7;
  renderer.domElement.style.touchAction = "pan-y";
  scene.add(new THREE.HemisphereLight(0xffffff, 0xa7b4a4, 1.5));
  const light = new THREE.DirectionalLight(0xffffff, 2);
  light.position.set(-3, 8, 8);
  light.castShadow = true;
  light.shadow.mapSize.set(1024, 1024);
  Object.assign(light.shadow.camera, { left: -8, right: 8, top: 7, bottom: -7 });
  light.shadow.bias = -.0005;
  scene.add(light);
  const content = new THREE.Group();
  scene.add(content);
  let state = initial;
  let narrow = host.clientWidth < 600;
  let disposed = false;
  let visible = true;
  let frame = 0;
  let last = 0;
  let dirty = true;
  let geometries: THREE.BufferGeometry[] = [];
  let materials: THREE.Material[] = [];
  let textures: THREE.Texture[] = [];
  let moving: Moving[] = [];
  let apply: (value: AlgorithmState) => void = () => {};
  let syncFrame: () => void = () => {};
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const px = (x: number) => x * (narrow ? .59 : 1);

  function material(color: number, opacity = 1) {
    const value = new THREE.MeshStandardMaterial({ color, roughness: .5, metalness: .08, transparent: opacity < 1, opacity });
    materials.push(value); return value;
  }
  function box(w: number, h: number, d: number, color = INK, opacity = 1) {
    const geometry = new THREE.BoxGeometry(w, h, d);
    geometries.push(geometry);
    const mesh = new THREE.Mesh(geometry, material(color, opacity));
    mesh.castShadow = mesh.receiveShadow = true;
    return mesh;
  }
  function line(points: number[][], color = 0xa6b1a8, dashed = false) {
    const geometry = new THREE.BufferGeometry().setFromPoints(points.map(p => new THREE.Vector3(...p)));
    const mat = dashed ? new THREE.LineDashedMaterial({ color, dashSize: .08, gapSize: .08 }) : new THREE.LineBasicMaterial({ color });
    geometries.push(geometry); materials.push(mat);
    const value = new THREE.Line(geometry, mat); value.computeLineDistances(); content.add(value); return value;
  }
  function label(text: string, x: number, y: number, z = 0, size = .26, color = "#344a3d", width = 4) {
    const canvas = document.createElement("canvas");
    canvas.width = 1024; canvas.height = 192;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Text canvas unavailable");
    context.font = '500 48px -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif';
    const rows = text.split("\n");
    const textWidth = Math.max(...rows.map(row => context.measureText(row).width), 1);
    const spriteWidth = Math.min(width, textWidth / 48 * size);
    context.textAlign = "center"; context.textBaseline = "middle"; context.fillStyle = color;
    rows.forEach((row, i) => context.fillText(row, 512, 96 + (i - (rows.length - 1) / 2) * 62, 1000));
    const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace;
    textures.push(texture);
    const mat = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
    materials.push(mat);
    const sprite = new THREE.Sprite(mat);
    // Canvas includes transparent margins. Match its full aspect so glyphs are
    // never stretched or independently positioned from their graph anchors.
    const fullWidth = spriteWidth * 1024 / Math.min(textWidth, 1000);
    sprite.scale.set(fullWidth, fullWidth * 192 / 1024, 1);
    sprite.position.set(x, y, z); sprite.renderOrder = 10; content.add(sprite);
    return sprite;
  }
  function paper(x: number, y: number, z: number, width = .65, height = .5, color = WHITE) {
    const group = new THREE.Group(); group.position.set(x, y, z);
    group.add(box(width, height, .24, color));
    for (let i = 0; i < 3; i++) {
      const row = box(width * (i === 2 ? .45 : .7), .018, .014, color === WHITE ? 0x82938a : 0xdbe8df);
      row.position.set(-width * .04, height * .2 - i * height * .18, .13); group.add(row);
    }
    content.add(group); return group;
  }
  function target(object: THREE.Object3D, x: number, y: number, z: number, sx = 1, sy = 1, sz = 1) {
    let entry = moving.find(value => value.object === object);
    if (!entry) { entry = { object, position: object.position.clone(), scale: object.scale.clone() }; moving.push(entry); }
    entry.position.set(x, y, z); entry.scale.set(sx, sy, sz); dirty = true;
  }
  function clearContent() {
    content.clear(); geometries.forEach(g => g.dispose()); materials.forEach(m => m.dispose()); textures.forEach(t => t.dispose());
    geometries = []; materials = []; textures = []; moving = []; syncFrame = () => {};
  }
  function removeLabel(sprite: THREE.Sprite) {
    content.remove(sprite);
    const texture = sprite.material.map;
    texture?.dispose(); sprite.material.dispose();
    textures = textures.filter(item => item !== texture);
    materials = materials.filter(item => item !== sprite.material);
    moving = moving.filter(item => item.object !== sprite);
  }
  function buildFetch() {
    const rows = [1.5, .75, 0, -.75, -1.5];
    label("검색 URL", px(-3.7), 2.25, 0, .28);
    label("출처 승인", px(-1.35), 2.25, 0, .27);
    label("HTTP → 본문", px(1.05), 2.25, 0, .27);
    label("비교할 원문", px(3.6), 2.25, 0, .28);
    [-1.35, 1.05].forEach(x => {
      const gate = box(.09, 3.8, .65, 0x89978e, .12); gate.position.set(px(x), 0, -.08); content.add(gate);
      line([[px(x), -1.9, .3], [px(x), 1.9, .3]], 0x788d7e);
    });
    const documents = rows.map((y, i) => {
      line([[px(-3.5), y, -.2], [px(3.6), y, -.2]], 0xb5c0b8, true);
      label(["A", "B", "C", "미승인", "D / 84자"][i], px(-4.6), y, 0, narrow ? .24 : .26, "#43584a", narrow ? .8 : 1.2);
      return paper(px(-3.7), y, .2, narrow ? .4 : .62, .43);
    });
    const rejectA = label("×", px(-1.75), rows[3], .4, .4, "#69716b");
    const rejectD = label("×", px(.55), rows[4], .4, .4, "#69716b");
    const quorum = line([[px(3.95), 1.75, 0], [px(4.3), 1.75, 0], [px(4.3), -.25, 0], [px(3.95), -.25, 0]], INK);
    apply = value => {
      documents.forEach((doc, i) => {
        const x = value.step === 0 ? -3.7 : i === 3 ? -1.9 : value.step === 1 ? -.35 : i === 4 ? .5 : 3.6;
        target(doc, px(x), rows[i], value.step === 3 && i < 3 ? .1 + i * .16 : .2, i === 3 && value.step > 0 ? .6 : 1, i === 3 && value.step > 0 ? .6 : 1);
      });
      rejectA.visible = value.step > 0; rejectD.visible = value.step > 1; quorum.visible = value.step === 3;
    };
  }
  function buildEvidence() {
    const docX = px(-2.45), quoteX = px(2.75);
    const docWidth = narrow ? 2.7 : 4.2;
    const sheet = box(docWidth, 3.8, .12, WHITE); sheet.position.set(docX, 0, 0); content.add(sheet);
    label("분석할 원문", docX, 2.35, .1, .3);
    label("예시신문 / 김기자", docX, 1.35, .16, .23, "#6b7d71", docWidth - .3);
    label("정부가 새로운 지원\n대책을 발표했다.", docX, .5, .16, .27, "#3e5144", docWidth - .25);
    const band = box(docWidth - .25, .9, .018, 0xd1e7d6); band.position.set(docX, -.48, .075); content.add(band);
    label("예산 부담은 남았지만\n단기 효과가 기대된다.", docX, -.48, .18, .27, "#234d35", docWidth - .4);
    label("시행 범위는 추가 논의한다.", docX, -1.3, .18, .22, "#6b7d71", docWidth - .3);
    const mask = box(docWidth - .35, .3, .07, INK); mask.position.set(docX, 1.35, .4); content.add(mask);
    mask.castShadow = false;
    const maskLabel = label("출처 가림", docX, 1.35, .47, .21, "#ffffff", docWidth - .5);
    const sourceLabel = content.children.find(child => child instanceof THREE.Sprite && Math.abs(child.position.y - 1.35) < .01 && child !== maskLabel);
    const quote = box(narrow ? 2.35 : 3.45, 1.4, .18, 0xd5e9db); quote.position.set(docX, -.48, -.2); content.add(quote);
    const quoteText = label("예산 부담은 남았지만\n단기 효과가 기대된다.", quoteX, -.2, .4, .27, "#234d35", narrow ? 2.15 : 3.15);
    const offset = label("[21, 45)", quoteX, 1.15, .1, .42, "#27835a");
    label("정확한 원문 위치", quoteX, 2.35, .1, .28);
    const connector = line([[docX + docWidth / 2, -.48, .15], [quoteX - (narrow ? 1.2 : 1.8), -.2, .3]], GREEN, true);
    apply = value => {
      mask.visible = maskLabel.visible = value.step > 0;
      if (sourceLabel) sourceLabel.visible = value.step === 0;
      band.visible = value.step === 2;
      quote.visible = quoteText.visible = offset.visible = connector.visible = value.step === 2;
      target(quote, value.step === 2 ? quoteX : docX, value.step === 2 ? -.2 : -.48, .15);
    };
  }
  function buildWeights() {
    const base = 0;
    const factor = .026;
    const xs = [-3.7, -1.85, 0, 1.85, 3.7].map(px);
    line([[px(-4.6), base, .25], [px(4.6), base, .25]], 0x8a9c8d);
    label("0", px(-4.65), base, .3, .22);
    const bars = xs.map((x, i) => { const bar = box(narrow ? .5 : .85, 1, .65, i === 4 ? INK : GREEN); bar.position.set(x, base, 0); content.add(bar); return bar; });
    const labels: THREE.Sprite[] = [];
    const bridges: THREE.Line[] = [];
    xs.slice(0, -1).forEach((x, i) => {
      const mat = new THREE.LineDashedMaterial({ color: 0x9aa99d, dashSize: .06, gapSize: .05 }); materials.push(mat);
      const geometry = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(x, base, 0), new THREE.Vector3(xs[i + 1], base, 0)]); geometries.push(geometry);
      const bridge = new THREE.Line(geometry, mat); content.add(bridge); bridges.push(bridge);
    });
    SIGNALS.forEach((item, i) => label(item.label, xs[i], -2.05, .1, narrow ? .22 : .26, "#415848", narrow ? 1.03 : 1.5));
    label("합계", xs[4], -2.05, .1, .27);
    label("가중 기여량을 쌓으면 최종 x", 0, 2.55, 0, .3);
    let oldModel: number | undefined;
    apply = value => {
      if (value.model === oldModel) return;
      oldModel = value.model;
      labels.forEach(removeLabel); labels.length = 0;
      let total = 0;
      SIGNALS.forEach((item, i) => {
        const input = i === 0 ? value.model : item.value;
        const contribution = input * item.weight;
        const start = total; total += contribution;
        target(bars[i], xs[i], base + (start + contribution / 2) * factor, 0, 1, Math.max(.035, Math.abs(contribution * factor)), 1);
        labels.push(label(`${input} × ${item.weight.toFixed(2)}`, xs[i], -2.48, .1, narrow ? .2 : .24, "#5f7366", narrow ? 1.05 : 1.7));
        labels.push(label(`${contribution > 0 ? "+" : ""}${contribution.toFixed(1)}`, xs[i], base + Math.max(start, total) * factor + .4, .1, .26, "#27835a"));
        const attr = bridges[i].geometry.getAttribute("position") as THREE.BufferAttribute;
        attr.setXYZ(0, xs[i], base + total * factor, .1); attr.setXYZ(1, xs[i + 1], base + total * factor, .1); attr.needsUpdate = true; bridges[i].computeLineDistances();
      });
      target(bars[4], xs[4], base + total * factor / 2, 0, 1, Math.max(.035, Math.abs(total * factor)), 1);
      labels.push(label(`${weightedScore(value.model)}`, xs[4], base + Math.max(0, total) * factor + .55, .1, .46, "#23372b"));
    };
  }
  function buildCoordinates() {
    const origin = [-2, -1.35, 1.5];
    const grid: number[][] = [];
    for (let i = 0; i <= 4; i++) {
      const x = -2 + i, y = -1.35 + .7 * i, z = 1.5 - .75 * i;
      grid.push([x, -1.35, 1.5], [x, -1.35, -1.5], [-2, -1.35, z], [2, -1.35, z]);
      grid.push([x, -1.35, -1.5], [x, 1.45, -1.5], [-2, y, -1.5], [2, y, -1.5]);
    }
    for (let i = 0; i < grid.length; i += 2) line(grid.slice(i, i + 2), 0xc7d1c7);
    line([origin, [2, -1.35, 1.5]], INK); line([origin, [-2, 1.45, 1.5]], INK); line([origin, [-2, -1.35, -1.5]], INK);
    label("−100", -2, -1.7, 1.5, .23); label("+100", 2, -1.7, 1.5, .23);
    label("관점 x", 0, -2, 1.6, .29);
    label("선정성 s", -2.15, 1.95, 1.5, .29);
    label("0", -2.38, -1.35, 1.5, .23); label("100", -2.4, 1.45, 1.5, .23);
    label("신뢰도 C", -2.5, -.9, -1.8, .28);
    label("0", -2.4, -1.6, 1.05, .22); label("1", -2.4, -1.6, -1.5, .22);
    const geometry = new THREE.SphereGeometry(.13, 28, 20); geometries.push(geometry);
    const point = new THREE.Mesh(geometry, material(GREEN)); point.castShadow = true; content.add(point);
    const dot = new THREE.Mesh(geometry, material(0x87b198)); dot.scale.set(.65, .12, .65); content.add(dot);
    const guide = line([[0, 0, 0], [0, 0, 0]], GREEN, true);
    const projection = line([[0, 0, 0], [0, 0, 0], [0, 0, 0]], GREEN, true);
    let pointLabel: THREE.Sprite | undefined;
    syncFrame = () => {
      const { x, y, z } = point.position;
      dot.position.set(x, -1.33, z);
      const a = guide.geometry.getAttribute("position") as THREE.BufferAttribute;
      a.setXYZ(0, x, y, z); a.setXYZ(1, x, -1.35, z); a.needsUpdate = true; guide.computeLineDistances();
      const b = projection.geometry.getAttribute("position") as THREE.BufferAttribute;
      b.setXYZ(0, x, -1.35, 1.5); b.setXYZ(1, x, -1.35, z); b.setXYZ(2, -2, -1.35, z); b.needsUpdate = true; projection.computeLineDistances();
      if (pointLabel) pointLabel.position.set(x + .5, y + .38, z);
    };
    apply = value => {
      const x = value.x / 50, y = -1.35 + value.s / 100 * 2.8, z = 1.5 - value.c / 100 * 3;
      target(point, x, y, z);
      if (pointLabel) removeLabel(pointLabel);
      pointLabel = label(`(${value.x}, ${value.s}, ${(value.c / 100).toFixed(2)})`, x + .5, y + .38, z, .24, "#20714c", 2.5);
    };
  }
  function buildRanking() {
    const row = (i: number) => 1.35 - i * .93;
    const left = px(-2.65), right = px(2.65), width = narrow ? 2.3 : 3.45;
    label("초기 점수", left, 2.3, .1, .3);
    label("선택 순서", right, 2.3, .1, .3);
    const { initial: items } = rankingExample(false);
    const cards = items.map((item, i) => {
      const card = box(width, .63, .18, WHITE); card.position.set(left, row(i), 0); content.add(card);
      label(`${item.id}   ${item.source}매체 / ${item.issue}   ${item.score.toFixed(3)}`, left, row(i), .16, narrow ? .2 : .24, "#3b5242", width - .2);
      const output = box(width, .63, .25, 0xd6e7d9); output.position.set(left, row(i), -.4); content.add(output);
      return { item, output };
    });
    line([[px(-.65), 0, 0], [px(.65), 0, 0]], INK);
    line([[px(.35), .15, 0], [px(.65), 0, 0], [px(.35), -.15, 0]], INK);
    const labels: THREE.Sprite[] = [];
    apply = value => {
      labels.forEach(removeLabel); labels.length = 0;
      const ranked = rankingExample(value.diverse);
      cards.forEach(({ item, output }) => {
        const i = ranked.selected.findIndex(selected => selected.id === item.id);
        const y = i < 0 ? -2.5 : row(i);
        target(output, right, y, i < 0 ? -.8 : .2, i < 0 ? .85 : 1, 1, 1);
        const text = i < 0 ? `${item.id}   같은 이슈 → 제외` : `${i + 1}   ${item.id} / ${item.source}매체 / ${item.issue}`;
        const tag = label(text, right, y, .5, narrow ? .2 : .25, i < 0 ? "#768479" : "#254a32", width - .2);
        // Labels share the same interpolation as the physical rows.
        tag.position.set(output.position.x, output.position.y, .5);
        target(tag, right, y, .5, tag.scale.x, tag.scale.y, 1); labels.push(tag);
      });
    };
  }
  function resetView() {
    controls.target.set(0, -.1, 0);
    camera.position.set(state.mode === "coordinates" ? 6.7 : state.mode === "weights" ? 1.5 : 3.5, state.mode === "coordinates" ? 4.5 : 4.3, 13);
    controls.update(); dirty = true;
  }
  function build() {
    clearContent();
    if (state.mode === "fetch") buildFetch();
    if (state.mode === "evidence") buildEvidence();
    if (state.mode === "weights") buildWeights();
    if (state.mode === "coordinates") buildCoordinates();
    if (state.mode === "ranking") buildRanking();
    apply(state); resetView(); dirty = true;
  }
  function resize() {
    const width = Math.max(host.clientWidth, 1), height = Math.max(host.clientHeight, 1);
    const nextNarrow = width < 600;
    renderer.setSize(width, height, false);
    const halfWidth = nextNarrow ? 3.45 : 5.8;
    const halfHeight = halfWidth * height / width;
    camera.left = -halfWidth; camera.right = halfWidth; camera.top = halfHeight; camera.bottom = -halfHeight;
    camera.updateProjectionMatrix();
    if (narrow !== nextNarrow) { narrow = nextNarrow; build(); }
    dirty = true;
  }
  function render(now: number) {
    if (disposed) return;
    frame = requestAnimationFrame(render);
    if (!visible || document.hidden) { last = now; return; }
    const delta = Math.min((now - last) / 1000, .05); last = now;
    let animating = false;
    for (const entry of moving) {
      const unsettled = entry.object.position.distanceToSquared(entry.position) > .000001 || entry.object.scale.distanceToSquared(entry.scale) > .000001;
      if (!unsettled) continue;
      const alpha = motion.matches ? 1 : 1 - Math.exp(-8 * delta);
      entry.object.position.lerp(entry.position, alpha); entry.object.scale.lerp(entry.scale, alpha); animating = true;
    }
    if (dirty || animating) { syncFrame(); renderer.render(scene, camera); dirty = false; }
  }
  controls.addEventListener("change", () => { dirty = true; });
  const observer = new ResizeObserver(resize); observer.observe(host);
  const intersection = new IntersectionObserver(entries => { visible = entries[0]?.isIntersecting ?? true; dirty = true; }); intersection.observe(host);
  build(); resize(); frame = requestAnimationFrame(render);
  return {
    update(next: AlgorithmState) { const changed = state.mode !== next.mode; state = next; if (changed) build(); else apply(state); dirty = true; },
    resetView,
    setInteractive(enabled: boolean) { controls.enabled = enabled; renderer.domElement.style.touchAction = enabled ? "none" : "pan-y"; },
    dispose() { disposed = true; cancelAnimationFrame(frame); observer.disconnect(); intersection.disconnect(); controls.dispose(); clearContent(); light.shadow.dispose(); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); },
  };
}

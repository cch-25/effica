"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";

const NODES = [
  { position: [1.42, 0.48, 0.66], scale: 0.105, color: "#f08a73" },
  { position: [-1.1, 1.12, 0.34], scale: 0.08, color: "#f3d36f" },
  { position: [-1.32, -0.86, 0.52], scale: 0.092, color: "#9cc9aa" },
  { position: [0.54, -1.48, -0.14], scale: 0.064, color: "#b9a9dc" },
] as const;

function useReducedMotion() {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return reduced;
}

function particlePositions() {
  const count = 84;
  const positions = new Float32Array(count * 3);
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));

  for (let index = 0; index < count; index += 1) {
    const y = 1 - (index / (count - 1)) * 2;
    const radius = Math.sqrt(1 - y * y);
    const theta = goldenAngle * index;
    const distance = 2.05 + ((index * 17) % 9) * 0.055;
    positions[index * 3] = Math.cos(theta) * radius * distance;
    positions[index * 3 + 1] = y * distance;
    positions[index * 3 + 2] = Math.sin(theta) * radius * distance;
  }

  return positions;
}

function disposeScene(scene: THREE.Scene) {
  scene.traverse((object) => {
    if (!(object instanceof THREE.Mesh || object instanceof THREE.Points)) return;
    object.geometry.dispose();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    materials.forEach((material) => material.dispose());
  });
}

function PerspectiveCanvas({
  onUnavailable,
  reducedMotion,
}: {
  onUnavailable: () => void;
  reducedMotion: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        canvas,
        alpha: true,
        antialias: true,
        powerPreference: "high-performance",
      });
    } catch {
      onUnavailable();
      return;
    }

    renderer.setClearAlpha(0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    renderer.outputColorSpace = THREE.SRGBColorSpace;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    camera.position.set(0, 0, 6.8);

    scene.add(new THREE.AmbientLight("#ffffff", 1.55));
    const keyLight = new THREE.DirectionalLight("#ffffff", 3.4);
    keyLight.position.set(4, 5, 5);
    scene.add(keyLight);
    const greenLight = new THREE.PointLight("#9cc9aa", 14, 8);
    greenLight.position.set(-3, -2, 3);
    scene.add(greenLight);
    const fillLight = new THREE.PointLight("#ffffff", 8, 7);
    fillLight.position.set(2, -3, -2);
    scene.add(fillLight);

    const field = new THREE.Group();
    field.rotation.set(-0.12, -0.2, 0.03);
    field.scale.setScalar(reducedMotion ? 1 : 0.72);
    scene.add(field);

    const particleGeometry = new THREE.BufferGeometry();
    particleGeometry.setAttribute("position", new THREE.BufferAttribute(particlePositions(), 3));
    const particles = new THREE.Points(
      particleGeometry,
      new THREE.PointsMaterial({
        color: "#3455b4",
        size: 0.018,
        sizeAttenuation: true,
        transparent: true,
        opacity: 0.34,
      }),
    );
    field.add(particles);

    field.add(
      new THREE.Mesh(
        new THREE.SphereGeometry(1.66, 64, 48),
        new THREE.MeshPhysicalMaterial({
          color: "#b8d9ec",
          metalness: 0.2,
          roughness: 0.18,
          transmission: 0.52,
          thickness: 1.5,
          transparent: true,
          opacity: 0.46,
          side: THREE.DoubleSide,
        }),
      ),
    );
    field.add(
      new THREE.Mesh(
        new THREE.IcosahedronGeometry(1.69, 3),
        new THREE.MeshBasicMaterial({
          color: "#3455b4",
          wireframe: true,
          transparent: true,
          opacity: 0.12,
        }),
      ),
    );

    const core = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.78, 2),
      new THREE.MeshStandardMaterial({
        color: "#7893e5",
        metalness: 0.78,
        roughness: 0.24,
        flatShading: true,
      }),
    );
    core.rotation.set(0.5, 0.15, 0.3);
    field.add(core);

    const ringOne = new THREE.Mesh(
      new THREE.TorusGeometry(1.92, 0.018, 16, 160),
      new THREE.MeshStandardMaterial({ color: "#f08a73", metalness: 0.55, roughness: 0.28 }),
    );
    ringOne.rotation.set(1.08, 0.2, 0.18);
    field.add(ringOne);

    const ringTwo = new THREE.Mesh(
      new THREE.TorusGeometry(2.03, 0.012, 14, 160),
      new THREE.MeshStandardMaterial({ color: "#f3d36f", metalness: 0.45, roughness: 0.3 }),
    );
    ringTwo.rotation.set(0.18, 1.12, -0.42);
    field.add(ringTwo);

    const thirdRing = new THREE.Mesh(
      new THREE.TorusGeometry(1.82, 0.008, 12, 160),
      new THREE.MeshBasicMaterial({ color: "#3455b4", transparent: true, opacity: 0.48 }),
    );
    thirdRing.rotation.set(0.62, -0.8, 0.78);
    field.add(thirdRing);

    NODES.forEach((node) => {
      const group = new THREE.Group();
      group.position.set(node.position[0], node.position[1], node.position[2]);
      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(1, 28, 28),
        new THREE.MeshStandardMaterial({
          color: node.color,
          emissive: node.color,
          emissiveIntensity: node.color === "#9cc9aa" ? 0.24 : 0.04,
          metalness: 0.25,
          roughness: 0.18,
        }),
      );
      marker.scale.setScalar(node.scale);
      group.add(marker);
      const halo = new THREE.Mesh(
        new THREE.SphereGeometry(1, 18, 18),
        new THREE.MeshBasicMaterial({
          color: node.color,
          wireframe: true,
          transparent: true,
          opacity: 0.28,
        }),
      );
      halo.scale.setScalar(node.scale * 1.9);
      group.add(halo);
      field.add(group);
    });

    const pointer = new THREE.Vector2();
    const updatePointer = (event: PointerEvent) => {
      const bounds = canvas.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return;
      pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
      pointer.y = 1 - ((event.clientY - bounds.top) / bounds.height) * 2;
    };
    const resetPointer = () => pointer.set(0, 0);
    canvas.addEventListener("pointermove", updatePointer);
    canvas.addEventListener("pointerleave", resetPointer);

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
      const delta = Math.min(timer.getDelta(), 0.1);
      const elapsed = timer.getElapsed();
      const entrance = Math.min(1, elapsed / 1.35);
      const easedEntrance = 1 - Math.pow(1 - entrance, 3);
      const targetX = -0.12 + pointer.y * 0.18;
      const targetY = -0.2 + pointer.x * 0.28;

      field.scale.setScalar(0.72 + easedEntrance * 0.28);
      field.rotation.x = THREE.MathUtils.damp(field.rotation.x, targetX, 3.2, delta);
      field.rotation.y = THREE.MathUtils.damp(field.rotation.y, targetY, 3.2, delta);
      core.rotation.x += delta * 0.12;
      core.rotation.y -= delta * 0.16;
      ringOne.rotation.z += delta * 0.075;
      ringTwo.rotation.z -= delta * 0.055;
      particles.rotation.y += delta * 0.018;
      renderer.render(scene, camera);
      animationFrame = window.requestAnimationFrame(renderFrame);
    };

    if (reducedMotion) {
      renderer.render(scene, camera);
    } else {
      animationFrame = window.requestAnimationFrame(renderFrame);
    }

    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      canvas.removeEventListener("pointermove", updatePointer);
      canvas.removeEventListener("pointerleave", resetPointer);
      timer.dispose();
      disposeScene(scene);
      renderer.dispose();
    };
  }, [onUnavailable, reducedMotion]);

  return <canvas ref={canvasRef} className="perspective-orb__canvas" aria-hidden="true" />;
}

export function PerspectiveOrb() {
  const reducedMotion = useReducedMotion();
  const [webglUnavailable, setWebglUnavailable] = useState(false);
  const handleUnavailable = useCallback(() => setWebglUnavailable(true), []);

  return (
    <div className="perspective-orb">
      <div className="perspective-orb__label">
        <span>01 / PERSPECTIVE FIELD</span>
        <span><i /> LIVE MODEL</span>
      </div>
      {webglUnavailable ? (
        <div className="perspective-orb__fallback" />
      ) : (
        <PerspectiveCanvas reducedMotion={reducedMotion} onUnavailable={handleUnavailable} />
      )}
      <div className="perspective-orb__coordinates">X +0.34 / Y −0.12 / Δ 0.46</div>
    </div>
  );
}

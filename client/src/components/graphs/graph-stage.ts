import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

/** A lit measuring stage. Its dimensions match the data volume exactly. */
export function createGraphStage(renderer: THREE.WebGLRenderer, scene: THREE.Scene) {
  const geometries: THREE.BufferGeometry[] = [];
  const materials: THREE.Material[] = [];
  const environment = new RoomEnvironment();
  const generator = new THREE.PMREMGenerator(renderer);
  const environmentMap = generator.fromScene(environment, .04);
  scene.environment = environmentMap.texture;
  scene.environmentIntensity = .75;
  environment.dispose(); generator.dispose();
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  const steel = new THREE.MeshStandardMaterial({ color: 0x92969d, roughness: .3, metalness: .8 });
  const porcelain = new THREE.MeshPhysicalMaterial({ color: 0xe4e6e9, roughness: .36, metalness: .12, clearcoat: .65 });
  materials.push(steel, porcelain);
  function box(size: [number, number, number], position: [number, number, number], material: THREE.Material, radius = .025) {
    const geometry = new RoundedBoxGeometry(...size, 3, radius);
    geometries.push(geometry);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(...position); mesh.castShadow = mesh.receiveShadow = true;
    scene.add(mesh); return mesh;
  }
  const platform = box([2.65, .105, 1.9], [0, -.91, 0], steel);
  const surface = box([2.58, .035, 1.83], [0, -.844, 0], porcelain, .012);
  const groundGeometry = new THREE.PlaneGeometry(200, 200);
  const groundMaterial = new THREE.ShadowMaterial({ color: 0x505968, opacity: .17 });
  geometries.push(groundGeometry); materials.push(groundMaterial);
  const ground = new THREE.Mesh(groundGeometry, groundMaterial);
  ground.rotation.x = -Math.PI / 2; ground.position.y = -1.02; ground.receiveShadow = true; scene.add(ground);
  const panelGeometry = new THREE.PlaneGeometry(2.4, 1.65);
  const panelMaterial = new THREE.MeshPhysicalMaterial({ color: 0xc5cedb, roughness: .3, metalness: .1, clearcoat: 1, transparent: true, opacity: .11, side: THREE.DoubleSide, depthWrite: false });
  geometries.push(panelGeometry); materials.push(panelMaterial);
  const panel = new THREE.Mesh(panelGeometry, panelMaterial);
  panel.position.z = -.83; scene.add(panel);
  const key = new THREE.DirectionalLight(0xffffff, 3.1);
  key.position.set(-2, 5, 3); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, { left: -2.3, right: 2.3, top: 2.3, bottom: -2.3, near: .1, far: 12 });
  key.shadow.normalBias = .015; key.shadow.bias = -.0002;
  scene.add(key, new THREE.HemisphereLight(0xffffff, 0xabb0bc, .7));
  const fill = new THREE.DirectionalLight(0xe2eaff, 1.6);
  fill.position.set(3, 1, -3); scene.add(fill);

  const rails = new THREE.Group(); scene.add(rails);
  function rod(start: number[], end: number[], radius = .007) {
    const a = new THREE.Vector3(...start), b = new THREE.Vector3(...end);
    const geometry = new THREE.CylinderGeometry(radius, radius, a.distanceTo(b), 12);
    geometries.push(geometry);
    const mesh = new THREE.Mesh(geometry, steel);
    mesh.position.addVectors(a, b).multiplyScalar(.5);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.sub(a).normalize());
    mesh.castShadow = true; rails.add(mesh);
  }
  rod([-1.2, -.825, .825], [1.2, -.825, .825]);
  rod([-1.2, -.825, .825], [-1.2, .825, .825]);
  rod([-1.2, -.825, .825], [-1.2, -.825, -.825]);
  for (let i = 0; i <= 20; i++) {
    const length = i % 5 === 0 ? .055 : .025;
    rod([-1.2 + i * .12, -.82, .825], [-1.2 + i * .12, -.82, .825 + length], .0025);
    rod([-1.2, -.825 + i * .0825, .825], [-1.2 - length, -.825 + i * .0825, .825], .0025);
    rod([-1.2, -.825, .825 - i * .0825], [-1.2 - length, -.825, .825 - i * .0825], .0025);
  }
  return {
    setPlanar(planar: boolean) {
      platform.visible = surface.visible = ground.visible = panel.visible = !planar;
      renderer.shadowMap.enabled = !planar;
    },
    dispose() { geometries.forEach(g => g.dispose()); materials.forEach(m => m.dispose()); environmentMap.dispose(); key.shadow.dispose(); },
  };
}

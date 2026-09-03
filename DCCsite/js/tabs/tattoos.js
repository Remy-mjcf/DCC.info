import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { el, fetchJSON, renderCardGrid, renderError, renderLoading } from "../lib/utils.js";

const DATA_PATH = "../DCCdata/tattoos.json";

// Placement coordinates are expected as normalized [0, 1] values per axis
// (see tattoo.schema.json), not raw scene units -- e.g. x=0.12 means "12%
// of the way from the body's left edge to its right edge", not 0.12 world
// units. BODY_BOUNDS maps that normalized space onto the placeholder
// mesh's approximate bounding box. Retune these once real coordinates
// (and a real body mesh) are in and we know the actual convention.
const BODY_BOUNDS = {
  x: [-0.5, 0.5],
  y: [0, 1.95],
  z: [-0.3, 0.3],
};

function lerp(min, max, t) {
  return min + (max - min) * t;
}

function normalizedToWorld(position3d) {
  return new THREE.Vector3(
    lerp(...BODY_BOUNDS.x, position3d.x),
    lerp(...BODY_BOUNDS.y, position3d.y),
    lerp(...BODY_BOUNDS.z, position3d.z),
  );
}

function createHumanoidPlaceholder() {
  const group = new THREE.Group();
  const material = new THREE.MeshStandardMaterial({ color: 0x4d5568, roughness: 0.55, metalness: 0.15 });

  const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.3, 0.6, 4, 8), material);
  torso.position.y = 1.1;
  group.add(torso);

  const head = new THREE.Mesh(new THREE.SphereGeometry(0.22, 16, 16), material);
  head.position.y = 1.75;
  group.add(head);

  const armGeometry = new THREE.CapsuleGeometry(0.08, 0.55, 4, 8);
  for (const side of [-1, 1]) {
    const arm = new THREE.Mesh(armGeometry, material);
    arm.position.set(0.42 * side, 1.15, 0);
    group.add(arm);
  }

  const legGeometry = new THREE.CapsuleGeometry(0.11, 0.7, 4, 8);
  for (const side of [-1, 1]) {
    const leg = new THREE.Mesh(legGeometry, material);
    leg.position.set(0.16 * side, 0.4, 0);
    group.add(leg);
  }

  return group;
}

function createMarker(tattoo, worldPosition) {
  const marker = new THREE.Mesh(
    new THREE.SphereGeometry(0.035, 12, 12),
    new THREE.MeshBasicMaterial({ color: 0xffcc00 }),
  );
  marker.position.copy(worldPosition);
  marker.userData.tattoo = tattoo;
  return marker;
}

function hasPlacement(tattoo) {
  const p = tattoo.placement?.position_3d;
  return p && typeof p.x === "number" && typeof p.y === "number" && typeof p.z === "number";
}

function setupScene(sceneContainer, tattoos, onMarkerClick) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x161922);
  scene.fog = new THREE.Fog(0x161922, 3, 8);

  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(1.4, 1.4, 1.8);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  sceneContainer.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.target.set(0, 1, 0);

  scene.add(new THREE.HemisphereLight(0x6f8fff, 0x0a0a12, 1.1));
  const directional = new THREE.DirectionalLight(0x9fe8ff, 1.4);
  directional.position.set(2, 3, 2);
  scene.add(directional);

  scene.add(new THREE.GridHelper(2, 10, 0x33e0c9, 0x252a36));
  scene.add(createHumanoidPlaceholder());

  const markers = [];
  for (const tattoo of tattoos) {
    if (!hasPlacement(tattoo)) continue;
    const marker = createMarker(tattoo, normalizedToWorld(tattoo.placement.position_3d));
    scene.add(marker);
    markers.push(marker);
  }

  function resize() {
    const width = sceneContainer.clientWidth;
    const height = sceneContainer.clientHeight;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }
  window.addEventListener("resize", resize);
  resize();

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  renderer.domElement.addEventListener("click", (event) => {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(markers);
    if (hits.length) onMarkerClick(hits[0].object.userData.tattoo);
  });

  function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }
  animate();

  return { markerCount: markers.length };
}

function renderTattooDetail(container, tattoo) {
  container.replaceChildren();
  container.appendChild(el("h3", { text: tattoo.name ?? "Unknown tattoo" }));
  if (tattoo.image) {
    container.appendChild(el("img", { attrs: { src: `../assets/images/${tattoo.image}`, alt: tattoo.name ?? "" } }));
  }
  if (tattoo.crawler_id) {
    container.appendChild(el("p", { text: `Crawler: ${tattoo.crawler_id}` }));
  }
  if (tattoo.placement?.body_part) {
    const side = tattoo.placement.side ? ` (${tattoo.placement.side})` : "";
    container.appendChild(el("p", { text: `Placement: ${tattoo.placement.body_part}${side}` }));
  }
  if (tattoo.effect) {
    container.appendChild(el("p", { text: tattoo.effect }));
  }
  if (tattoo.source_url) {
    const link = el("a", { text: "Wiki source", attrs: { href: tattoo.source_url, target: "_blank", rel: "noopener" } });
    container.appendChild(el("p", {}, [link]));
  }
}

function buildListCard(tattoo) {
  const card = el("article", { className: "card" });
  card.appendChild(el("h3", { text: tattoo.name ?? "Unknown" }));
  if (tattoo.crawler_id) card.appendChild(el("p", { className: "card-meta", text: `Crawler: ${tattoo.crawler_id}` }));
  if (tattoo.effect) card.appendChild(el("p", { className: "card-summary", text: tattoo.effect }));
  if (!hasPlacement(tattoo)) card.appendChild(el("p", { className: "empty-state", text: "3D placement pending" }));
  return card;
}

export default async function renderTattoos(panel) {
  const sceneContainer = panel.querySelector("#tattoo-scene");
  const detailContainer = panel.querySelector("#tattoo-detail");
  const listContainer = panel.querySelector("#tattoo-list");

  renderLoading(listContainer);

  let tattoos = [];
  let loadError = null;
  try {
    tattoos = await fetchJSON(DATA_PATH);
  } catch (err) {
    loadError = err;
  }

  // The 3D scene (humanoid placeholder, lighting, controls) doesn't depend
  // on tattoo data existing -- always show it, even with zero markers.
  const { markerCount } = setupScene(sceneContainer, tattoos, (tattoo) => {
    renderTattooDetail(detailContainer, tattoo);
  });

  if (!markerCount) {
    detailContainer.replaceChildren(
      el("p", { className: "tattoo-detail-placeholder", text: "No tattoos have 3D placement yet." }),
    );
  }

  if (loadError) {
    renderError(listContainer, `Couldn't load tattoos: ${loadError.message}`);
  } else {
    renderCardGrid(listContainer, tattoos, buildListCard, "No tattoos yet -- run the extraction pipeline.");
  }
}

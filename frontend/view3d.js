// 3D view for the big screen: satellite imagery tilted like a chase camera, restricted zones as walls up to the legal height,
// the permit as a glass box up to its height limit, and a modelled quadcopter (three.js) with spinning rotors, a ground shadow,
// a height line and a trail. MapLibre GL draws the world, three.js draws the drone in the same depth buffer.
const View3D = (() => {
  let map = null, ready = false, scene, camera, renderer, rig, rotors = [], light, shadow, drop, trailLine, trailGeo, origin = null, mercO = null;
  let cur = null, prev = null, tPrev = 0, tCur = 0, mode = "chase", camHeading = 0, gimbal = 25, trail = [], onReady = [], zoneGeo = [], nearest = null, lastNear = 0, raf = 0;
  const MODES = ["chase", "fpv", "top", "free"], MODE_LABEL = { chase: "Camera: chase", fpv: "Camera: drone view", top: "Camera: from above", free: "Camera: free" };
  const M_LAT = 110574, M_LNG = 111320, MAX_TRAIL = 900;
  const RED = 0xd64545, AMBER = 0xe0a030, GREEN = 0x3fae6a, ACCENT = 0x4aa3df;

  function local(lng, lat, alt) {
    return new THREE.Vector3((lng - origin[0]) * M_LNG * Math.cos(origin[1] * Math.PI / 180), (lat - origin[1]) * M_LAT, alt || 0);
  }

  function buildDrone() {
    const g = new THREE.Group(), dark = new THREE.MeshStandardMaterial({ color: 0x2a323b, roughness: 0.5, metalness: 0.3 });
    const body = new THREE.Mesh(new THREE.BoxGeometry(6, 9, 2.6), dark); g.add(body);
    const top = new THREE.Mesh(new THREE.BoxGeometry(4, 5, 1.2), new THREE.MeshStandardMaterial({ color: 0x4a5560, roughness: 0.4 })); top.position.z = 1.7; g.add(top);
    const nose = new THREE.Mesh(new THREE.BoxGeometry(3, 2, 1.6), new THREE.MeshStandardMaterial({ color: 0xd64545, emissive: 0x551515 })); nose.position.set(0, 5.2, 0); g.add(nose);
    const armGeo = new THREE.BoxGeometry(24, 1.1, 0.9);
    [Math.PI / 4, -Math.PI / 4].forEach(a => { const arm = new THREE.Mesh(armGeo, dark); arm.rotation.z = a; g.add(arm); });
    [[1, 1], [-1, 1], [1, -1], [-1, -1]].forEach(([sx, sy]) => {
      const x = sx * 8.5, y = sy * 8.5;
      const motor = new THREE.Mesh(new THREE.CylinderGeometry(1.5, 1.5, 1.8, 14).rotateX(Math.PI / 2), dark); motor.position.set(x, y, 1.1); g.add(motor);
      const rot = new THREE.Group(); rot.position.set(x, y, 2.3);
      const blade = new THREE.Mesh(new THREE.BoxGeometry(14, 0.9, 0.2), new THREE.MeshStandardMaterial({ color: 0xcfd6dd, roughness: 0.6 }));
      const blade2 = blade.clone(); blade2.rotation.z = Math.PI / 2; rot.add(blade, blade2);
      const disc = new THREE.Mesh(new THREE.CircleGeometry(7.2, 28), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.12, side: THREE.DoubleSide, depthWrite: false })); rot.add(disc);
      g.add(rot); rotors.push(rot);
    });
    light = new THREE.Mesh(new THREE.SphereGeometry(1.1, 12, 12), new THREE.MeshBasicMaterial({ color: GREEN })); light.position.set(0, -1.5, 2.6); g.add(light);
    return g;
  }

  // where the drone is right now, smoothed between the last two samples, which arrive a few times a second
  function pose() {
    if (!cur) return null;
    const k = prev ? Math.min(1, (performance.now() - tCur) / Math.max(80, tCur - tPrev)) : 1, a = prev || cur;
    return { lng: a.lng + (cur.lng - a.lng) * k, lat: a.lat + (cur.lat - a.lat) * k, alt: a.alt_m + (cur.alt_m - a.alt_m) * k, heading: camHeading };
  }

  // MapLibre aims a camera at a ground point from a distance set by the zoom. To put the camera at a given spot and height,
  // aim it at the ground point it looks at and pick the zoom whose viewing distance equals the distance to that point.
  function putCamera(lng, lat, alt, pitch, bearing) {
    const p = pitch * Math.PI / 180, b = bearing * Math.PI / 180, ground = alt * Math.tan(p), dist = Math.max(2, alt / Math.cos(p));
    const cLat = lat + Math.cos(b) * ground / M_LAT, cLng = lng + Math.sin(b) * ground / (M_LNG * Math.cos(lat * Math.PI / 180));
    const zoom = Math.log2(40075016 * Math.cos(lat * Math.PI / 180) * map.transform.cameraToCenterDistance / (512 * dist));
    map.jumpTo({ center: [cLng, cLat], zoom: Math.min(23, zoom), pitch, bearing });
  }

  // the camera is placed by hand every frame, so it never lags or jitters behind the drone
  function placeCamera() {
    raf = requestAnimationFrame(placeCamera);
    const q = pose(); if (!q || mode === "free" || !map || !ready) return;
    const h = cur.heading_deg; camHeading += (((((h - camHeading) % 360) + 540) % 360) - 180) * 0.12;
    const rad = camHeading * Math.PI / 180;
    let lng = q.lng, lat = q.lat, alt = q.alt + 2, pitch, bearing = camHeading;
    if (mode === "chase") {
      const back = 150, up = 65;  // metres behind and above, looking at the drone
      lng -= Math.sin(rad) * back / (M_LNG * Math.cos(q.lat * Math.PI / 180)); lat -= Math.cos(rad) * back / M_LAT; alt += up;
      pitch = Math.atan2(back, up) * 180 / Math.PI;
    } else if (mode === "fpv") {
      pitch = 90 - gimbal;
    } else { alt += 190; pitch = 0; bearing = 0; }
    putCamera(lng, lat, alt, Math.min(80, pitch), bearing);
    fpvHud(q);
  }

  /* ---------- the drone's own view: heads-up display and distance to the nearest restricted airspace ---------- */
  function ringDist(ring, x, y) {  // metres from a point to a polygon ring, 0 if inside
    let inside = false, best = Infinity;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const a = ring[i], b = ring[j];
      if ((a.y > y) !== (b.y > y) && x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x) inside = !inside;
      const dx = b.x - a.x, dy = b.y - a.y, l2 = dx * dx + dy * dy, t = l2 ? Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / l2)) : 0;
      best = Math.min(best, Math.hypot(x - (a.x + t * dx), y - (a.y + t * dy)));
    }
    return inside ? 0 : best;
  }
  function nearestZone(q) {
    let best = null; const me = local(q.lng, q.lat, 0);
    zoneGeo.forEach(z => z.rings.forEach(ring => {
      const d = ringDist(ring, me.x, me.y);
      if (!best || d < best.d) best = { d, name: z.name, red: z.red };
    }));
    return best;
  }
  function fpvHud(q) {
    const el = document.getElementById("fpvhud"); if (!el) return;
    el.classList.toggle("hidden", mode !== "fpv");
    if (mode !== "fpv") return;
    const now = performance.now();
    if (now - lastNear > 400) { lastNear = now; nearest = nearestZone(q); }
    const set = (id, v) => { const n = document.getElementById(id); if (n) n.textContent = v; };
    set("fAlt", Math.round(q.alt) + " m"); set("fHdg", String(Math.round((camHeading + 360) % 360)).padStart(3, "0")); set("fGim", gimbal + " deg down");
    set("fSpd", (cur.speed_mps || 0) + " m/s");
    const z = document.getElementById("fZone");
    if (z) {
      if (!nearest) z.textContent = "";
      else if (nearest.d === 0) { z.textContent = "Inside " + nearest.name; z.className = "fz breach"; }
      else { const eta = cur.speed_mps > 0.5 ? Math.round(nearest.d / cur.speed_mps) : null; z.textContent = nearest.name + ", " + Math.round(nearest.d) + " m" + (eta !== null && nearest.d < 600 ? ", about " + eta + " s at this speed" : ""); z.className = "fz " + (nearest.d < 150 ? "warning" : ""); }
    }
    const strip = document.getElementById("fStrip");
    if (strip) strip.style.backgroundPositionX = (-(camHeading % 360) * 4 + strip.clientWidth / 2) + "px";
  }

  const layer = {
    id: "drone3d", type: "custom", renderingMode: "3d",
    onAdd(m, gl) {
      camera = new THREE.Camera(); scene = new THREE.Scene();
      scene.add(new THREE.AmbientLight(0xffffff, 0.85));
      const sun = new THREE.DirectionalLight(0xffffff, 0.9); sun.position.set(-40, -60, 90); scene.add(sun);
      rig = buildDrone(); rig.scale.setScalar(1.7); scene.add(rig);
      shadow = new THREE.Mesh(new THREE.CircleGeometry(9, 28), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.38, depthWrite: false })); scene.add(shadow);
      drop = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 0, 1)]), new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.7 })); scene.add(drop);
      trailGeo = new THREE.BufferGeometry(); trailGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(MAX_TRAIL * 3), 3)); trailGeo.setDrawRange(0, 0);
      trailLine = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0xffffff })); trailLine.frustumCulled = false; scene.add(trailLine);
      renderer = new THREE.WebGLRenderer({ canvas: m.getCanvas(), context: gl, antialias: true }); renderer.autoClear = false;
      rig.visible = shadow.visible = drop.visible = false;
    },
    render(gl, matrix) {
      if (!origin) return;
      const q = pose();
      if (q) {
        const p = local(q.lng, q.lat, 0), alt = q.alt; rig.visible = shadow.visible = drop.visible = true;
        rig.position.set(p.x, p.y, alt + 2); rig.rotation.z = -q.heading * Math.PI / 180;
        shadow.position.set(p.x, p.y, 0.3); shadow.scale.setScalar(Math.max(0.5, 1 - alt / 400));
        drop.position.set(p.x, p.y, 0); drop.scale.set(1, 1, alt + 2);
        rotors.forEach((r, i) => { r.rotation.z += (i % 2 ? -1 : 1) * 1.4; });
        light.material.color.setHex(cur.status === "breach" ? RED : cur.status === "warning" ? AMBER : GREEN);
        rig.visible = mode !== "fpv";  // from inside the drone you do not see its own body
      }
      const s = mercO.meterInMercatorCoordinateUnits();
      const l = new THREE.Matrix4().makeTranslation(mercO.x, mercO.y, mercO.z).scale(new THREE.Vector3(s, -s, s));
      camera.projectionMatrix = new THREE.Matrix4().fromArray(matrix).multiply(l);
      renderer.resetState(); renderer.render(scene, camera); map.triggerRepaint();
    },
  };

  function circle(lng, lat, rKm) {
    const pts = []; for (let i = 0; i <= 48; i++) { const a = i / 48 * 2 * Math.PI; pts.push([lng + rKm * 1000 / (M_LNG * Math.cos(lat * Math.PI / 180)) * Math.sin(a), lat + rKm * 1000 / M_LAT * Math.cos(a)]); }
    return { type: "Polygon", coordinates: [pts] };
  }

  function buildRings() {
    zoneGeo.forEach(z => {
      const g = z.raw, polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
      z.rings = polys.map(poly => poly[0].map(([lng, lat]) => local(lng, lat, 0)));
    });
  }

  async function drawStatic() {
    const zones = { type: "FeatureCollection", features: [] }; zoneGeo = [];
    try {
      const fc = await api("/zones", { auth: false });
      fc.features.forEach(f => {
        const t = f.properties.zone_type, red = ZONE_GROUP[t] === "red";
        zones.features.push({ type: "Feature", geometry: f.geometry, properties: { name: f.properties.name, color: red ? C.red : C.amber, h: red ? 150 : 100 } });
        zoneGeo.push({ name: f.properties.name, red, raw: f.geometry });
      });
    } catch (e) { /* zones stay empty */ }
    const notices = { type: "FeatureCollection", features: [] };
    try { (await api("/notices/active", { auth: false })).forEach(n => { const g = n.area || n.geometry; if (g) notices.features.push({ type: "Feature", geometry: g, properties: { color: C.notice, h: 150 } }); }); } catch (e) { /* none */ }
    if (origin) buildRings();
    map.getSource("zones").setData(zones); map.getSource("notices").setData(notices);
  }

  function init(el, center) {
    if (map) return;
    const tiles = ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"];
    map = new maplibregl.Map({
      container: el, center: [center[1], center[0]], zoom: 16.5, pitch: 62, bearing: 0, maxPitch: 85, maxZoom: 24, attributionControl: false, antialias: true,
      style: { version: 8, sources: { sat: { type: "raster", tiles, tileSize: 256, maxzoom: 19, attribution: "Imagery © Esri" } }, layers: [{ id: "sat", type: "raster", source: "sat" }] },
    });
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    map.on("load", () => {
      const empty = { type: "FeatureCollection", features: [] };
      ["zones", "notices", "permit", "path"].forEach(id => map.addSource(id, { type: "geojson", data: empty }));
      const ext = (id, src, opacity) => map.addLayer({ id, type: "fill-extrusion", source: src, paint: { "fill-extrusion-color": ["get", "color"], "fill-extrusion-height": ["get", "h"], "fill-extrusion-base": 0, "fill-extrusion-opacity": opacity } });
      ext("zones", "zones", 0.32); ext("notices", "notices", 0.3); ext("permit", "permit", 0.22);
      map.addLayer({ id: "path", type: "line", source: "path", paint: { "line-color": "#f4f7fa", "line-width": 3, "line-opacity": 0.8 } });
      map.addLayer(layer);
      ready = true; drawStatic(); onReady.forEach(f => f()); onReady = [];
    });
    map.on("dragstart", () => { if (mode === "chase") setMode("free"); });
    window.addEventListener("keydown", e => { if (e.key === "z") gimbal = Math.max(0, gimbal - 5); if (e.key === "x") gimbal = Math.min(85, gimbal + 5); });
    cancelAnimationFrame(raf); placeCamera();
  }

  function setMode(m) { mode = m; const b = document.getElementById("camBtn"); if (b) b.textContent = MODE_LABEL[m]; if (m === "free" && cur && map) map.jumpTo({ center: [cur.lng, cur.lat], zoom: 17, pitch: 60, bearing: camHeading }); fpvHud(pose() || {}); }
  function when(fn) { ready ? fn() : onReady.push(fn); }

  return {
    init, setMode, setChase(on) { setMode(on ? "chase" : "free"); }, nextMode() { setMode(MODES[(MODES.indexOf(mode) + 1) % MODES.length]); }, get mode() { return mode; },
    refresh() { when(drawStatic); },
    setPermit(area, altMax) {
      when(() => map.getSource("permit").setData({ type: "FeatureCollection", features: area ? [{ type: "Feature", geometry: area, properties: { color: C.accent, h: altMax || 60 } }] : [] }));
    },
    reset() { origin = null; prev = cur = null; trail = []; when(() => { map.getSource("path").setData({ type: "FeatureCollection", features: [] }); if (trailGeo) trailGeo.setDrawRange(0, 0); }); },
    update(d) {
      when(() => {
        if (!origin) { origin = [d.lng, d.lat]; mercO = maplibregl.MercatorCoordinate.fromLngLat(origin, 0); camHeading = d.heading_deg; buildRings(); }
        const f = cur ? { ...d, lng: cur.lng + (d.lng - cur.lng) * 0.45, lat: cur.lat + (d.lat - cur.lat) * 0.45 } : d;  // soften the simulated GPS noise
        prev = cur; cur = d = f; tPrev = tCur; tCur = performance.now();
        trail.push([d.lng, d.lat, d.alt_m]); if (trail.length > MAX_TRAIL) trail.shift();
        const pos = trailGeo.attributes.position;
        trail.forEach((t, i) => { const p = local(t[0], t[1], t[2] + 2); pos.setXYZ(i, p.x, p.y, p.z); });
        pos.needsUpdate = true; trailGeo.setDrawRange(0, trail.length);
        trailLine.material.color.setHex(d.status === "breach" ? RED : d.status === "warning" ? AMBER : 0xffffff);
        map.getSource("path").setData({ type: "Feature", geometry: { type: "LineString", coordinates: trail.map(t => [t[0], t[1]]) } });
      });
    },
    resize() { if (map) map.resize(); },
  };
})();

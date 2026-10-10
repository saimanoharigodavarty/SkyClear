// Shared helpers for all SkyClear pages.
// Opened straight from a file (file://)? Talk to the local server instead of failing silently.
const API_BASE = location.protocol === "file:" ? "http://localhost:8000" : "";
// Everything about the place (city, map centre, drone classes) comes from the server through config.js. Nothing is typed into the pages.
const CFG = window.SKYCLEAR || { city: "", center: [20.59, 78.96], zoom: 5, searchViewbox: null, countryCode: "in", droneClasses: [], otpChannel: "email" };
const HYD = CFG.center;

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const VERDICT_LABEL = {
  can_fly: "No restriction found in our data",
  permission_needed: "Permission needed",
  prohibited: "Prohibited",
  cannot_determine: "Can't determine"
};
const VERDICT_MEANING = {
  can_fly: "Our data shows no restriction at this spot, for this drone and time. That is not a guarantee. Confirm on the official portal before you fly.",
  permission_needed: "You need permission from the authority before flying here. Request it below and we send it to the right officer.",
  prohibited: "Do not fly here. Pick another spot or another time.",
  cannot_determine: "Our data does not cover this spot. Ask the local authority or the official portal."
};
const STATUS_LABEL = { watching: "Watching", requested: "Pending", approved: "Approved", rejected: "Rejected", cancelled: "Cancelled", active: "Active", revoked: "Revoked", expired: "Expired", pending: "Pending", verified: "Verified", unverified: "Not verified" };
// Colours are read from the theme (CSS variables), so the map follows light and dark.
const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const C = { get red() { return cssVar("--red"); }, get amber() { return cssVar("--amber"); }, get green() { return cssVar("--green"); },
  get grey() { return cssVar("--grey"); }, get notice() { return cssVar("--notice"); }, get ink() { return cssVar("--ink"); }, get accent() { return cssVar("--accent"); } };
// Severity grouping: defence zones are prohibited, the rest need permission (or depend on the drone).
const ZONE_GROUP = { military: "red", airport: "amber", park: "amber", government: "amber" };
const zoneColor = type => (ZONE_GROUP[type] === "red" ? C.red : C.amber);

function saved(key, value) {
  try { if (value === undefined) return JSON.parse(localStorage.getItem(key)); if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value)); }
  catch (e) { return null; }
}

/* ---------- theme: light, dark, or follow the device ---------- */
const THEMES = ["system", "light", "dark"];
const THEME_LABEL = { system: "Theme: Auto", light: "Theme: Light", dark: "Theme: Dark" };
const themeChoice = () => (THEMES.includes(saved("skyclear.theme")) ? saved("skyclear.theme") : "system");
const isDark = () => themeChoice() === "dark" || (themeChoice() === "system" && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
function applyTheme() {
  const t = themeChoice();
  if (t === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  window.dispatchEvent(new Event("skyclear:theme"));
}
function setTheme(t) { saved("skyclear.theme", t); applyTheme(); document.querySelectorAll(".seg button").forEach(b => b.classList.toggle("on", b.dataset.theme === t)); }
if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (themeChoice() === "system") applyTheme(); });

/* ---------- session and API ---------- */
const session = () => saved("skyclear.session");
const token = () => (session() || {}).access_token || (session() || {}).token;
function setSession(t) { saved("skyclear.session", { access_token: t.access_token, token: t.access_token, refresh_token: t.refresh_token, user: t.user }); }
function clearSession() { saved("skyclear.session", null); }

function serverDown(show) {
  let bar = $("serverDown");
  if (!show) { if (bar) bar.remove(); return; }
  if (bar) return;
  bar = document.createElement("div"); bar.id = "serverDown"; bar.className = "serverdown"; bar.setAttribute("role", "alert");
  bar.innerHTML = 'Cannot reach the SkyClear server. Start it with <code>./run.sh</code> in the project folder, then reload this page.';
  document.body.insertBefore(bar, document.body.firstChild);
}

let refreshing = null;
function refreshTokens() {
  const s = session();
  if (!s || !s.refresh_token) return Promise.reject(new Error("no session"));
  refreshing = refreshing || fetch(API_BASE + "/auth/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: s.refresh_token }) })
    .then(async r => { if (!r.ok) throw new Error("session ended"); setSession(await r.json()); })
    .finally(() => { refreshing = null; });
  return refreshing;
}

// fetch with the access token, one automatic refresh when it has expired.
async function authFetch(path, opts = {}, auth = true) {
  const go = () => {
    const headers = { ...(opts.headers || {}) };
    if (auth && token()) headers.Authorization = "Bearer " + token();
    return fetch(API_BASE + path, { ...opts, headers });
  };
  let res;
  try { res = await go(); serverDown(false); }
  catch (e) { serverDown(true); throw new Error("Cannot reach the SkyClear server. Is it running?"); }
  if (res.status === 401 && auth && session()) {
    let detail = ""; try { detail = (await res.clone().json()).detail; } catch (e) { /* keep */ }
    if (detail === "token_expired") {
      try { await refreshTokens(); res = await go(); }
      catch (e) { clearSession(); if (document.body.dataset.requireAuth) location.href = "account.html?expired=1"; }
    } else { clearSession(); if (document.body.dataset.requireAuth) location.href = "account.html?expired=1"; }
  }
  return res;
}

async function api(path, { method = "GET", body, auth = true } = {}) {
  const opts = { method };
  if (body !== undefined) { opts.headers = { "Content-Type": "application/json" }; opts.body = JSON.stringify(body); }
  const res = await authFetch(path, opts, auth);
  if (!res.ok) {
    let detail = res.status + "";
    try { const j = await res.json(); detail = typeof j.detail === "string" ? j.detail : (j.detail || []).map(d => d.msg).join(", ") || detail; } catch (e) { /* keep status */ }
    const err = new Error(detail); err.status = res.status; throw err;
  }
  return res.json();
}

async function signOut() {
  const s = session();
  if (s && s.refresh_token) { try { await fetch(API_BASE + "/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: s.refresh_token }) }); } catch (e) { /* signing out anyway */ } }
  clearSession(); location.href = "account.html";
}

/* ---------- formatting ---------- */
function fmtWhen(iso) {
  const d = new Date(iso);
  return isNaN(d) ? String(iso) : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
function toLocalInput(d) { const x = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return x.toISOString().slice(0, 16); }
const toISO = v => new Date(v).toISOString();
function skeleton() { return '<div class="skel big"></div><div class="skel"></div><div class="skel w80"></div><div class="skel w50"></div>'; }

/* ---------- header ---------- */
function header(active) {
  const s = session();
  $("top").innerHTML = `
    <a class="brand" href="index.html">Sky<b>Clear</b>${CFG.city ? `<small>${esc(CFG.city)}</small>` : ""}</a>
    <nav class="nav">
      <a href="index.html" class="${active === "pilot" ? "on" : ""}">Pilot</a>
      <a href="official.html" class="${active === "official" ? "on" : ""}">Authority</a>
      <a href="display.html" class="${active === "display" ? "on" : ""}">Demo screen</a>
      <a href="guide.html" class="${active === "guide" ? "on" : ""}">Guide</a>
    </nav>
    <div class="who">
      <div class="seg" role="group" aria-label="Theme">${THEMES.map(t => `<button type="button" data-theme="${t}" class="${themeChoice() === t ? "on" : ""}" aria-pressed="${themeChoice() === t}">${{ system: "Auto", light: "Light", dark: "Dark" }[t]}</button>`).join("")}</div>
      ${s ? `<span>${esc(s.user.name)}</span><span class="role">${esc(s.user.role)}</span><a href="#" id="signout">Sign out</a>`
          : `<a class="btn-ghost" href="account.html">Sign in</a><a class="btn-sm" href="account.html?tab=register">Create account</a>`}
    </div>`;
  document.querySelectorAll(".seg button").forEach(b => b.addEventListener("click", () => setTheme(b.dataset.theme)));
  const out = $("signout");
  if (out) out.addEventListener("click", e => { e.preventDefault(); signOut(); });
}

/* ---------- map ---------- */
function circleOf(n) { return L.geoJSON(n.area || n.geometry, { style: { color: C.notice, weight: 2, dashArray: "6 5", fillColor: C.notice, fillOpacity: 0.12 }, interactive: false }); }

// Base map: centred on the configured city, calm basemap that follows the theme, satellite toggle, zones grouped by severity, active notices, clickable legend.
function makeMap(opts = {}) {
  const map = L.map("map", { zoomControl: false, minZoom: 5 }).setView(HYD, CFG.zoom);
  L.control.zoom({ position: "topright" }).addTo(map);
  L.control.scale({ metric: true, imperial: false, position: "bottomright" }).addTo(map);
  const tile = { maxNativeZoom: 16, maxZoom: 18, attribution: "Tiles © Esri, map data © OpenStreetMap contributors" };
  const esri = (tone, name) => `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${tone}_Gray_${name}/MapServer/tile/{z}/{y}/{x}`;
  const plain = tone => L.layerGroup([L.tileLayer(esri(tone, "Base"), tile), L.tileLayer(esri(tone, "Reference"), { ...tile, attribution: "", pane: "shadowPane" })]);
  const light = plain("Light"), dark = plain("Dark");
  // Satellite: Esri World Imagery (sharp down to rooftops, zoom 19) with place names on top.
  const sat = L.layerGroup([L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxNativeZoom: 19, maxZoom: 20, attribution: "Imagery © Esri, Maxar, Earthstar Geographics" }),
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 19, maxZoom: 20, attribution: "", pane: "shadowPane" })]);
  let satOn = !!opts.satellite, current = null;
  const show = () => {
    const want = satOn ? sat : (isDark() ? dark : light);
    map.getContainer().classList.toggle("sat-on", satOn);
    if (current === want) return;
    if (current) map.removeLayer(current);
    current = want; want.addTo(map);
  };
  show();
  window.addEventListener("skyclear:theme", show);

  const control = (text, title, onclick) => new (L.Control.extend({ options: { position: "topright" }, onAdd() {
    const d = L.DomUtil.create("div", "leaflet-bar reset"); const a = L.DomUtil.create("a", "", d);
    a.href = "#"; a.textContent = text; a.title = title;
    L.DomEvent.on(a, "click", e => { L.DomEvent.preventDefault(e); onclick(a); }); return d; } }))().addTo(map);
  control(CFG.city || "Reset view", "Back to the start view", () => map.setView(HYD, CFG.zoom));
  const satBtn = control(opts.satellite ? "Map" : "Satellite", "Switch between map and satellite", a => { satOn = !satOn; a.textContent = satOn ? "Map" : "Satellite"; show(); });

  const layers = { red: L.layerGroup().addTo(map), amber: L.layerGroup().addTo(map), notices: L.layerGroup().addTo(map), work: L.layerGroup().addTo(map) };
  const legend = $("legend");
  if (legend) {
    const rows = [["red", "var(--red)", "Red: flying prohibited"], ["amber", "var(--amber)", "Yellow: permission needed"], ["notices", "var(--notice)", "Official notice, time limited"]];
    legend.innerHTML = '<details' + (window.innerWidth > 860 ? " open" : "") + '><summary class="label" style="margin:0;cursor:pointer">Map layers</summary>' + rows.map(([k, col, text]) =>
      `<label class="lg"><input type="checkbox" data-layer="${k}" checked><i style="border-color:${col};background:color-mix(in srgb, ${col} 14%, transparent);${k === "notices" ? "border-style:dashed" : ""}"></i>${text}</label>`).join("")
      + '<div class="lg" style="cursor:default"><i style="border-color:var(--green);background:color-mix(in srgb, var(--green) 14%, transparent)"></i>Green: no restriction found in our data (not painted)</div></details>';
    legend.querySelectorAll("input").forEach(box => box.addEventListener("change", () => {
      const l = layers[box.dataset.layer]; box.checked ? l.addTo(map) : map.removeLayer(l); }));
  }
  const labelZoom = () => { const k = map.getContainer().classList; k.toggle("zoom-low", map.getZoom() < 10); k.toggle("zoom-mid", map.getZoom() < 13); };
  map.on("zoomend", labelZoom); labelZoom();
  return { map, layers };
}

// Search box on the map: our zones first (Atlas Search later), then places from OpenStreetMap's Nominatim.
function bindMapSearch(map, onPick) {
  const input = $("mapSearch"), list = $("mapResults");
  if (!input) return;
  let timer = null, seq = 0;
  const close = () => list.classList.add("hidden");
  const pick = (lat, lng, zoom) => { map.flyTo([lat, lng], zoom, { duration: 0.8 }); close(); if (onPick) onPick({ lat, lng }); };
  async function run() {
    const q = input.value.trim(), mine = ++seq;
    if (q.length < 2) return close();
    let zones = [], places = [];
    try { zones = await api("/zones/search?q=" + encodeURIComponent(q), { auth: false }); } catch (e) { /* offline */ }
    try {
      const near = map.getCenter();
      places = await api(`/places/search?q=${encodeURIComponent(q)}&lat=${near.lat}&lng=${near.lng}`, { auth: false });
    } catch (e) { /* Mappls is optional */ }
    if (!places.length) try {
      const vb = CFG.searchViewbox ? "&viewbox=" + CFG.searchViewbox.join(",") : "";
      const r = await fetch("https://nominatim.openstreetmap.org/search?format=jsonv2&limit=4&countrycodes=" + CFG.countryCode + vb + "&q=" + encodeURIComponent(q));
      places = r.ok ? (await r.json()).map(p => ({ name: p.display_name.split(",").slice(0, 2).join(","), address: "", lat: Number(p.lat), lng: Number(p.lon), provider: "OpenStreetMap place search" })) : [];
    } catch (e) { /* offline */ }
    if (mine !== seq) return;
    const items = [...zones.map(z => ({ title: z.name, sub: "Restricted zone, " + z.zone_type, lat: z.center.lat, lng: z.center.lng, zoom: 13 })),
      ...places.map(p => ({ title: p.name, sub: p.provider || "Place", lat: p.lat, lng: p.lng, eloc: p.eloc, zoom: 15 }))];
    list.innerHTML = items.length ? items.map((it, i) => `<li data-i="${i}">${esc(it.title)}<small>${esc(it.sub)}</small></li>`).join("") : '<li class="none">Nothing found. Try a zone name or an area in Hyderabad.</li>';
    list.classList.remove("hidden");
    list.querySelectorAll("li[data-i]").forEach(li => li.addEventListener("click", async () => {
      const it = items[Number(li.dataset.i)]; input.value = it.title;
      if (it.eloc) { try { const detail = await api("/places/" + encodeURIComponent(it.eloc), { auth: false }); pick(detail.lat, detail.lng, it.zoom); } catch (e) { li.querySelector("small").textContent = "Mappls could not provide coordinates for this place."; } }
      else pick(it.lat, it.lng, it.zoom);
    }));
  }
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 300); });
  input.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
  document.addEventListener("click", e => { if (!e.target.closest(".mapsearch")) close(); });
}

function zoneStyle(type, strong) { const col = zoneColor(type); return { color: col, weight: strong ? 2.5 : 1.5, fillColor: col, fillOpacity: strong ? 0.1 : 0.07 }; }

async function drawZones(layers) {
  layers.red.clearLayers(); layers.amber.clearLayers();
  try {
    const fc = await api("/zones", { auth: false });
    fc.features.forEach(f => {
      const p = f.properties, layer = ZONE_GROUP[p.zone_type] === "red" ? layers.red : layers.amber;
      // Not interactive: clicks must reach the map so a pilot can pick a spot inside a zone.
      const shape = L.geoJSON(f, { style: () => zoneStyle(p.zone_type), interactive: false });
      const major = p.zone_type === "military" || p.zone_type === "airport";
      shape.bindTooltip(esc(p.name), { permanent: true, direction: "center", className: "zlabel" + (major ? "" : " minor"), interactive: false });
      shape.addTo(layer);
    });
  } catch (e) { /* the check result still draws the zones it needs */ }
}
async function drawNotices(layer) {
  layer.clearLayers();
  try {
    const list = await api("/notices/active", { auth: false });
    list.forEach(n => circleOf(n).bindTooltip(esc(n.title), { permanent: true, direction: "top", className: "zlabel notice", interactive: false }).addTo(layer));
  } catch (e) { /* the static sample notice still applies in checks */ }
}

// A square target pin, crisp at any zoom.
function pinIcon(extra = "") { return L.divIcon({ className: "", html: `<div class="pin ${extra}"></div>`, iconSize: [22, 22], iconAnchor: [11, 11] }); }

/* ---------- uploads, QR, badges ---------- */
async function uploadFile(file) {
  const fd = new FormData(); fd.append("file", file);
  const res = await authFetch("/uploads", { method: "POST", body: fd });
  if (!res.ok) { let d = res.status + ""; try { d = (await res.json()).detail || d; } catch (e) { /* keep */ } throw new Error(d); }
  return (await res.json()).file_id;
}
async function openFile(fileId) {
  const res = await authFetch("/uploads/" + fileId);
  if (!res.ok) throw new Error("Cannot open the file");
  window.open(URL.createObjectURL(await res.blob()), "_blank");
}
function qrSvg(text) {
  if (typeof qrcode === "undefined") return "";
  const q = qrcode(0, "M"); q.addData(text); q.make();
  return q.createSvgTag({ cellSize: 3, margin: 0, scalable: true });
}
const verifyBadge = v => { const s = (v && v.status) || "unverified"; return `<span class="tag ${esc(s === "verified" ? "approved" : s === "rejected" ? "rejected" : s === "pending" ? "requested" : "watching")}">${esc(STATUS_LABEL[s] || s)}</span>`; };

/* ---------- flight lifecycle ---------- */
const FLOW_PERMISSION = ["Requested", "Approved", "Cleared", "Flying", "Landed"];
const FLOW_WATCH = ["Planned", "Cleared", "Flying", "Landed"];
const FLOW_AT = { permission: { requested: 0, approved: 1, cleared: 2, flying: 3, completed: 4 }, watch: { watching: 0, cleared: 1, flying: 2, completed: 3 } };
const FLOW_END = { rejected: "Rejected", cancelled: "Cancelled", revoked: "Permit revoked", recalled: "Recalled" };
// The stages a flight goes through, with where this one is now. A flight that ended early shows why in red.
function flowHTML(f) {
  const kind = f.kind === "permission" ? "permission" : "watch", names = kind === "permission" ? FLOW_PERMISSION : FLOW_WATCH;
  const at = FLOW_AT[kind][f.status], ended = FLOW_END[f.status];
  const stage = at !== undefined ? at : (f.status === "recalled" ? names.length - 2 : f.launched_at ? names.length - 2 : f.permit_id || f.status === "revoked" ? 1 : 0);
  const chips = names.map((n, i) => `<span class="${ended ? (i < stage ? "done" : i === stage && f.status === "recalled" ? "done" : "") : i < stage ? "done" : i === stage ? "on" : ""}">${esc(n)}</span>`).join("");
  return `<div class="flow">${chips}${ended ? `<span class="end">${esc(ended)}</span>` : ""}</div>`;
}

/* ---------- live drones on the map ---------- */
function droneIcon(d) {
  const cls = d.phase === "returning" ? "returning" : d.status;
  return L.divIcon({ className: "", html: `<div class="drone-pin ${cls}"><i style="transform:rotate(${Math.round(d.heading_deg)}deg)"></i></div>`, iconSize: [22, 22], iconAnchor: [11, 12] });
}
// Polls /live/drones and keeps one marker per flight. A pilot sees their own drone, an officer sees every drone, a visitor sees background traffic.
function createLive(map, layer, onData, everyMs = 2000) {
  const markers = new Map();
  let timer = null;
  async function tick() {
    try {
      const out = await api("/live/drones");
      const seen = new Set();
      out.drones.forEach(d => {
        const key = d.flight_id; seen.add(key);
        const ll = [d.lat, d.lng];
        const flight = d.kind === "flight";
        let m = markers.get(key);
        if (!m) {
          m = flight ? L.marker(ll, { icon: droneIcon(d), keyboard: false, zIndexOffset: 1000 }) : L.circleMarker(ll, { radius: 3.5, weight: 1, color: C.grey, fillColor: C.grey, fillOpacity: 0.7 });
          m.addTo(layer); markers.set(key, m);
        }
        m.setLatLng(ll);
        if (flight) m.setIcon(droneIcon(d));
        else m.setStyle({ color: d.status === "breach" ? C.red : d.status === "warning" ? C.amber : C.grey, fillColor: d.status === "breach" ? C.red : d.status === "warning" ? C.amber : C.grey });
        m.bindTooltip(`${esc(d.drone_id)}, ${Math.round(d.alt_m)} m, ${d.speed_mps} m/s${d.zone ? ", " + esc(d.zone) : ""}`, { direction: "top", className: "zlabel", sticky: true });
      });
      markers.forEach((m, k) => { if (!seen.has(k)) { layer.removeLayer(m); markers.delete(k); } });
      if (onData) onData(out.drones);
    } catch (e) { /* server busy, the next tick tries again */ }
  }
  return { start() { if (!timer) { tick(); timer = setInterval(tick, everyMs); } }, stop() { clearInterval(timer); timer = null; }, tick, markers };
}

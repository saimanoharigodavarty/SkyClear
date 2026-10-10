// Shared helpers for all SkyClear pages.
const API_BASE = "";  // empty = same origin as the backend
const HYD = [17.385, 78.4867];

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const VERDICT_LABEL = {
  can_fly: "No restriction found in our data",
  permission_needed: "Permission needed",
  prohibited: "Prohibited",
  cannot_determine: "Can't determine"
};
const STATUS_LABEL = { watching: "Watching", requested: "Pending", approved: "Approved", rejected: "Rejected", cancelled: "Cancelled", active: "Active", revoked: "Revoked", expired: "Expired", pending: "Pending", verified: "Verified", unverified: "Not verified" };
const RED = "#b3261e", AMBER = "#a15c00", NOTICE_COLOR = "#1f4e79";
// Severity grouping: defence zones are prohibited, the rest need permission (or depend on the drone).
const ZONE_GROUP = { military: "red", airport: "amber", park: "amber", government: "amber" };
const zoneColor = type => (ZONE_GROUP[type] === "red" ? RED : AMBER);

function saved(key, value) {
  try { if (value === undefined) return JSON.parse(localStorage.getItem(key)); if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value)); }
  catch (e) { return null; }
}
const session = () => saved("skyclear.session");
const token = () => (session() || {}).token;

async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth && token()) headers.Authorization = "Bearer " + token();
  let res;
  try { res = await fetch(API_BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) }); }
  catch (e) { throw new Error("Cannot reach the SkyClear server. Is it running?"); }
  if (res.status === 401 && token()) { saved("skyclear.session", null); }
  if (!res.ok) {
    let detail = res.status + "";
    try { const j = await res.json(); detail = typeof j.detail === "string" ? j.detail : (j.detail || []).map(d => d.msg).join(", ") || detail; } catch (e) { /* keep status */ }
    throw new Error(detail);
  }
  return res.json();
}

function fmtWhen(iso) {
  const d = new Date(iso);
  return isNaN(d) ? String(iso) : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
function toLocalInput(d) { const x = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return x.toISOString().slice(0, 16); }
const toISO = v => new Date(v).toISOString();

function skeleton() { return '<div class="skel big"></div><div class="skel"></div><div class="skel w80"></div><div class="skel w50"></div>'; }

function header(active) {
  const s = session();
  $("top").innerHTML = `
    <a class="brand" href="index.html">SkyClear<small>Hyderabad prototype</small></a>
    <nav class="nav">
      <a href="index.html" class="${active === "pilot" ? "on" : ""}">Pilot</a>
      <a href="official.html" class="${active === "official" ? "on" : ""}">Authority</a>
    </nav>
    <div class="who">${s ? `<span>${esc(s.user.name)}</span><span class="role">${esc(s.user.role)}</span><a href="#" id="signout">Sign out</a>`
                          : `<a href="account.html">Sign in</a>`}</div>`;
  const out = $("signout");
  if (out) out.addEventListener("click", e => { e.preventDefault(); saved("skyclear.session", null); location.href = "account.html"; });
}

function footer() {
  return '<footer class="foot"><a href="terms.html">Terms of Service</a><a href="privacy.html">Privacy Policy</a>Decision support only, not legal permission. Zones and rules are sample or derived data until verified.</footer>';
}

function circleOf(n) { return L.geoJSON(n.area || n.geometry, { style: { color: NOTICE_COLOR, weight: 2, dashArray: "6 5", fillColor: NOTICE_COLOR, fillOpacity: 0.1 }, interactive: false }); }

// Base map: Hyderabad, calm light basemap, zones grouped by severity, active notices, clickable legend.
function makeMap() {
  const map = L.map("map", { zoomControl: false, minZoom: 5 }).setView(HYD, 11);
  L.control.zoom({ position: "topright" }).addTo(map);
  L.control.scale({ metric: true, imperial: false, position: "bottomright" }).addTo(map);
  const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  // Esri gray canvas: calm, no API key. Reference layer adds place names on top.
  const esri = name => `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${dark ? "Dark" : "Light"}_Gray_${name}/MapServer/tile/{z}/{y}/{x}`;
  const tile = { maxNativeZoom: 16, maxZoom: 18, attribution: "Tiles © Esri, map data © OpenStreetMap contributors" };
  const plain = L.layerGroup([L.tileLayer(esri("Base"), tile), L.tileLayer(esri("Reference"), { ...tile, attribution: "", pane: "shadowPane" })]).addTo(map);
  // Satellite: Sentinel-2 cloudless by EOX (free, non-commercial). Place names on top.
  const sat = L.layerGroup([L.tileLayer("https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2021_3857/default/g/{z}/{y}/{x}.jpg",
    { maxNativeZoom: 13, maxZoom: 18, attribution: "Sentinel-2 cloudless by EOX (contains modified Copernicus Sentinel data 2021)" }),
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}", { ...tile, attribution: "", pane: "shadowPane" })]);
  const Base = L.Control.extend({ options: { position: "topright" }, onAdd() {
    const d = L.DomUtil.create("div", "leaflet-bar basemap"); const a = L.DomUtil.create("a", "", d);
    a.href = "#"; a.textContent = "Satellite"; a.title = "Switch between map and satellite";
    let on = false;
    L.DomEvent.on(a, "click", e => { L.DomEvent.preventDefault(e); on = !on;
      if (on) { map.removeLayer(plain); sat.addTo(map); } else { map.removeLayer(sat); plain.addTo(map); }
      a.textContent = on ? "Map" : "Satellite"; }); return d; } });
  const layers = { red: L.layerGroup().addTo(map), amber: L.layerGroup().addTo(map), notices: L.layerGroup().addTo(map), work: L.layerGroup().addTo(map) };

  const Reset = L.Control.extend({ options: { position: "topright" }, onAdd() {
    const d = L.DomUtil.create("div", "leaflet-bar reset"); const a = L.DomUtil.create("a", "", d);
    a.href = "#"; a.textContent = "Hyderabad"; a.title = "Back to Hyderabad";
    L.DomEvent.on(a, "click", e => { L.DomEvent.preventDefault(e); map.setView(HYD, 11); }); return d; } });
  new Reset().addTo(map);
  new Base().addTo(map);

  const legend = $("legend");
  if (legend) {
    const rows = [["red", RED, "Red: flying prohibited"], ["amber", AMBER, "Yellow: permission needed"], ["notices", NOTICE_COLOR, "Official notice, time limited"]];
    legend.innerHTML = '<div class="label" style="margin:0 0 6px">Layers</div>' + rows.map(([k, col, text]) =>
      `<label class="lg"><input type="checkbox" data-layer="${k}" checked><i style="border-color:${col};background:${col}22;${k === "notices" ? "border-style:dashed" : ""}"></i>${text}</label>`).join("") + '<div class="lg" style="cursor:default"><i style="border-color:#1a7f37;background:#1a7f3722"></i>Green: no restriction found in our data (not painted)</div>';
    legend.querySelectorAll("input").forEach(box => box.addEventListener("change", () => {
      const l = layers[box.dataset.layer]; box.checked ? l.addTo(map) : map.removeLayer(l); }));
  }
  const labelZoom = () => { const k = map.getContainer().classList; k.toggle("zoom-low", map.getZoom() < 10); k.toggle("zoom-mid", map.getZoom() < 13); };
  map.on("zoomend", labelZoom); labelZoom();
  return { map, layers };
}

function zoneStyle(type, strong) { const col = zoneColor(type); return { color: col, weight: strong ? 3 : 1.5, fillColor: col, fillOpacity: strong ? 0.22 : 0.08 }; }

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
    list.forEach(n => circleOf(n).bindTooltip(esc(n.title), { permanent: true, direction: "center", className: "zlabel notice", interactive: false }).addTo(layer));
  } catch (e) { /* the static sample notice still applies in checks */ }
}

// A square target pin, crisp at any zoom.
function pinIcon(extra = "") { return L.divIcon({ className: "", html: `<div class="pin ${extra}"></div>`, iconSize: [22, 22], iconAnchor: [11, 11] }); }

// Upload a file (JPG, PNG, PDF up to 5 MB). Returns the file id.
async function uploadFile(file) {
  const fd = new FormData(); fd.append("file", file);
  let res;
  try { res = await fetch(API_BASE + "/uploads", { method: "POST", headers: { Authorization: "Bearer " + token() }, body: fd }); }
  catch (e) { throw new Error("Cannot reach the SkyClear server. Is it running?"); }
  if (!res.ok) { let d = res.status + ""; try { d = (await res.json()).detail || d; } catch (e) { /* keep */ } throw new Error(d); }
  return (await res.json()).file_id;
}
// Open an uploaded file in a new tab (needs the auth header, so fetch it first).
async function openFile(fileId) {
  const res = await fetch(API_BASE + "/uploads/" + fileId, { headers: { Authorization: "Bearer " + token() } });
  if (!res.ok) throw new Error("Cannot open the file");
  window.open(URL.createObjectURL(await res.blob()), "_blank");
}
function qrSvg(text) {
  if (typeof qrcode === "undefined") return "";
  const q = qrcode(0, "M"); q.addData(text); q.make();
  return q.createSvgTag({ cellSize: 3, margin: 0, scalable: true });
}
const verifyBadge = v => { const s = (v && v.status) || "unverified"; return `<span class="tag ${esc(s === "verified" ? "approved" : s === "rejected" ? "rejected" : s === "pending" ? "requested" : "watching")}">${esc(STATUS_LABEL[s] || s)}</span>`; };

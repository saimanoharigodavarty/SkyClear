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
const STATUS_LABEL = { watching: "Watching", requested: "Pending", approved: "Approved", rejected: "Rejected", cancelled: "Cancelled", active: "Active" };
const ZONE_COLOR = { airport: "#b3261e", military: "#b3261e", park: "#a15c00", government: "#a15c00" };
const NOTICE_COLOR = "#1f4e79";

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

function circleOf(n) { return L.geoJSON(n.area || n.geometry, { style: { color: NOTICE_COLOR, weight: 2, dashArray: "6 5", fillOpacity: 0.12 } }); }

// Base map: Hyderabad, all zones, all active notices.
function makeMap() {
  const map = L.map("map", { zoomControl: true }).setView(HYD, 11);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap contributors", maxZoom: 19 }).addTo(map);
  const layers = { zones: L.layerGroup().addTo(map), notices: L.layerGroup().addTo(map), work: L.layerGroup().addTo(map) };
  return { map, layers };
}
async function drawZones(layer) {
  layer.clearLayers();
  try {
    const fc = await api("/zones", { auth: false });
    L.geoJSON(fc, {
      style: f => ({ color: ZONE_COLOR[f.properties.zone_type] || "#a15c00", weight: 1.5, fillOpacity: 0.14 }),
      onEachFeature: (f, l) => l.bindPopup(`<b>${esc(f.properties.name)}</b><br>${esc(f.properties.zone_type)}<br><span class="small">${esc(f.properties.source)}</span>`)
    }).addTo(layer);
  } catch (e) { /* the check result still draws the zones it needs */ }
}
async function drawNotices(layer) {
  layer.clearLayers();
  try {
    const list = await api("/notices/active", { auth: false });
    list.forEach(n =>
      circleOf(n).bindPopup(`<b>${esc(n.title)}</b><br>${esc(fmtWhen(n.starts_at))} to ${esc(fmtWhen(n.ends_at))}<br><span class="small">${esc(n.source || "")}</span>`).addTo(layer));
  } catch (e) { /* notices need sign-in; the static sample notice still applies in checks */ }
}

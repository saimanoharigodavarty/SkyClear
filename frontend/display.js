// The big screen for a presentation: satellite view that follows the drone, a status banner, live numbers, an event log,
// and a QR code so a phone can fly it. Sign in as the pilot on this computer, pick a flight, scan the QR with a phone.
document.body.dataset.requireAuth = "1";
const sess = session();
if (!sess) location.href = "account.html?next=display.html";
const { map, layers } = makeMap({ satellite: true });
map.zoomControl && map.zoomControl.setPosition("bottomleft");
let FID = new URLSearchParams(location.search).get("flight"), info = null, timer = null, trail = null, marker = null, followed = false, lastStatus = "idle";
const trailPts = [], keys = {};
const live = L.layerGroup().addTo(map);
$("whoLine").textContent = sess ? sess.user.name + ", " + sess.user.role : "";
let is3d = saved("display3d") !== false;
function setView(on) {
  is3d = on; saved("display3d", on);
  $("map3d").classList.toggle("hidden", !on); $("map").classList.toggle("hidden", on);
  $("viewBtn").textContent = on ? "2D map" : "3D view"; $("camBtn").classList.toggle("hidden", !on);
  if (!on) $("fpvhud").classList.add("hidden");
  if (on) { View3D.init("map3d", [HYD[0], HYD[1]]); View3D.resize(); } else map.invalidateSize();
}
$("viewBtn").addEventListener("click", () => setView(!is3d));
$("camBtn").addEventListener("click", () => View3D.nextMode());
$("fs").addEventListener("click", () => document.documentElement.requestFullscreen && document.documentElement.requestFullscreen());
drawZones(layers); drawNotices(layers.notices);
window.addEventListener("skyclear:theme", () => { drawZones(layers); drawNotices(layers.notices); });

function banner(kind, big, sub) {
  const b = $("banner2"); b.className = "hud " + kind;
  b.innerHTML = `<div class="big">${esc(big)}</div><div class="sub">${esc(sub || "")}</div>`;
}

/* ---------- choosing a flight ---------- */
const LAUNCHABLE = ["approved", "watching", "cleared", "flying"];
async function chooser() {
  $("chooser").classList.remove("hidden");
  try {
    const flights = (await api("/flights")).filter(f => (LAUNCHABLE.includes(f.status) || f.status === "recalled") && new Date(f.end) > new Date());  // expired windows cannot take off
    if (!flights.length) {
      $("chooseBody").innerHTML = `<p>No flight is ready to fly. Sign in as the demo pilot and get a flight approved first: request permission in a yellow zone, or save a flight in a green area.</p><a class="btn-sm" href="index.html">Open the pilot app</a>`;
      return;
    }
    $("chooseBody").innerHTML = `<p class="small" style="margin-top:0">Pick the flight to fly. It runs preflight, takes off, and shows a QR code for the phone.</p>` + flights.map(f => `
      <div class="item"><div class="head"><span class="title mono">${esc(f.flight_id)}</span><span class="tag ${esc(f.status)}">${esc(STATUS_LABEL[f.status] || f.status)}</span></div>
        <div>${esc(f.drone_name)}, ${f.zones.length ? esc(f.zones.join(", ")) : "open area"}</div>
        <div class="meta">${f.permit ? "Permit " + esc(f.permit.permit_id) + ", max " + esc(f.permit.alt_max_m) + " m" : "No permit needed here"}</div>
        <button type="button" data-go="${esc(f.flight_id)}" style="margin-top:8px">${f.status === "flying" ? "Show this flight" : "Take off with phone control"}</button><div id="cm-${esc(f.flight_id)}"></div></div>`).join("");
    $("chooseBody").querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => start(b.dataset.go, flights.find(f => f.flight_id === b.dataset.go))));
  } catch (e) { $("chooseBody").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}

async function start(fid, f) {
  const msg = $("cm-" + fid);
  try {
    if (f && f.status !== "flying" && f.status !== "recalled") {
      if (f.status !== "cleared") { const pre = await api(`/flights/${fid}/preflight`, { method: "POST" }); if (!pre.cleared) throw new Error("Not cleared: " + pre.reasons.join("; ")); }
      await api(`/flights/${fid}/launch`, { method: "POST", body: { mode: "manual" } });
    }
    FID = fid; follow();
  } catch (e) { if (msg) msg.innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}

/* ---------- following the flight ---------- */
const DRONE_ICON = d => L.divIcon({ className: "", html: `<div class="drone-pin ${d.phase === "returning" ? "returning" : d.status}" style="width:34px;height:34px"><i style="width:28px;height:32px;transform:rotate(${Math.round(d.heading_deg)}deg)"></i></div>`, iconSize: [34, 34], iconAnchor: [17, 18] });

async function follow() {
  $("chooser").classList.add("hidden"); $("endcard").classList.add("hidden");
  history.replaceState(null, "", "?flight=" + FID);
  info = await api(`/flights/${FID}/info`);
  const pilot = sess.user.role === "pilot";
  if (info.permit) {
    L.geoJSON(info.permit.area, { style: { color: C.accent, weight: 3, dashArray: "8 6", fillColor: C.accent, fillOpacity: 0.1 }, interactive: false }).addTo(live)
      .bindTooltip("Permit area", { permanent: true, direction: "center", className: "zlabel", interactive: false });
    $("permitLine").textContent = `Permit ${info.permit.permit_id}: stay inside the dashed area, below ${info.permit.alt_max_m} m.`;
  } else $("permitLine").textContent = "No permit needed here. Restricted zones still apply.";
  map.setView([info.lat, info.lng], 17);
  miniPermit = info.permit ? info.permit.area : null; miniAt = 0; miniTrail.setLatLngs([]);
  View3D.reset(); View3D.setPermit(info.permit ? info.permit.area : null, info.permit ? info.permit.alt_max_m : 0); View3D.setChase(true);
  ["telepanel", "eventpanel"].forEach(i => $(i).classList.remove("hidden"));
  $("keyhint").classList.toggle("hidden", !pilot);
  if (pilot) { await showQr(); $("pairpanel").classList.remove("hidden"); }
  clearInterval(timer); timer = setInterval(poll, 250); poll();
}

async function showQr() {
  try {
    const [pair, lan] = await Promise.all([api(`/flights/${FID}/pair`, { method: "POST" }), api("/lan", { auth: false })]);
    const base = (lan.urls && lan.urls[0]) || location.origin;
    const url = `${base}/controller.html?flight=${encodeURIComponent(FID)}&pair=${encodeURIComponent(pair.token)}`;
    $("qr").innerHTML = qrSvg(url);
    $("pairUrl").textContent = base + "/controller.html";
  } catch (e) { $("pairUrl").textContent = e.message; }
}

function hud(d) {
  $("tAlt").textContent = Math.round(d.alt_m); $("tSpd").textContent = d.speed_mps; $("tBat").textContent = Math.round(d.battery_pct) + "%";
  $("tHdg").textContent = Math.round(d.heading_deg) + " degrees"; $("tNeedle").style.transform = `rotate(${d.heading_deg}deg)`;
  const lim = d.alt_limit_m || 120; $("altLabel").textContent = `Altitude limit ${lim} m`;
  $("altBar").style.width = Math.min(100, d.alt_m / lim * 100) + "%"; $("altBar").className = d.alt_m > lim ? "hot" : "";
  if (d.phase === "returning") banner("breach", "RETURNING HOME", "The drone is flying itself back");
  else if (d.status === "breach") banner("breach", "BREACH", d.zone || "Inside restricted airspace");
  else if (d.status === "warning") banner("warning", "WARNING", d.zone || "Restricted area ahead");
  else banner("ok", "ALL CLEAR", d.mode === "manual" ? "Flying by phone" : "Following its route");
}

function drawEvents(list) {
  $("events").innerHTML = [...list].reverse().map(e => `<div class="evt ${esc(e.kind)}"><time>${esc(new Date(e.ts).toLocaleTimeString("en-IN", { hour12: false }))}</time><b>${esc(e.text)}</b></div>`).join("") || '<div class="small">Nothing yet.</div>';
}

async function poll() {
  try {
    const s = await api(`/flights/${FID}/live`);
    drawEvents(s.events);
    if (!s.airborne) {
      clearInterval(timer); sirenStop(); $("minipanel").classList.add("hidden");
      const f = await api(`/flights/${FID}/info`).catch(() => info);
      const log = f.flight_log;
      banner("idle", "LANDED", f.status === "recalled" ? "The drone was recalled" : "Flight ended");
      $("endcard").classList.remove("hidden");
      $("endcard").innerHTML = `<h2>Flight summary</h2><p style="margin:6px 0;font-size:18px"><b>${log ? log.breaches : 0}</b> time${log && log.breaches === 1 ? "" : "s"} in restricted airspace, highest point <b>${log ? log.max_alt_m : 0} m</b></p><p class="small">The log is kept on the flight. Press Take off in the pilot app to fly again.</p><div class="btnrow"><a class="btn-sm" href="display.html">Fly again</a><a class="btn-ghost" href="index.html">Pilot app</a></div>`;
      $("pairpanel").classList.add("hidden"); $("keyhint").classList.add("hidden");
      return;
    }
    const d = s.drone, ll = [d.lat, d.lng];
    View3D.update(d); miniUpdate(d); alarmFor(d.status);
    if (!marker) { marker = L.marker(ll, { icon: DRONE_ICON(d), zIndexOffset: 1000, keyboard: false }).addTo(live); trail = L.polyline([], { color: "#f4f7fa", weight: 3, opacity: 0.85 }).addTo(live); }
    marker.setLatLng(ll); marker.setIcon(DRONE_ICON(d));
    trailPts.push(ll); if (trailPts.length > 600) trailPts.shift(); trail.setLatLngs(trailPts);
    trail.setStyle({ color: d.status === "breach" ? C.red : d.status === "warning" ? C.amber : "#f4f7fa" });
    if (!map.getBounds().pad(-0.3).contains(ll) || !followed) { map.panTo(ll, { animate: true, duration: 0.25, easeLinearity: 1 }); followed = true; }
    hud(d);
    lastStatus = d.status;
  } catch (e) { if (/token_expired|sign in/.test(e.message)) location.href = "account.html?next=display.html"; }
}

/* ---------- keyboard flying, for a laptop with no phone ---------- */
let sendTimer = null;
function sticksFromKeys() {
  const k = c => (keys[c] ? 1 : 0);
  return { fwd: k("w") - k("s"), right: k("d") - k("a"), yaw: k("e") - k("q"), climb: k("r") - k("f") };
}
window.addEventListener("keydown", e => { if (/^[wasdqerf]$/i.test(e.key)) { keys[e.key.toLowerCase()] = true; e.preventDefault(); } });
window.addEventListener("keyup", e => { if (/^[wasdqerf]$/i.test(e.key)) delete keys[e.key.toLowerCase()]; });
setInterval(() => {
  if (!FID || sess.user.role !== "pilot" || !info) return;
  const s = sticksFromKeys(), any = Object.values(s).some(v => v !== 0);
  if (any || sendTimer) { api(`/flights/${FID}/control`, { method: "POST", body: s }).catch(() => {}); sendTimer = any ? 1 : null; }
}, 100);

setView(is3d);
if (FID) follow().catch(() => chooser()); else chooser();


/* ---------- the map beside the drone view: where the drone is, with the zones, notices and permit around it ---------- */
const mini = L.map("mini", { zoomControl: false, attributionControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false, boxZoom: false, keyboard: false, touchZoom: false }).setView(HYD, 16);
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 19, maxZoom: 19 }).addTo(mini);
const miniShapes = L.layerGroup().addTo(mini), miniTrail = L.polyline([], { color: "#f4f7fa", weight: 2 }).addTo(mini);
let miniDot = null, miniAt = 0, miniPermit = null;
async function miniDraw(lat, lng) {
  miniAt = Date.now();
  try {
    const d = 0.02, [fc, notices] = await Promise.all([api(`/zones?bbox=${lng - d},${lat - d},${lng + d},${lat + d}`, { auth: false }), api("/notices/active", { auth: false })]);
    miniShapes.clearLayers();
    fc.features.forEach(f => L.geoJSON(f, { style: zoneStyle(f.properties.zone_type, true), interactive: false }).addTo(miniShapes));
    notices.forEach(n => { if (n.area) L.geoJSON(n.area, { style: { color: C.notice, weight: 2, dashArray: "6 5", fillColor: C.notice, fillOpacity: 0.2 }, interactive: false }).addTo(miniShapes); });
    if (miniPermit) L.geoJSON(miniPermit, { style: { color: C.accent, weight: 2, dashArray: "8 6", fillOpacity: 0.1 }, interactive: false }).addTo(miniShapes);
  } catch (e) { /* the map keeps what it has */ }
}
function miniUpdate(d) {
  const ll = [d.lat, d.lng];
  $("minipanel").classList.remove("hidden"); mini.invalidateSize();
  if (!miniDot) { miniDot = L.marker(ll, { icon: DRONE_ICON(d), keyboard: false, interactive: false }).addTo(mini); }
  miniDot.setLatLng(ll); miniDot.setIcon(L.divIcon({ className: "", html: `<div class="drone-pin ${d.status}" style="width:26px;height:26px"><i style="width:20px;height:24px;transform:rotate(${Math.round(d.heading_deg)}deg)"></i></div>`, iconSize: [26, 26], iconAnchor: [13, 13] }));
  const pts = miniTrail.getLatLngs(); pts.push(ll); if (pts.length > 400) pts.shift(); miniTrail.setLatLngs(pts);
  mini.setView(ll, 16, { animate: false });
  if (Date.now() - miniAt > 15000) miniDraw(d.lat, d.lng);
}

/* ---------- alarm sound: a siren while the drone is in restricted airspace, a short beep as it nears one ---------- */
let actx = null, sirenNode = null, beepAt = 0, soundOn = saved("displaySound") !== false;
function audioReady() {
  try { actx = actx || new (window.AudioContext || window.webkitAudioContext)(); if (actx.state !== "running") actx.resume(); } catch (e) { /* no sound in this browser */ }
  $("soundhint").classList.toggle("hidden", !actx || actx.state === "running" || !soundOn);
}
["click", "keydown", "touchstart"].forEach(ev => window.addEventListener(ev, audioReady, { passive: true }));
function sirenStart() {
  if (sirenNode || !actx || actx.state !== "running" || !soundOn) return;
  const osc = actx.createOscillator(), gain = actx.createGain();
  osc.type = "square"; gain.gain.value = 0.25; osc.connect(gain).connect(actx.destination); osc.start();
  let hi = true; const t = setInterval(() => { osc.frequency.setValueAtTime(hi ? 960 : 640, actx.currentTime); hi = !hi; }, 350);
  osc.frequency.value = 960; sirenNode = { osc, t };
}
function sirenStop() { if (!sirenNode) return; clearInterval(sirenNode.t); try { sirenNode.osc.stop(); } catch (e) { /* already stopped */ } sirenNode = null; }
function beep() {
  if (!actx || actx.state !== "running" || !soundOn || Date.now() - beepAt < 1500) return;
  beepAt = Date.now(); const o = actx.createOscillator(), g = actx.createGain(); o.frequency.value = 880; g.gain.value = 0.18; o.connect(g).connect(actx.destination); o.start(); o.stop(actx.currentTime + 0.15);
}
function alarmFor(status) { if (status === "breach") sirenStart(); else { sirenStop(); if (status === "warning") beep(); } }
$("sndBtn").textContent = soundOn ? "Sound: on" : "Sound: off";
$("sndBtn").addEventListener("click", () => { soundOn = !soundOn; saved("displaySound", soundOn); $("sndBtn").textContent = soundOn ? "Sound: on" : "Sound: off"; if (!soundOn) sirenStop(); });


/* ---------- officials also see the other drones in the sky around the one they watch (tracker drones and background traffic) ---------- */
if (sess && sess.user.role === "official") {
  setInterval(async () => {
    if (!FID || !is3d) return;
    try { const out = await api("/live/drones"); View3D.setOthers(out.drones.filter(d => d.flight_id !== FID)); } catch (e) { /* the next tick tries again */ }
  }, 1500);
}

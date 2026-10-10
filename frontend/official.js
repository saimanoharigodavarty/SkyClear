// Authority console: review permission requests, publish and cancel notices, see the overview.
const sess = session();
if (!sess || sess.user.role !== "official") { location.href = "account.html"; }
else if (sess.user.must_change_password) { location.href = "account.html?change=1"; }
header("official");
const { map, layers } = makeMap();
let tab = "requests", filter = "requested", centre = null, preview = null;
const reqLayer = L.layerGroup().addTo(layers.work);

function showTab(t) {
  tab = t;
  document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  ["requests", "live", "verify", "publish", "notices", "insights", "team"].forEach(x => $("tab-" + x).classList.toggle("hidden", x !== t));
  if (t === "requests") loadRequests();
  if (t === "live") startLiveView(); else stopLiveView();
  if (t === "verify") loadVerification();
  if (t === "notices") loadNotices();
  if (t === "insights") loadInsights();
  if (t === "team") loadTeam();
}
document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));

async function loadStats() {
  try {
    const o = await api("/overview");
    const cell = (n, l) => `<td><span class="n">${n}</span><span class="l">${l}</span></td>`;
    $("stats").innerHTML = `<tr>${cell(o.pending_requests, "Pending")}${cell(o.approved, "Approved")}${cell(o.watching, "Watching")}${cell(o.active_notices, "Notices")}</tr>`;
    const c = $("reqCount"); c.textContent = o.pending_requests; c.classList.toggle("hidden", o.pending_requests === 0);
    const q = await api("/verification/queue"); const vc = $("verCount"); vc.textContent = q.length; vc.classList.toggle("hidden", q.length === 0);
  } catch (e) { $("stats").innerHTML = `<tr><td>${esc(e.message)}</td></tr>`; }
}

/* ---------- requests ---------- */
function setFilter(f) { filter = f; $("fPending").className = "inline" + (f === "requested" ? "" : " ghost"); $("fAll").className = "inline" + (f === "all" ? "" : " ghost"); loadRequests(); }
$("fPending").addEventListener("click", () => setFilter("requested"));
$("fAll").addEventListener("click", () => setFilter("all"));

async function loadRequests() {
  $("reqList").innerHTML = skeleton();
  try {
    const list = await api("/flights" + (filter === "requested" ? "?status=requested" : ""));
    reqLayer.clearLayers();
    list.forEach(f => L.marker([f.lat, f.lng], { icon: pinIcon(f.status === "requested" ? "pending" : ""), keyboard: false }).bindPopup(`<b class="mono">${esc(f.flight_id)}</b><br>${esc(f.pilot_name)}`).addTo(reqLayer));
    $("reqList").innerHTML = list.length ? list.map(reqCard).join("") : `<div class="hint">${filter === "requested" ? "No pending requests for your office. A request appears here when a pilot asks for permission in an area you are responsible for." : "No flights yet."}</div>`;
    $("reqList").querySelectorAll("[data-show]").forEach(b => b.addEventListener("click", () => { const [a, o] = b.dataset.show.split(",").map(Number); map.setView([a, o], 14); }));
    $("reqList").querySelectorAll("[data-decide]").forEach(b => b.addEventListener("click", () => decide(b.dataset.id, b.dataset.decide)));
    $("reqList").querySelectorAll("[data-revoke]").forEach(b => b.addEventListener("click", () => revoke(b.dataset.revoke)));
    $("reqList").querySelectorAll("[data-recall]").forEach(b => b.addEventListener("click", () => doRecall(b.dataset.recall)));
  } catch (e) { $("reqList").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}
function reqCard(f) {
  const r = f.routed_to, pm = f.permit;
  return `
      <div class="item" id="r-${esc(f.flight_id)}">
        <div class="head"><span class="title mono">${esc(f.flight_id)}</span><span>${f.overdue ? '<span class="tag rejected">Overdue</span> ' : ""}<span class="tag ${esc(f.status)}">${esc(STATUS_LABEL[f.status] || f.status)}</span></span></div>
        ${flowHTML(f)}
        <div><b>${esc(f.pilot_name)}</b> <span class="muted">${f.pilot_cert ? "cert " + esc(f.pilot_cert) : "no certificate given"}</span></div>
        <div>${esc(f.drone_name)} <span class="muted">class ${esc(f.drone_class)}${f.uin ? ", reg. " + esc(f.uin) : ""}</span></div>
        <div class="meta">${esc(fmtWhen(f.start))} to ${esc(fmtWhen(f.end))}</div>
        <div class="meta mono">${f.lat.toFixed(4)}, ${f.lng.toFixed(4)}</div>
        <div class="meta">System verdict: ${esc(VERDICT_LABEL[f.verdict])}${f.zones.length ? ", " + esc(f.zones.join(", ")) : ""}${f.rule_ids.length ? ", rules " + esc(f.rule_ids.join(", ")) : ""}</div>
        ${r ? `<div class="meta">Routed to ${esc(r.authority.name)}, ${esc(r.reason.replace("_", " "))}</div>` : ""}
        ${f.purpose ? `<div class="meta">Purpose: ${esc(f.purpose)}</div>` : ""}
        ${f.decision ? `<div class="msg">${esc(f.decision.by)}: ${esc(f.decision.comment || "No comment")}</div>` : ""}
        ${pm ? `<div class="permit" style="grid-template-columns:1fr"><div><div class="k">Permit</div><div class="mono"><b>${esc(pm.permit_id)}</b> <span class="tag ${esc(pm.status)}">${esc(STATUS_LABEL[pm.status] || pm.status)}</span></div>
          <div class="meta">Max ${esc(pm.alt_max_m)} m${pm.conditions.length ? ", " + esc(pm.conditions.join("; ")) : ""}</div>${pm.revoked_reason ? `<div class="meta" style="color:var(--red)">Revoked: ${esc(pm.revoked_reason)}</div>` : ""}</div></div>` : ""}
        <div class="btnrow"><button class="ghost inline" type="button" data-show="${f.lat},${f.lng}">Show on map</button></div>
        ${f.status === "requested" ? `
          <div class="row2"><div><label for="a-${esc(f.flight_id)}">Max altitude (m)</label><input id="a-${esc(f.flight_id)}" type="number" min="10" max="400" value="60"></div><div></div></div>
          <label for="k-${esc(f.flight_id)}">Conditions, one per line</label>
          <textarea id="k-${esc(f.flight_id)}" placeholder="Daylight only&#10;Keep 50 m from the building"></textarea>
          <label for="c-${esc(f.flight_id)}">Comment to pilot (required to reject)</label>
          <input id="c-${esc(f.flight_id)}" maxlength="300">
          <div class="btnrow"><button class="inline" type="button" data-decide="approved" data-id="${esc(f.flight_id)}" style="margin-top:8px">Approve and issue permit</button>
          <button class="danger inline" type="button" data-decide="rejected" data-id="${esc(f.flight_id)}" style="margin-top:8px">Reject</button></div>
          <div id="m-${esc(f.flight_id)}"></div>` : ""}
        ${f.flight_log ? `<div class="msg">Flight log: ${esc(fmtTime(f.flight_log.launched_at))} to ${esc(fmtTime(f.flight_log.landed_at))}, highest ${esc(f.flight_log.max_alt_m)} m, restricted airspace entered ${esc(f.flight_log.breaches)} time${f.flight_log.breaches === 1 ? "" : "s"}.</div>` : ""}
        ${f.status === "flying" ? recallBox(f) : ""}
        ${pm && pm.status === "active" ? `
          <label for="rv-${esc(f.flight_id)}">Revoke this permit, reason</label><input id="rv-${esc(f.flight_id)}" maxlength="300" placeholder="e.g. VIP movement over the area">
          <button class="danger inline" type="button" data-revoke="${esc(pm.permit_id)}" data-flight="${esc(f.flight_id)}" style="margin-top:8px">Revoke permit</button><div id="rm-${esc(f.flight_id)}"></div>` : ""}
      </div>`;
}
async function decide(id, decision) {
  const conditions = $("k-" + id).value.split("\n").map(s => s.trim()).filter(Boolean);
  try { await api(`/flights/${id}/decision`, { method: "POST", body: { decision, comment: $("c-" + id).value, alt_max_m: Number($("a-" + id).value) || 60, conditions } }); loadRequests(); loadStats(); }
  catch (e) { $("m-" + id).innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}
async function revoke(permitId) {
  const btn = document.querySelector(`[data-revoke="${permitId}"]`), fid = btn.dataset.flight;
  try { await api(`/permits/${permitId}/revoke`, { method: "POST", body: { reason: $("rv-" + fid).value } }); loadRequests(); loadStats(); }
  catch (e) { $("rm-" + fid).innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}

/* ---------- verification queue ---------- */
async function loadVerification() {
  $("verList").innerHTML = skeleton();
  try {
    const list = await api("/verification/queue");
    $("verList").innerHTML = list.length ? list.map(v => `
      <div class="item"><div class="head"><span class="title mono">${esc(v.verification_id)}</span><span class="tag requested">${v.kind === "pilot" ? "Pilot" : "Drone"}</span></div>
        <div><b>${esc(v.user_name)}</b>${v.kind === "drone" ? " " + esc(v.drone_name) : ""}</div>
        <div class="meta">${v.kind === "pilot" ? "Certificate " + esc(v.data.cert_no) : "Serial " + esc(v.data.serial) + (v.data.uin ? ", reg. " + esc(v.data.uin) : "")}</div>
        <div class="btnrow">${v.file_ids.map((id, i) => `<button class="ghost inline" type="button" data-file="${esc(id)}">View document ${i + 1}</button>`).join("")}</div>
        <label for="vc-${esc(v.verification_id)}">Comment (required to reject)</label><input id="vc-${esc(v.verification_id)}" maxlength="300">
        <div class="btnrow"><button class="inline" type="button" data-vd="approved" data-vid="${esc(v.verification_id)}" style="margin-top:8px">Verify</button>
        <button class="danger inline" type="button" data-vd="rejected" data-vid="${esc(v.verification_id)}" style="margin-top:8px">Reject</button></div>
        <div id="vm-${esc(v.verification_id)}"></div></div>`).join("") : '<div class="hint">Nothing waiting for verification.</div>';
    $("verList").querySelectorAll("[data-file]").forEach(b => b.addEventListener("click", () => openFile(b.dataset.file).catch(e => alert(e.message))));
    $("verList").querySelectorAll("[data-vd]").forEach(b => b.addEventListener("click", async () => {
      const id = b.dataset.vid;
      try { await api(`/verification/${id}/decision`, { method: "POST", body: { decision: b.dataset.vd, comment: $("vc-" + id).value } }); loadVerification(); loadStats(); }
      catch (e) { $("vm-" + id).innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
    }));
  } catch (e) { $("verList").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}

/* ---------- publish ---------- */
let shape = "circle", corners = [];
const drawLayer = L.layerGroup().addTo(layers.work);
function drawPreview() {
  if (preview) { layers.work.removeLayer(preview); preview = null; }
  drawLayer.clearLayers();
  if (shape === "circle") { if (centre) preview = L.circle(centre, { radius: (Number($("nRadius").value) || 0) * 1000, color: C.notice, weight: 2, dashArray: "6 5", fillOpacity: 0.12 }).addTo(layers.work); return; }
  corners.forEach((c, i) => L.circleMarker(c, { radius: 5, color: C.notice, weight: 2, fillColor: "#f4f7fa", fillOpacity: 1, interactive: false }).addTo(drawLayer));
  if (corners.length >= 3) L.polygon(corners, { color: C.notice, weight: 2, dashArray: "6 5", fillColor: C.notice, fillOpacity: 0.15, interactive: false }).addTo(drawLayer);
  else if (corners.length === 2) L.polyline(corners, { color: C.notice, weight: 2, dashArray: "6 5", interactive: false }).addTo(drawLayer);
}
function setShape(mode) {
  shape = mode;
  $("mCircle").className = "inline" + (mode === "circle" ? "" : " ghost"); $("mDraw").className = "inline" + (mode === "draw" ? "" : " ghost");
  $("radiusBox").classList.toggle("hidden", mode !== "circle"); $("drawBox").classList.toggle("hidden", mode !== "draw");
  if (mode === "circle") { $("nCenter").innerHTML = centre ? `Centre <span class="mono">${centre.lat.toFixed(4)}, ${centre.lng.toFixed(4)}</span>` : "No centre chosen. Click the map."; $("nGo").disabled = !centre; }
  else cornersChanged();
  drawPreview();
}
function cornersChanged() {
  $("nCenter").textContent = corners.length < 3 ? `Click the corners of the area on the map, in order around its edge. ${corners.length} so far, at least 3 needed.` : `${corners.length} corners. Click more to refine the shape, or Undo.`;
  $("nGo").disabled = corners.length < 3;
  $("drUse").disabled = corners.length < 3; if (corners.length < 3) $("drUse").checked = false;
  drawPreview();
}
function setCentre(ll) {
  centre = L.latLng(ll.lat, ll.lng); drawPreview();
  $("nCenter").innerHTML = `Centre <span class="mono">${centre.lat.toFixed(4)}, ${centre.lng.toFixed(4)}</span>`;
  $("nGo").disabled = false;
}
map.on("click", e => {
  if (tab !== "publish") return;
  if (shape === "circle") setCentre(e.latlng); else { corners.push(L.latLng(e.latlng.lat, e.latlng.lng)); cornersChanged(); }
});
$("mCircle").addEventListener("click", () => setShape("circle"));
$("mDraw").addEventListener("click", () => setShape("draw"));
$("cUndo").addEventListener("click", () => { corners.pop(); cornersChanged(); });
$("cClear").addEventListener("click", () => { corners = []; cornersChanged(); });
bindMapSearch(map, ll => {
  if (tab === "publish" && shape === "circle") setCentre(ll);
  if ($("drLat")) { $("drLat").value = ll.lat.toFixed(5); $("drLng").value = ll.lng.toFixed(5); if (ll.name) $("drTitle").value = ll.name.split(",")[0]; }  // a searched place can be used for the drill
});
$("nRadius").addEventListener("input", drawPreview);
$("noticeForm").addEventListener("submit", async e => {
  e.preventDefault();
  $("nGo").disabled = true;
  try {
    const where = shape === "draw" ? { polygon: corners.map(c => [c.lng, c.lat]) } : { lat: centre.lat, lng: centre.lng, radius_km: Number($("nRadius").value) };
    const n = await api("/notices", { method: "POST", body: { title: $("nTitle").value, note: $("nNote").value, ...where, starts_at: toISO($("nStart").value), ends_at: toISO($("nEnd").value) } });
    const conflicts = n.conflicting_permits || [];
    $("nMsg").innerHTML = `<div class="msg">Published <span class="mono">${esc(n.notice_id)}</span>. ${n.affected_flights} flight${n.affected_flights === 1 ? "" : "s"} overlapped and the pilot${n.affected_flights === 1 ? " was" : "s were"} alerted.</div>`
      + (conflicts.length ? `<div class="msg err"><b>${conflicts.length} approved permit${conflicts.length === 1 ? "" : "s"} conflict${conflicts.length === 1 ? "s" : ""} with this notice.</b> Review ${conflicts.length === 1 ? "it" : "them"} in Requests, All flights, and revoke if needed.<ul class="reasons">${conflicts.map(c => `<li><span class="mono">${esc(c.permit_id)}</span>, ${esc(c.pilot_name)}</li>`).join("")}</ul></div>` : "");
    drawNotices(layers.notices); loadStats();
  } catch (err) { $("nMsg").innerHTML = `<div class="msg err">${esc(err.message)}</div>`; }
  finally { $("nGo").disabled = false; }
});

/* ---------- notices ---------- */
async function loadNotices() {
  $("noticeList").innerHTML = skeleton();
  try {
    const list = await api("/notices");
    $("noticeList").innerHTML = list.length ? list.map(n => `
      <div class="item">
        <div class="head"><span class="title">${esc(n.title)}</span><span class="tag ${esc(n.status)}">${esc(STATUS_LABEL[n.status])}</span></div>
        <div class="meta">${esc(fmtWhen(n.starts_at))} to ${esc(fmtWhen(n.ends_at))}, ${n.shape === "polygon" ? "drawn boundary" : "radius " + esc(n.radius_km) + " km"}</div>
        ${n.text ? `<div>${esc(n.text)}</div>` : ""}
        <div class="meta">${esc(n.source)}${n.status === "active" ? `, ${n.affected_flights} flight${n.affected_flights === 1 ? "" : "s"} affected` : ""}</div>
        <div class="btnrow"><button class="ghost inline" type="button" data-show="${n.center.lat},${n.center.lng}">Show on map</button>
        ${n.status === "active" ? `<button class="danger inline" type="button" data-cancel="${esc(n.notice_id)}">Cancel notice</button>` : ""}</div>
      </div>`).join("") : '<div class="hint">No notices published yet.</div>';
    $("noticeList").querySelectorAll("[data-show]").forEach(b => b.addEventListener("click", () => { const [a, o] = b.dataset.show.split(",").map(Number); map.setView([a, o], 13); }));
    $("noticeList").querySelectorAll("[data-cancel]").forEach(b => b.addEventListener("click", async () => { await api(`/notices/${b.dataset.cancel}/cancel`, { method: "POST" }); loadNotices(); loadStats(); drawNotices(layers.notices); }));
  } catch (e) { $("noticeList").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}

/* ---------- start ---------- */
const now = new Date();
$("nStart").value = toLocalInput(now); $("nEnd").value = toLocalInput(new Date(now.getTime() + 3 * 3600000));
drawZones(layers); drawNotices(layers.notices); loadStats(); loadRequests();
window.addEventListener("skyclear:theme", () => { drawZones(layers); drawNotices(layers.notices); });
(async () => {
  const u = sess.user, box = $("office");
  try {
    const mine = (await api("/authorities")).find(a => a.authority_id === u.authority_id);
    box.innerHTML = mine
      ? `<b>${esc(mine.name)}</b><div class="small">You review permission requests for the areas this office is responsible for. Expected response time: ${esc(mine.sla_minutes)} minutes, after which a request is flagged overdue and shown to the supervising office.</div>`
      : `<b>Administrator view</b><div class="small">You see every office, all requests and all verification requests.</div>`;
  } catch (e) { box.textContent = ""; }
})();
setInterval(() => { loadStats(); if (tab === "requests") loadRequests(); }, 20000);
let pending = null;
const soon = fn => { clearTimeout(pending); pending = setTimeout(fn, 150); };  // several events at once cause one refresh
liveEvents({
  flight: () => soon(() => { loadStats(); if (tab === "requests") loadRequests(); if (tab === "live") refreshLive(); }),
  breach: () => soon(() => { if (tab === "live") refreshLive(); }),
  notice: () => soon(() => { drawNotices(layers.notices); if (tab === "notices") loadNotices(); }),
  status: ok => { const b = $("liveDot"); if (b) { b.textContent = ok ? "Live" : "Reconnecting"; b.className = "livedot " + (ok ? "on" : ""); } },
});

/* ---------- team (admin only) ---------- */
if (!sess.user.authority_id) $("teamTab").classList.remove("hidden");
async function loadTeam() {
  try {
    const [auths, people] = await Promise.all([api("/authorities"), api("/admin/officials")]);
    $("iAuth").innerHTML = '<option value="">Administrator (sees every office)</option>' + auths.map(a => `<option value="${esc(a.authority_id)}">${esc(a.name)}</option>`).join("");
    const nameOf = id => (auths.find(a => a.authority_id === id) || {}).name || "Administrator";
    $("teamList").innerHTML = people.map(u => `<div class="item"><div class="head"><span class="title">${esc(u.name)}</span>${u.mfa_enabled ? '<span class="tag approved">Authenticator on</span>' : ""}</div><div class="meta">${esc(u.email)}</div><div class="meta">${esc(nameOf(u.authority_id))}</div></div>`).join("") || '<div class="hint">No officials yet.</div>';
  } catch (e) { $("teamList").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}
$("inviteForm").addEventListener("submit", async e => {
  e.preventDefault();
  try {
    const u = await api("/admin/officials", { method: "POST", body: { name: $("iName").value, email: $("iEmail").value, authority_id: $("iAuth").value || null } });
    $("inviteMsg").innerHTML = `<div class="msg"><b>${esc(u.email)} is invited.</b> Give them this temporary password now, it is not shown again:<div class="mono" style="font-size:16px;margin-top:6px">${esc(u.temporary_password)}</div></div>`;
    e.target.reset(); loadTeam();
  } catch (err) { $("inviteMsg").innerHTML = `<div class="msg err">${esc(err.message)}</div>`; }
});

/* ---------- live airspace ---------- */
const fmtTime = iso => new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const liveLayer = L.layerGroup().addTo(map);
let liveDrones = [], liveTimer = null;
const live = createLive(map, liveLayer, drones => { liveDrones = drones; }, 2000);
live.start();  // officers see the drones on the map in every tab

function recallBox(f) {
  return `<label for="rc-${esc(f.flight_id)}">Recall this drone, reason</label><input id="rc-${esc(f.flight_id)}" maxlength="300" placeholder="e.g. Emergency vehicle landing nearby">
    <button class="danger inline" type="button" data-recall="${esc(f.flight_id)}" style="margin-top:8px">Recall drone</button><div id="rcm-${esc(f.flight_id)}"></div>`;
}
async function doRecall(id) {
  const reason = ($("rc-" + id) || {}).value || "";
  try { await api(`/flights/${id}/recall`, { method: "POST", body: { reason } }); refreshLive(); loadRequests(); }
  catch (e) { const m = $("rcm-" + id); if (m) m.innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}

async function refreshLive() {
  try {
    const [flights, br] = await Promise.all([api("/flights"), api("/live/breaches?limit=8")]);
    const airborne = flights.filter(f => ["flying", "recalled"].includes(f.status));
    const traffic = liveDrones.filter(d => d.kind !== "flight").length;
    const inAir = Object.fromEntries(liveDrones.map(d => [d.flight_id, d]));
    const cell = (n, l) => `<td><span class="n">${n}</span><span class="l">${l}</span></td>`;
    $("liveStats").innerHTML = `<tr>${cell(airborne.length, "Flights in the air")}${cell(traffic, "Traffic drones")}${cell(liveDrones.filter(d => d.status === "breach").length, "In breach now")}</tr>`;
    $("airList").innerHTML = airborne.length ? airborne.map(f => {
      const d = inAir[f.flight_id], state = f.status === "recalled" ? '<span class="pill-bad">Recalled, returning</span>' : !d ? "starting" : d.status === "breach" ? '<span class="pill-bad">Inside ' + esc(d.zone || "restricted airspace") + "</span>" : d.status === "warning" ? '<span class="pill-warn">' + esc(d.zone || "Restricted area ahead") + "</span>" : '<span class="pill-ok">All clear</span>';
      return `<div class="item air-item"><div><b class="mono">${esc(f.flight_id)}</b> ${esc(f.pilot_name)}<div class="meta">${esc(f.drone_name)}${d ? `, ${Math.round(d.alt_m)} m, ${d.speed_mps} m/s, battery ${Math.round(d.battery_pct)}%` : ""}</div><div class="meta">${state}</div></div>
        <div>${f.status === "flying" ? `<button class="danger" type="button" data-air-recall="${esc(f.flight_id)}">Recall</button>` : ""}<button class="ghost" type="button" data-air-show="${esc(f.flight_id)}" style="margin-top:6px">Show</button>
          <a class="btn-sm" href="display.html?flight=${encodeURIComponent(f.flight_id)}" target="_blank" rel="noopener" style="display:block;margin-top:6px;text-align:center">Watch in 3D</a></div></div>`;
    }).join("") : '<div class="hint">No pilot flights in the air. When a pilot takes off after preflight, it appears here at once.</div>';
    $("airList").querySelectorAll("[data-air-recall]").forEach(b => b.addEventListener("click", async () => {
      const reason = prompt("Reason for recalling this drone (the pilot is told):");
      if (reason && reason.trim().length > 2) { try { await api(`/flights/${b.dataset.airRecall}/recall`, { method: "POST", body: { reason } }); refreshLive(); } catch (e) { alert(e.message); } }
    }));
    $("airList").querySelectorAll("[data-air-show]").forEach(b => b.addEventListener("click", () => { const d = inAir[b.dataset.airShow]; if (d) map.flyTo([d.lat, d.lng], 16, { duration: 0.6 }); }));
    $("breachList").innerHTML = br.breaches.length ? br.breaches.map(b => `<div class="breach"><b>${esc(b.name)}</b> <span class="muted">${esc(b.kind)}</span><div class="meta">${esc(b.drone_id)}, flight ${esc(b.flight_id)}, ${esc(fmtTime(b.ts))}</div></div>`).join("") : '<div class="hint">No breaches yet.</div>';
  } catch (e) { $("airList").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}
function startLiveView() { refreshLive(); if (!liveTimer) liveTimer = setInterval(refreshLive, 8000); }
function stopLiveView() { clearInterval(liveTimer); liveTimer = null; }

$("trafficN").addEventListener("input", () => { $("trafficLabel").textContent = $("trafficN").value; });
$("trafficGo").addEventListener("click", async () => {
  try { await api("/sim/fleet", { method: "POST", body: { count: Number($("trafficN").value) || 50, seed: 1, speed_x: 1 } }); $("simMsg").innerHTML = '<div class="msg">Background traffic started.</div>'; refreshLive(); }
  catch (e) { $("simMsg").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
});
$("trafficStop").addEventListener("click", async () => {
  try { await api("/sim/fleet", { method: "DELETE" }); $("simMsg").innerHTML = '<div class="msg">Background traffic stopped. Pilots\' flights keep flying.</div>'; refreshLive(); }
  catch (e) { $("simMsg").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
});
$("vipGo").addEventListener("click", async () => {
  try {
    const r = await api("/sim/scenarios/vip", { method: "POST" });
    $("simMsg").innerHTML = `<div class="msg">Restriction <span class="mono">${esc(r.notice_id)}</span> published. ${r.affected_flights} pilot flight${r.affected_flights === 1 ? "" : "s"} alerted, ${r.affected_drones} drone${r.affected_drones === 1 ? "" : "s"} inside it.</div>`
      + ((r.conflicting_permits || []).length ? `<div class="msg err"><b>${r.conflicting_permits.length} approved permit${r.conflicting_permits.length === 1 ? "" : "s"} conflict.</b> Review in Requests, All flights.</div>` : "");
    drawNotices(layers.notices); refreshLive();
  } catch (e) { $("simMsg").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
});


/* ---------- insights: what the data says (MongoDB aggregations), who did what (audit log), how updates reach the screens (change streams) ---------- */
const STATUS_ORDER = ["requested", "approved", "watching", "flying", "completed", "recalled", "revoked", "rejected", "cancelled"];
function bars(rows, labelOf) {
  const max = Math.max(1, ...rows.map(r => r[1]));
  return rows.map(r => `<div class="barrow"><span class="bl">${esc(labelOf ? labelOf(r[0]) : r[0])}</span><span class="bt"><i style="width:${Math.round(r[1] / max * 100)}%"></i></span><b>${esc(r[1])}</b></div>`).join("");
}
async function loadInsights() {
  const box = $("insightBody"); box.innerHTML = skeleton();
  try {
    const isAdmin = !sess.user.authority_id;
    const [a, audit, ev] = await Promise.all([api("/analytics/summary"), isAdmin ? api("/audit?limit=12").catch(() => []) : [], isAdmin ? api("/events/status").catch(() => null) : null]);
    const statuses = STATUS_ORDER.filter(k => a.flights_by_status[k]).map(k => [k, a.flights_by_status[k]]);
    const hot = (a.heatmap || []).slice(0, 6).map(h => [`${h.cell[1].toFixed(2)} N, ${h.cell[0].toFixed(2)} E`, h.count]);
    const zb = (a.breaches_by_zone || []).slice(0, 6).map(z => [z.name || z.zone || z._id, z.count]);
    box.innerHTML = `
      <div class="section"><h3>Flights by status</h3>${bars(statuses, k => STATUS_LABEL[k] || k[0].toUpperCase() + k.slice(1)) || '<div class="hint">No flights yet.</div>'}</div>
      <div class="section"><h3>Busiest areas for requests and checks</h3>${bars(hot) || '<div class="hint">No data.</div>'}<div class="meta">Grid cells counted by a MongoDB aggregation over saved flights.</div></div>
      <div class="section"><h3>Breaches by zone</h3>${bars(zb) || '<div class="hint">No breaches recorded yet.</div>'}</div>
      <div class="section"><h3>Response time</h3><div class="n2">${a.median_decision_minutes == null ? "n/a" : esc(a.median_decision_minutes)} min</div><div class="meta">Median time from request to decision. ${esc(a.zones)} zones in the data.</div></div>
      ${isAdmin ? `<div class="section"><h3>Live updates</h3>${ev ? `<div>${esc(ev.mode === "mongodb_change_streams" ? "MongoDB change streams" : "In-process events")}, watching ${esc((ev.watching || []).join(", ") || "nothing")}</div><div class="meta">${esc(ev.events)} events delivered, ${esc(ev.restarts)} restarts</div>` : '<div class="hint">Not available.</div>'}</div>
      <div class="section"><h3>Audit log, latest first</h3>${(audit || []).map(r => `<div class="item"><div class="head"><span class="title">${esc(r.action.replace(/_/g, " "))}</span><span class="meta">${esc(fmtTime(r.ts))}</span></div><div class="meta">${esc(r.actor)}, ${esc(r.target)}${r.detail ? ", " + esc(r.detail) : ""}</div></div>`).join("") || '<div class="hint">Nothing recorded yet.</div>'}<div class="meta">Append-only: written in the same MongoDB transaction as the action it records.</div></div>` : ""}`;
  } catch (e) { box.innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}


/* ---------- guard alerts: a link and QR for the devices in the protected area, and a test siren ---------- */
(async function guardLink() {
  try {
    const lan = await api("/lan", { auth: false }), base = (lan.urls && lan.urls[0]) || location.origin;
    $("guardQr").innerHTML = qrSvg(base + "/guard.html"); $("guardUrl").textContent = base + "/guard.html";
  } catch (e) { $("guardUrl").textContent = location.origin + "/guard.html"; }
})();
$("guardTest").addEventListener("click", async () => {
  try { const r = await api("/guard/test", { method: "POST" }); $("guardMsg").textContent = r.listeners ? `Siren sent to ${r.listeners} listening device${r.listeners === 1 ? "" : "s"}.` : "No device is listening yet. Open the link above on a phone and tap Turn alerts on."; }
  catch (e) { $("guardMsg").textContent = e.message; }
});

/* ---------- drill: declare an area and send a simulated drone toward it ---------- */
let drillNotice = null;
$("drHere").addEventListener("click", () => {
  if (!navigator.geolocation) { $("drMsg").innerHTML = '<div class="msg err">This browser cannot give a location. Type the numbers.</div>'; return; }
  navigator.geolocation.getCurrentPosition(p => { $("drLat").value = p.coords.latitude.toFixed(5); $("drLng").value = p.coords.longitude.toFixed(5); $("drMsg").innerHTML = `<div class="msg">Location taken, accurate to about ${Math.round(p.coords.accuracy)} m.</div>`; },
    e => { $("drMsg").innerHTML = `<div class="msg err">Could not read the location (${esc(e.message)}). Open this page as localhost on a laptop, or type the numbers.</div>`; }, { enableHighAccuracy: true, timeout: 15000 });
});
$("drGo").addEventListener("click", async () => {
  try {
    const where = $("drUse").checked ? { polygon: corners.map(c => [c.lng, c.lat]) } : { lat: Number($("drLat").value), lng: Number($("drLng").value) };
    const r = await api("/sim/scenarios/intruder", { method: "POST", body: { ...where, radius_m: Number($("drRad").value) || 150, title: $("drTitle").value.trim() || "Protected area drill" } });
    drillNotice = r.notice_id; drawNotices(layers.notices);
    $("drMsg").innerHTML = `<div class="msg">Drill started. <b>${esc(r.title)}</b> is declared. The drone ${esc(r.drone_id)} reaches it in about ${esc(r.arrives_in_s)} seconds. Devices with the guard page open will sound.</div>`;
  } catch (e) { $("drMsg").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
});
$("drEnd").addEventListener("click", async () => {
  try {
    if (drillNotice) await api(`/notices/${drillNotice}/cancel`, { method: "POST" }).catch(() => {});
    await api("/sim/fleet", { method: "DELETE" }); drillNotice = null; drawNotices(layers.notices);
    $("drMsg").innerHTML = '<div class="msg">Drill ended. The restriction is cancelled and the test drone is gone.</div>';
  } catch (e) { $("drMsg").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
});

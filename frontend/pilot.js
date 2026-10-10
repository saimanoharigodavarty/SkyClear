// Pilot app: check a spot, simulate a flight, manage flights and drones, read alerts.
header("pilot");
if (session() && session().user.must_change_password) location.href = "account.html?change=1";
const { map, layers } = makeMap();
const VCOLOR = { get can_fly() { return C.green; }, get permission_needed() { return C.amber; }, get prohibited() { return C.red; }, get cannot_determine() { return C.grey; } };
let tab = "check", picked = null, marker = null, catalog = [], mine = [], lastCheck = null;
const me = () => (session() || {}).user;

/* ---------- tabs ---------- */
function showTab(t) {
  tab = t;
  document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  ["check", "sim", "ask", "flights", "alerts"].forEach(x => $("tab-" + x).classList.toggle("hidden", x !== t));
  if (t === "ask") updateAskSpot();
  if (t === "flights") loadFlights();
  if (t === "alerts") loadAlerts();
}
document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));

/* ---------- drones ---------- */
async function loadDrones() {
  try { catalog = await api("/drones", { auth: false }); } catch (e) { catalog = []; }
  mine = me() ? await api("/me/drones").catch(() => []) : [];
  const opt = d => `<option value="${esc(d.drone_id)}">${esc(d.name)} (${esc(d.class)})</option>`;
  const options = (mine.length ? `<optgroup label="My drones">${mine.map(opt).join("")}</optgroup>` : "") +
    `<optgroup label="Sample drones, for trying the app">${catalog.map(opt).join("")}</optgroup>`;
  const keep = $("drone").value;
  $("drone").innerHTML = options; $("simDrone").innerHTML = options;
  if (keep) $("drone").value = keep;
  updateDroneHelp();
  $("myDrones").innerHTML = mine.length
    ? mine.map(d => `<div class="item"><div class="head"><span class="title">${esc(d.name)}</span>${verifyBadge(d.verification)}</div>
        <div class="meta">${esc(d.weight_g)} g, class ${esc(d.class)}${d.serial ? ", serial " + esc(d.serial) : ""}${d.uin ? ", reg. " + esc(d.uin) : ""}</div>
        ${d.verification && d.verification.status === "rejected" ? `<div class="meta" style="color:var(--red)">${esc(d.verification.comment)}</div>` : ""}
        ${(!d.verification || ["unverified", "rejected"].includes(d.verification.status)) ? `<form data-dv="${esc(d.drone_id)}">
          <div class="row2"><div><label>Serial number</label><input name="serial" required minlength="3" maxlength="40"></div><div><label>Registration no. (UIN)</label><input name="uin" maxlength="40" value="${esc(d.uin || "")}"></div></div>
          <label>Photo of the drone with its serial plate (JPG, PNG, PDF)</label><input name="file" type="file" accept="image/jpeg,image/png,application/pdf" required>
          <button class="ghost inline" type="submit" style="margin-top:8px">Send for verification</button><div class="vmsg"></div></form>` : ""}</div>`).join("")
    : '<div class="hint">No drones yet. Add one so checks use your real weight class.</div>';
  document.querySelectorAll("form[data-dv]").forEach(f => f.addEventListener("submit", e => submitDroneVerification(e, f.dataset.dv)));
  renderPilotVerify();
  if (me() && $("checklist")) renderChecklist();
}

function renderChecklist() {
  const u = me() || {}, pv = (u.verification || {}).status || "unverified";
  const drone = mine[0], dv = drone && (drone.verification || {}).status;
  const steps = [
    ["Create your account", true, "Done", ""],
    ["Verify your pilot certificate", pv === "verified", pv === "pending" ? "Waiting for an officer" : pv === "verified" ? "Verified" : "Do this next", "pilotVerify"],
    ["Add your drone", mine.length > 0, mine.length ? "Done" : "Add it below", "droneForm"],
    ["Verify your drone", dv === "verified", dv === "pending" ? "Waiting for an officer" : dv === "verified" ? "Verified" : mine.length ? "Send its serial number" : "After adding it", "myDrones"],
    ["Request permission when a spot needs it", false, "Check a spot, then press Request permission", ""]
  ];
  const done = steps.filter(s => s[1]).length;
  $("checklist").innerHTML = `<div class="progress">${done} of 4 steps done</div><ul class="checklist">${steps.map((s, i) => `<li class="${s[1] ? "done" : ""}"><span class="n">${s[1] ? "&#10003;" : i + 1}</span><div><div class="t">${esc(s[0])}</div><div class="small">${esc(s[2])}</div></div></li>`).join("")}</ul>`;
}

function renderPilotVerify() {
  if (!me()) return;
  const u = me(), v = (u && u.verification) || { status: "unverified" };
  $("pilotVerify").innerHTML = `<div class="item"><div class="head"><span class="title">Pilot certificate</span>${verifyBadge(v)}</div>
    ${v.status === "verified" ? `<div class="meta">Verified by ${esc(v.by)} on ${esc(fmtWhen(v.at))}</div>` : v.status === "pending" ? '<div class="meta">Waiting for an officer to check your documents.</div>' : `
      ${v.status === "rejected" ? `<div class="meta" style="color:var(--red)">${esc(v.comment)}</div>` : ""}
      <form id="pvForm"><label for="pvCert">Remote pilot certificate number</label><input id="pvCert" required minlength="3" maxlength="40" value="${esc(u.pilot_cert || "")}">
      <label for="pvFile">Photo of the certificate (JPG, PNG, PDF)</label><input id="pvFile" type="file" accept="image/jpeg,image/png,application/pdf" required>
      <button class="ghost inline" type="submit" style="margin-top:8px">Send for verification</button><div id="pvMsg"></div></form>`}</div>`;
  const f = $("pvForm");
  if (f) f.addEventListener("submit", async e => {
    e.preventDefault();
    try { const id = await uploadFile($("pvFile").files[0]); await api("/me/verification/pilot", { method: "POST", body: { cert_no: $("pvCert").value, file_ids: [id] } }); await refreshMe(); renderPilotVerify(); }
    catch (err) { $("pvMsg").innerHTML = `<div class="msg err">${esc(err.message)}</div>`; }
  });
}
async function submitDroneVerification(e, droneId) {
  e.preventDefault();
  const f = e.target, msg = f.querySelector(".vmsg");
  try {
    const id = await uploadFile(f.file.files[0]);
    await api(`/me/drones/${droneId}/verification`, { method: "POST", body: { serial: f.serial.value, uin: f.uin.value || null, file_ids: [id] } });
    await loadDrones();
  } catch (err) { msg.innerHTML = `<div class="msg err">${esc(err.message)}</div>`; }
}
async function refreshMe() { const u = await api("/me"); const s = session(); s.user = u; saved("skyclear.session", s); }

/* ---------- guidance: welcome, steps, examples, drone help ---------- */
const CLASS_HELP = Object.fromEntries(CFG.droneClasses.map(c => [c.name, c.label]));
function updateDroneHelp() {
  const all = [...mine, ...catalog], d = all.find(x => x.drone_id === $("drone").value);
  $("droneHelp").textContent = d ? `${CLASS_HELP[d.class]}. The rules depend on the weight class.${me() ? "" : " Sign in to use your own registered drones."}` : "";
}
$("drone").addEventListener("change", updateDroneHelp);
function setStep(n) { document.querySelectorAll("#stepper span").forEach(s => { const i = Number(s.dataset.s); s.className = i < n ? "done" : i === n ? "on" : ""; }); }
function setPick(latlng) {
  picked = latlng;
  if (marker) marker.setLatLng(picked); else marker = L.marker(picked, { icon: pinIcon(), keyboard: false }).addTo(layers.work);
  $("picked").innerHTML = `Selected <span class="mono">${picked.lat.toFixed(4)}, ${picked.lng.toFixed(4)}</span>. Step 2: check your drone and time, then press Check.`;
  $("go").disabled = false; setStep(2);
}
function pickAndCheck(lat, lng) { showTab("check"); map.flyTo([lat, lng], 15, { duration: 0.6 }); setPick(L.latLng(lat, lng)); $("go").click(); }
// Example buttons are built from the real zones in the database (/examples), nothing is typed into the page.
let exampleRoute = null;
(async () => {
  if (CFG.city) $("cityName").textContent = CFG.city;
  try {
    const ex = await api("/examples", { auth: false });
    $("examples").innerHTML = ex.spots.map((s, i) => `<button type="button" data-i="${i}">${esc(s.label)}${s.droneClass ? ", " + esc(s.droneClass) + " drone" : ""}</button>`).join("");
    $("examples").querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
      const s = ex.spots[Number(b.dataset.i)];
      if (s.droneClass) { const d = catalog.find(x => x.class === s.droneClass); if (d) $("drone").value = d.drone_id; updateDroneHelp(); }
      pickAndCheck(s.lat, s.lng);
    }));
    exampleRoute = ex.route;
    if (ex.route) { $("routeExamples").innerHTML = '<button type="button" id="exRoute">Try an example route through a restricted zone</button>'; $("exRoute").addEventListener("click", loadExampleRoute); }
  } catch (e) { $("examples").innerHTML = ""; }
})();
if (!saved("skyclear.welcome.hidden")) $("welcome").classList.remove("hidden");
$("hideWelcome").addEventListener("click", () => { saved("skyclear.welcome.hidden", true); $("welcome").classList.add("hidden"); });
bindMapSearch(map, ll => { if (tab === "check") setPick(L.latLng(ll.lat, ll.lng)); });

/* ---------- map clicks ---------- */
map.on("click", e => {
  if (tab === "check") setPick(e.latlng);
  else if (tab === "sim") addWaypoint(e.latlng);
});

/* ---------- check ---------- */
function drawCheck(r) {
  resultLayer.clearLayers();
  const shapes = [];
  (r.zones || []).filter(z => z.distance_km === 0).forEach(z => shapes.push(L.geoJSON(z.geometry, { style: zoneStyle(z.zone_type, true), interactive: false }).addTo(resultLayer)));
  (r.notices || []).forEach(n => shapes.push(L.geoJSON(n.geometry, { style: { color: C.notice, weight: 3, dashArray: "6 5", fillColor: C.notice, fillOpacity: 0.18 }, interactive: false }).addTo(resultLayer)));
  if (shapes.length && picked) {  // frame the spot together with what it is inside
    const b = L.latLngBounds([picked]); shapes.forEach(s => b.extend(s.getBounds()));
    map.fitBounds(b, { padding: [40, 40], maxZoom: 14 });
  }
}
const resultLayer = L.layerGroup().addTo(layers.work);

function renderCheck(r) {
  drawCheck(r);
  const inside = (r.zones || []).filter(z => z.distance_km === 0);
  const near = (r.zones || []).filter(z => z.distance_km > 0);
  const zl = z => `<li><b>${esc(z.name)}</b> <span class="muted">${esc(z.zone_type)}</span><span class="meta mono" style="float:right">${z.distance_km === 0 ? "inside" : esc(z.distance_km) + " km"}</span></li>`;
  $("result").innerHTML = `
    <div class="verdict ${esc(r.verdict)}"><div class="v">${esc(VERDICT_LABEL[r.verdict] || r.verdict)}</div><div class="s">${esc(VERDICT_MEANING[r.verdict] || "")}</div></div>
    <p style="margin:0"><b>Why:</b> ${esc(r.summary)}</p>
    <div class="small" style="margin-top:6px">${r.explained_by === "llm" ? "Explanation written by an AI model from the rules below. The verdict itself is decided by rules, not by the model." : "The verdict is decided by rules."}</div>
    ${inside.length ? `<div class="section"><h3>Inside</h3><ul class="list">${inside.map(zl).join("")}</ul></div>` : ""}
    ${r.notices.length ? `<div class="section"><h3>Active notices</h3><ul class="list">${r.notices.map(n => `<li><b>${esc(n.title)}</b><div class="meta">${esc(fmtWhen(n.starts_at))} to ${esc(fmtWhen(n.ends_at))}</div></li>`).join("")}</ul></div>` : ""}
    ${near.length ? `<div class="section"><h3>Nearby</h3><ul class="list">${near.map(zl).join("")}</ul></div>` : ""}
    ${r.citations.length ? `<div class="section"><h3>Rules behind this answer</h3>${r.citations.map(c => `<div class="cite"><span class="id">${esc(c.rule_id)}</span>${esc(c.text)}<div class="small">${esc(c.source)}</div></div>`).join("")}</div>` : ""}
    <div class="section"><h3>Next steps</h3><ul class="list">${r.next_steps.map(s => `<li>${esc(s)}</li>`).join("")}</ul></div>
    <button type="button" class="ghost inline" id="askAbout" style="margin-top:12px">Ask a question about this spot</button>
    <div class="small" style="margin-top:12px">Data last updated ${esc(r.data_last_updated)}. ${esc(r.disclaimer)}</div>`;
  renderActions(r);
  $("askAbout").addEventListener("click", () => { showTab("ask"); updateAskSpot(); $("askSpot").checked = true; $("askQ").focus(); });
}

function renderActions(r) {
  const box = $("actions");
  if (!me()) { box.innerHTML = '<div class="section"><h3>Stay informed</h3><p style="margin:0">Sign in to watch this flight and get an alert if an official restriction appears, or to request permission from the authority.</p><a href="account.html"><button type="button">Sign in or register</button></a></div>'; return; }
  const canAsk = r.verdict === "permission_needed";
  box.innerHTML = `<div class="section"><h3>Save this flight</h3>
    ${canAsk ? '<div class="route" id="routeInfo">Finding who reviews permission here...</div>' : ""}
    <div class="row2"><div><label for="fStart">Takeoff</label><input id="fStart" type="datetime-local" value="${esc($("when").value)}"></div>
    <div><label for="fEnd">Landing</label><input id="fEnd" type="datetime-local" value="${esc(toLocalInput(new Date(new Date($("when").value).getTime() + 3600000)))}"></div></div>
    <label for="fPurpose">Purpose</label><input id="fPurpose" maxlength="200" placeholder="e.g. site survey">
    <div class="btnrow"><button id="fWatch" class="ghost" type="button">Watch this flight</button>
    ${canAsk ? '<button id="fAsk" type="button">Request permission</button>' : ""}</div>
    <div id="fMsg"></div></div>`;
  $("fWatch").addEventListener("click", () => saveFlight("watch"));
  if (canAsk) {
    $("fAsk").addEventListener("click", () => saveFlight("permission"));
    api(`/route-preview?lat=${picked.lat}&lng=${picked.lng}`).then(r => {
      $("routeInfo").innerHTML = routeText(r) + verifyHint();
    }).catch(e => { $("routeInfo").textContent = e.message.replace(/^no_authority_for_area: /, ""); $("fAsk").disabled = true; });
  }
}

const REASON = { zone_owner: "owner of this zone", jurisdiction: "responsible for this area", nearest_office: "nearest office" };
const routeText = r => `<b>Reviewed by:</b> ${esc(r.authority.name)}<div class="meta">${esc(REASON[r.reason] || r.reason)}${r.distance_km != null ? ", " + esc(r.distance_km) + " km away" : ""}. Usual response within ${esc(r.authority.sla_minutes)} minutes.${r.also_notified.length ? " Also informed: " + esc(r.also_notified.join(", ")) + "." : ""}</div>`;
function verifyHint() { const u = me(); const v = (u && u.verification && u.verification.status) || "unverified"; return v === "verified" ? "" : `<div class="meta" style="color:var(--red)">Your pilot verification is "${esc(v)}". Verify in the My flights tab before you request.</div>`; }

async function saveFlight(kind) {
  const msg = $("fMsg");
  try {
    const f = await api("/flights", { method: "POST", body: { drone_id: $("drone").value, lat: picked.lat, lng: picked.lng,
      start: toISO($("fStart").value), end: toISO($("fEnd").value), purpose: $("fPurpose").value, kind } });
    msg.innerHTML = `<div class="msg">${kind === "permission" ? "Request sent" : "Watching this flight"} as <span class="mono">${esc(f.flight_id)}</span>. You will get an alert if something changes.</div>${f.routed_to ? `<div class="route">${routeText(f.routed_to)}</div>` : ""}`;
  } catch (e) { msg.innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}

$("go").addEventListener("click", async () => {
  if (!picked) return;
  const btn = $("go");
  btn.disabled = true; btn.textContent = "Checking...";
  $("result").innerHTML = skeleton(); $("actions").innerHTML = "";
  $("welcome").classList.add("hidden");  // the pilot has found their feet, give the answer the room
  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    setStep(3);
    renderCheck(await api("/check", { method: "POST", auth: false, body: { lat: picked.lat, lng: picked.lng, drone_id: $("drone").value, datetime: toISO($("when").value) } }));
  } catch (e) { $("result").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
  finally { btn.disabled = false; btn.textContent = "Check this spot"; }
});

/* ---------- simulation ---------- */
let waypoints = [], routeLine = null, playTimer = null;
const simLayer = L.layerGroup().addTo(layers.work);
function addWaypoint(ll) {
  stopPlayback(); waypoints.push(ll);
  L.circleMarker(ll, { radius: 5, color: C.notice, fillColor: C.notice, fillOpacity: 1 }).addTo(simLayer);
  if (routeLine) routeLine.setLatLngs(waypoints); else routeLine = L.polyline(waypoints, { color: C.notice, weight: 2, dashArray: "4 4" }).addTo(simLayer);
  $("wpHint").textContent = waypoints.length + " waypoint" + (waypoints.length > 1 ? "s" : "") + ". " + (waypoints.length < 2 ? "Add at least 2." : "Ready to run.");
  $("run").disabled = waypoints.length < 2;
}
function stopPlayback() { if (playTimer) { clearInterval(playTimer); playTimer = null; } }
function clearRoute() {
  stopPlayback(); simLayer.clearLayers(); waypoints = []; routeLine = null;
  $("run").disabled = true; $("live").classList.add("hidden"); $("simResult").innerHTML = "";
  $("wpHint").textContent = "Click the map to add waypoints, at least 2.";
}
$("clearRoute").addEventListener("click", clearRoute);
const fmtDur = s => Math.floor(s / 60) + " min " + Math.round(s % 60) + " s";

function simSummary(out) {
  const sm = out.summary, fi = sm.first_issue;
  $("simResult").innerHTML = `
    <div class="verdict ${esc(sm.worst_verdict)}"><div class="v">${esc(VERDICT_LABEL[sm.worst_verdict])}</div><div class="s">Worst result along the route</div></div>
    <p style="margin:0">Route ${(sm.length_m / 1000).toFixed(2)} km, about ${esc(fmtDur(sm.duration_s))} at ${esc($("speed").value)} m/s.</p>
    ${fi ? `<p><b>First issue</b> after ${(fi.dist_m / 1000).toFixed(2)} km (${esc(fmtDur(fi.t_s))}): ${esc(VERDICT_LABEL[fi.verdict])} in ${esc(fi.zones.join(", "))}. Rules <span class="mono">${esc(fi.rule_ids.join(", "))}</span>.</p>` : "<p>No restriction found in our data along this route.</p>"}
    <div class="small">Simulated flight, not an approval of the route. ${esc(out.disclaimer)}</div>`;
}

function play(out) {
  stopPlayback();
  const s = out.samples, rate = Number($("playback").value);
  const dot = L.circleMarker([s[0].lat, s[0].lng], { radius: 8, color: C.ink, weight: 2, fillColor: VCOLOR[s[0].verdict], fillOpacity: 1 }).addTo(simLayer);
  let i = 0, t = 0;
  $("live").classList.remove("hidden");
  playTimer = setInterval(() => {
    t += rate * 0.1;
    while (i < s.length - 1 && s[i + 1].t_s <= t) { i++; L.polyline([[s[i - 1].lat, s[i - 1].lng], [s[i].lat, s[i].lng]], { color: VCOLOR[s[i].verdict], weight: 5 }).addTo(simLayer); }
    const p = s[i];
    dot.setLatLng([p.lat, p.lng]).setStyle({ fillColor: VCOLOR[p.verdict] });
    $("live").innerHTML = `<div class="verdict ${esc(p.verdict)}"><div class="v">${esc(VERDICT_LABEL[p.verdict])}</div></div>
      <div class="mono">${esc(fmtDur(p.t_s))} / ${(p.dist_m / 1000).toFixed(2)} km</div>
      <div>${p.zones.length ? "Inside: " + esc(p.zones.join(", ")) : "Not inside any known zone"}</div>`;
    if (i >= s.length - 1) { stopPlayback(); simSummary(out); }
  }, 100);
}

$("run").addEventListener("click", async () => {
  const btn = $("run");
  btn.disabled = true; btn.textContent = "Checking route...";
  $("live").classList.add("hidden"); $("simResult").innerHTML = skeleton();
  simLayer.eachLayer(l => { if (l instanceof L.Polyline && l !== routeLine) simLayer.removeLayer(l); });
  try {
    const out = await api("/simulate/route", { method: "POST", auth: false, body: { drone_id: $("simDrone").value, speed_mps: Number($("speed").value) || 10,
      datetime: toISO($("simWhen").value), waypoints: waypoints.map(w => ({ lat: w.lat, lng: w.lng })) } });
    $("simResult").innerHTML = '<div class="hint">Simulating flight...</div>';
    play(out);
  } catch (e) { $("simResult").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
  finally { btn.disabled = waypoints.length < 2; btn.textContent = "Run simulation"; }
});

/* ---------- flights ---------- */
function gate(id, bodyId, text) {
  const ok = !!me();
  $(id).innerHTML = ok ? "" : `<div class="welcome"><h2>Sign in to continue</h2><p>${text}</p><div class="btnrow"><a class="btn-sm" href="account.html">Sign in</a><a class="btn-ghost" href="account.html?tab=register">Create a free account</a></div></div>`;
  $(bodyId).classList.toggle("hidden", !ok);
  return ok;
}
async function loadFlights() {
  if (!gate("flightsGate", "flightsBody", "An account lets you register your drones, watch flights, request permission from the authority and get alerted when a restriction appears. Checking a spot never needs an account.")) return;
  await refreshMe().catch(() => {});
  await loadDrones();
  renderChecklist();
  $("flightList").innerHTML = skeleton();
  try {
    const list = await api("/flights");
    $("flightList").innerHTML = list.length ? list.map(flightCard).join("") : '<div class="hint">No flights yet. Check a spot, then press Watch or Request permission.</div>';
    $("flightList").querySelectorAll("[data-pre]").forEach(b => b.addEventListener("click", () => runPreflight(b.dataset.pre)));
    $("flightList").querySelectorAll("[data-show]").forEach(b => b.addEventListener("click", () => { const [a, o] = b.dataset.show.split(",").map(Number); map.setView([a, o], 14); }));
    $("flightList").querySelectorAll("[data-cancel]").forEach(b => b.addEventListener("click", async () => { await api("/flights/" + b.dataset.cancel + "/cancel", { method: "POST" }); loadFlights(); }));
  } catch (e) { $("flightList").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}
function flightCard(f) {
  const pm = f.permit;
  const permit = pm ? `<div class="permit"><div>
      <div class="k">Permit</div><div class="mono"><b>${esc(pm.permit_id)}</b> <span class="tag ${esc(pm.status)}">${esc(STATUS_LABEL[pm.status] || pm.status)}</span></div>
      <div class="meta">Max ${esc(pm.alt_max_m)} m, ${esc(fmtWhen(pm.starts_at))} to ${esc(fmtWhen(pm.ends_at))}</div>
      <div class="meta">Issued by ${esc(pm.issued_by)}</div>
      ${pm.conditions.length ? `<div class="meta">Conditions: ${esc(pm.conditions.join("; "))}</div>` : ""}
      ${pm.revoked_reason ? `<div class="meta" style="color:var(--red)">Revoked: ${esc(pm.revoked_reason)}</div>` : ""}
    </div><div class="qr">${qrSvg("skyclear:permit:" + pm.permit_id + ":" + pm.signature.slice(0, 12))}</div></div>` : "";
  const canPre = ["approved", "watching"].includes(f.status) && (pm || f.verdict !== "permission_needed");
  return `<div class="item">
    <div class="head"><span class="title mono">${esc(f.flight_id)}</span><span class="tag ${esc(f.status)}">${esc(STATUS_LABEL[f.status] || f.status)}</span></div>
    <div>${esc(f.drone_name)} <span class="muted">(${esc(f.drone_class)})</span></div>
    <div class="meta">${esc(fmtWhen(f.start))} to ${esc(fmtWhen(f.end))}</div>
    <div class="meta mono">${f.lat.toFixed(4)}, ${f.lng.toFixed(4)}</div>
    ${f.zones.length ? `<div class="meta">${esc(f.zones.join(", "))}</div>` : ""}
    ${f.purpose ? `<div class="meta">Purpose: ${esc(f.purpose)}</div>` : ""}
    ${f.routed_to ? `<div class="route">${routeText(f.routed_to)}${f.overdue ? '<div class="meta" style="color:var(--red)">Overdue, escalated to the supervising office.</div>' : ""}</div>` : ""}
    ${f.decision ? `<div class="msg">${esc(f.decision.by)}: ${esc(f.decision.comment || "No comment")}</div>` : ""}
    ${permit}
    <div id="pre-${esc(f.flight_id)}"></div>
    <div class="btnrow">
      ${canPre ? `<button class="inline" type="button" data-pre="${esc(f.flight_id)}">Preflight</button>` : ""}
      <button class="ghost inline" type="button" data-show="${f.lat},${f.lng}">Show on map</button>
      ${["watching", "requested", "approved"].includes(f.status) ? `<button class="ghost inline" type="button" data-cancel="${esc(f.flight_id)}">Cancel</button>` : ""}
    </div></div>`;
}

async function runPreflight(id) {
  const out = $("pre-" + id);
  out.innerHTML = skeleton();
  try {
    const r = await api(`/flights/${id}/preflight`, { method: "POST" });
    out.innerHTML = r.cleared
      ? `<div class="cleared">Cleared for takeoff until ${esc(fmtWhen(r.cleared_until))}</div>${r.conditions.length ? `<div class="meta">Conditions: ${esc(r.conditions.join("; "))}</div>` : ""}<div class="small">Checked ${esc(fmtWhen(r.checked_at))}. Cleared means every check passed now. Conditions can change, check again before you fly.</div>`
      : `<div class="msg err"><b>Not cleared</b><ul class="reasons">${r.reasons.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>`;
  } catch (e) { out.innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}

$("droneForm").addEventListener("submit", async e => {
  e.preventDefault();
  try { await api("/me/drones", { method: "POST", body: { name: $("dName").value, weight_g: Number($("dWeight").value), uin: $("dUin").value || null } }); e.target.reset(); await loadDrones(); }
  catch (err) { $("myDrones").insertAdjacentHTML("beforeend", `<div class="msg err">${esc(err.message)}</div>`); }
});

/* ---------- alerts ---------- */
let lastUnread = 0;
function setUnread(n, items) {
  const c = $("alertCount");
  c.textContent = n; c.classList.toggle("hidden", n === 0);
  document.title = (n ? `(${n}) ` : "") + "SkyClear, pilot";
  const high = (items || []).find(a => !a.read && a.severity === "high");
  $("banner").classList.toggle("hidden", !high);
  if (high) $("bannerText").textContent = high.title + ". " + high.body;
}
async function pollAlerts() {
  if (!me()) return;
  try {
    const a = await api("/notifications");
    setUnread(a.unread, a.items);
    if (a.unread !== lastUnread && tab === "alerts") renderAlerts(a);
    lastUnread = a.unread;
    return a;
  } catch (e) { /* offline, try again next tick */ }
}
function renderAlerts(a) {
  $("alertList").innerHTML = a.items.length ? a.items.map(n => `
    <div class="alert ${n.read ? "" : "unread"} ${esc(n.severity)}">
      <div class="title">${esc(n.title)}</div><div>${esc(n.body)}</div>
      <div class="meta">${esc(fmtWhen(n.created_at))}${n.flight_id ? ", flight " + esc(n.flight_id) : ""}</div>
    </div>`).join("") : '<div class="hint">No alerts yet. When an authority publishes a restriction that touches one of your flights, it appears here.</div>';
}
async function loadAlerts() {
  if (!gate("alertsGate", "alertsBody", "Alerts tell you when an official restriction touches one of your flights, and when an officer decides your request. Sign in to receive them.")) return;
  $("alertList").innerHTML = skeleton();
  const a = await pollAlerts(); if (a) renderAlerts(a);
}
$("markRead").addEventListener("click", async () => { await api("/notifications/read", { method: "POST" }); loadAlerts(); });
$("bannerBtn").addEventListener("click", () => showTab("alerts"));

/* ---------- start ---------- */
$("when").value = toLocalInput(new Date()); $("simWhen").value = $("when").value;
drawZones(layers); drawNotices(layers.notices); loadDrones();
window.addEventListener("skyclear:theme", () => { drawZones(layers); drawNotices(layers.notices); });
if (me()) { refreshMe().catch(() => {}); pollAlerts(); setInterval(() => { pollAlerts(); drawNotices(layers.notices); }, 5000); }

function loadExampleRoute() {
  if (!exampleRoute) return;
  clearRoute(); map.fitBounds(exampleRoute, { padding: [60, 60] });
  exampleRoute.forEach(([lat, lng]) => addWaypoint(L.latLng(lat, lng)));
}

/* ---------- ask about the rules ---------- */
const ASK_EXAMPLES = ["Do I need permission to fly near an airport?", "Can I fly over a military area?", "What are the rules for parks?", "What happens during a VIP movement?"];
$("askExamples").innerHTML = ASK_EXAMPLES.map(q => `<button type="button">${esc(q)}</button>`).join("");
$("askExamples").querySelectorAll("button").forEach(b => b.addEventListener("click", () => { $("askQ").value = b.textContent; $("askForm").requestSubmit(); }));
function updateAskSpot() {
  const box = $("askSpot");
  box.disabled = !picked;
  $("askSpotText").textContent = picked ? `Use the spot I picked on the map (${picked.lat.toFixed(4)}, ${picked.lng.toFixed(4)})` : "Use the spot I picked on the map (pick one in the Check tab first)";
  if (!picked) box.checked = false;
}
$("askForm").addEventListener("submit", async e => {
  e.preventDefault();
  const body = { question: $("askQ").value };
  if ($("askSpot").checked && picked) Object.assign(body, { lat: picked.lat, lng: picked.lng, drone_id: $("drone").value, datetime: toISO($("when").value) });
  const btn = $("askGo"); btn.disabled = true; btn.textContent = "Searching the rules...";
  $("askResult").innerHTML = skeleton();
  try {
    const r = await api("/ask", { method: "POST", auth: false, body });
    const spot = r.spot ? `<div class="explain" style="margin-top:10px"><b>For your spot:</b> ${esc(VERDICT_LABEL[r.spot.verdict])}${r.spot.zones.length ? ", inside " + esc(r.spot.zones.join(", ")) : ""}. <span class="small">Decided by rules for ${esc(r.spot.drone)}.</span></div>` : "";
    $("askResult").innerHTML = `
      <div class="explain" style="background:var(--panel);border-color:var(--rule-strong)">${esc(r.answer)}</div>${spot}
      ${r.citations.length ? `<div class="section"><h3>The rules behind this answer</h3>${r.citations.map(c => `<div class="cite"><span class="id">${esc(c.rule_id)}</span>${esc(c.text)}<div class="small">${esc(c.source)}</div></div>`).join("")}</div>` : ""}
      <div class="small">Found with ${esc(r.retrieval)}. ${r.answered_by === "llm" ? "Worded by an AI model from these rules only." : r.answered_by === "extracted" ? "Taken directly from the rules, no AI guessing." : ""} ${esc(r.disclaimer)}</div>`;
  } catch (err) { $("askResult").innerHTML = `<div class="msg err">${esc(err.message)}</div>`; }
  finally { btn.disabled = false; btn.textContent = "Ask"; }
});

// Authority console: review permission requests, publish and cancel notices, see the overview.
const sess = session();
if (!sess || sess.user.role !== "official") { location.href = "account.html"; }
header("official");
const { map, layers } = makeMap();
let tab = "requests", filter = "requested", centre = null, preview = null;
const reqLayer = L.layerGroup().addTo(layers.work);

function showTab(t) {
  tab = t;
  document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  ["requests", "publish", "notices"].forEach(x => $("tab-" + x).classList.toggle("hidden", x !== t));
  if (t === "requests") loadRequests(); if (t === "notices") loadNotices();
}
document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));

async function loadStats() {
  try {
    const o = await api("/overview");
    const cell = (n, l) => `<td><span class="n">${n}</span><span class="l">${l}</span></td>`;
    $("stats").innerHTML = `<tr>${cell(o.pending_requests, "Pending")}${cell(o.approved, "Approved")}${cell(o.watching, "Watching")}${cell(o.active_notices, "Notices")}</tr>`;
    const c = $("reqCount"); c.textContent = o.pending_requests; c.classList.toggle("hidden", o.pending_requests === 0);
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
    $("reqList").innerHTML = list.length ? list.map(f => `
      <div class="item" id="r-${esc(f.flight_id)}">
        <div class="head"><span class="title mono">${esc(f.flight_id)}</span><span class="tag ${esc(f.status)}">${esc(STATUS_LABEL[f.status] || f.status)}</span></div>
        <div><b>${esc(f.pilot_name)}</b> <span class="muted">${f.pilot_cert ? "cert " + esc(f.pilot_cert) + " (self-declared)" : "no certificate given"}</span></div>
        <div>${esc(f.drone_name)} <span class="muted">class ${esc(f.drone_class)}${f.uin ? ", reg. " + esc(f.uin) + " (self-declared)" : ""}</span></div>
        <div class="meta">${esc(fmtWhen(f.start))} to ${esc(fmtWhen(f.end))}</div>
        <div class="meta mono">${f.lat.toFixed(4)}, ${f.lng.toFixed(4)}</div>
        <div class="meta">System verdict: ${esc(VERDICT_LABEL[f.verdict])}${f.zones.length ? ", " + esc(f.zones.join(", ")) : ""}${f.rule_ids.length ? ", rules " + esc(f.rule_ids.join(", ")) : ""}</div>
        ${f.purpose ? `<div class="meta">Purpose: ${esc(f.purpose)}</div>` : ""}
        ${f.decision ? `<div class="msg">${esc(f.decision.by)}: ${esc(f.decision.comment || "No comment")}</div>` : ""}
        <div class="btnrow"><button class="ghost inline" type="button" data-show="${f.lat},${f.lng}">Show on map</button></div>
        ${f.status === "requested" ? `
          <label for="c-${esc(f.flight_id)}">Comment to pilot (required to reject)</label>
          <input id="c-${esc(f.flight_id)}" maxlength="300" placeholder="e.g. Keep below 60 m, daylight only">
          <div class="btnrow"><button class="inline" type="button" data-decide="approved" data-id="${esc(f.flight_id)}" style="margin-top:8px">Approve</button>
          <button class="danger inline" type="button" data-decide="rejected" data-id="${esc(f.flight_id)}" style="margin-top:8px">Reject</button></div>
          <div id="m-${esc(f.flight_id)}"></div>` : ""}
      </div>`).join("") : `<div class="hint">${filter === "requested" ? "No pending requests." : "No flights yet."}</div>`;
    $("reqList").querySelectorAll("[data-show]").forEach(b => b.addEventListener("click", () => { const [a, o] = b.dataset.show.split(",").map(Number); map.setView([a, o], 14); }));
    $("reqList").querySelectorAll("[data-decide]").forEach(b => b.addEventListener("click", () => decide(b.dataset.id, b.dataset.decide)));
  } catch (e) { $("reqList").innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}
async function decide(id, decision) {
  try { await api(`/flights/${id}/decision`, { method: "POST", body: { decision, comment: $("c-" + id).value } }); loadRequests(); loadStats(); }
  catch (e) { $("m-" + id).innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
}

/* ---------- publish ---------- */
function drawPreview() {
  if (preview) { layers.work.removeLayer(preview); preview = null; }
  if (centre) preview = L.circle(centre, { radius: (Number($("nRadius").value) || 0) * 1000, color: NOTICE_COLOR, weight: 2, dashArray: "6 5", fillOpacity: 0.12 }).addTo(layers.work);
}
map.on("click", e => {
  if (tab !== "publish") return;
  centre = e.latlng; drawPreview();
  $("nCenter").innerHTML = `Centre <span class="mono">${centre.lat.toFixed(4)}, ${centre.lng.toFixed(4)}</span>`;
  $("nGo").disabled = false;
});
$("nRadius").addEventListener("input", drawPreview);
$("noticeForm").addEventListener("submit", async e => {
  e.preventDefault();
  $("nGo").disabled = true;
  try {
    const n = await api("/notices", { method: "POST", body: { title: $("nTitle").value, note: $("nNote").value, lat: centre.lat, lng: centre.lng,
      radius_km: Number($("nRadius").value), starts_at: toISO($("nStart").value), ends_at: toISO($("nEnd").value) } });
    $("nMsg").innerHTML = `<div class="msg">Published <span class="mono">${esc(n.notice_id)}</span>. ${n.affected_flights} flight${n.affected_flights === 1 ? "" : "s"} overlapped and the pilot${n.affected_flights === 1 ? " was" : "s were"} alerted.</div>`;
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
        <div class="meta">${esc(fmtWhen(n.starts_at))} to ${esc(fmtWhen(n.ends_at))}, radius ${esc(n.radius_km)} km</div>
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
setInterval(() => { loadStats(); if (tab === "requests") loadRequests(); }, 6000);

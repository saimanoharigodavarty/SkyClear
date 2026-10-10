// Guard page: listens to the public alert stream and sounds a siren on this device. No sign-in, nothing about the pilot is received.
let es = null, ctx = null, siren = null, wake = null, on = false;
const status = (text, kind) => { $("gStatus").textContent = text; $("gStatus").className = "gstatus " + kind; };

async function loadAreas() {
  try { (await api("/notices/active", { auth: false })).forEach(n => { if (![...$("gArea").options].some(o => o.value === n.title)) { const o = document.createElement("option"); o.value = n.title; o.textContent = n.title; $("gArea").appendChild(o); } }); } catch (e) { /* the list stays as it is */ }
}
loadAreas().then(() => {
  const want = new URLSearchParams(location.search).get("area");
  if (want) { if (![...$("gArea").options].some(o => o.value === want)) { const o = document.createElement("option"); o.value = want; o.textContent = want; $("gArea").appendChild(o); } $("gArea").value = want; }
});
setInterval(loadAreas, 20000);  // an area declared after this page was opened shows up in the list

function startSiren() {
  stopSiren();
  if (!ctx) return;
  const osc = ctx.createOscillator(), gain = ctx.createGain();
  osc.type = "square"; gain.gain.value = 0.35; osc.connect(gain).connect(ctx.destination); osc.start();
  let hi = true; const t = setInterval(() => { osc.frequency.setValueAtTime(hi ? 960 : 640, ctx.currentTime); hi = !hi; }, 350);
  osc.frequency.value = 960; siren = { osc, t };
  const buzz = setInterval(() => navigator.vibrate && navigator.vibrate([300, 150, 300]), 900); siren.buzz = buzz;
}
function stopSiren() {
  if (!siren) return;
  clearInterval(siren.t); clearInterval(siren.buzz); try { siren.osc.stop(); } catch (e) { /* already stopped */ } siren = null; navigator.vibrate && navigator.vibrate(0);
}
function approaching(a) {  // a softer first signal: the drone is about to enter the area
  status("A drone is about to enter " + a.area + ".", "warning");
  if (ctx) for (let i = 0; i < 3; i++) setTimeout(() => { const o = ctx.createOscillator(), g = ctx.createGain(); o.frequency.value = 880; g.gain.value = 0.2; o.connect(g).connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.18); }, i * 350);
  navigator.vibrate && navigator.vibrate([150, 80, 150]);
}
function alarm(a) {
  $("gAlarm").classList.remove("hidden");
  $("gWhere").textContent = a.kind === "test" ? "Test alert: " + a.area : a.area;
  $("gWhen").textContent = new Date(a.ts || Date.now()).toLocaleTimeString("en-IN", { hour12: false });
  startSiren();
  clearTimeout(alarm.t); alarm.t = setTimeout(() => { stopSiren(); }, 30000);  // the siren stops by itself after 30 seconds, the red screen stays until dismissed
}
$("gQuiet").addEventListener("click", () => { stopSiren(); $("gAlarm").classList.add("hidden"); });

function connect() {
  if (es) es.close();
  const area = $("gArea").value;
  es = new EventSource(API_BASE + "/guard/stream" + (area ? "?area=" + encodeURIComponent(area) : ""));
  es.addEventListener("ready", () => status("Listening" + (area ? " for " + area : " for every declared area") + ". Keep this page open.", "ok"));
  es.addEventListener("alert", ev => { try { const a = JSON.parse(ev.data); if (a.kind === "approaching") approaching(a); else alarm(a); } catch (e) { /* ignore a bad event */ } });
  es.onerror = () => status("Lost the connection to SkyClear, trying again...", "warning");
}

$("gOn").addEventListener("click", async () => {
  if (on) { on = false; if (es) es.close(); stopSiren(); if (wake) wake.release().catch(() => {}); $("gOn").textContent = "Turn alerts on"; $("gTest").disabled = true; status("Alerts are off.", "idle"); return; }
  try { ctx = ctx || new (window.AudioContext || window.webkitAudioContext)(); await ctx.resume(); } catch (e) { status("This browser cannot play sound.", "breach"); return; }
  try { if (navigator.wakeLock) wake = await navigator.wakeLock.request("screen"); } catch (e) { /* the screen may sleep, alerts still work while the page is open */ }
  on = true; $("gOn").textContent = "Turn alerts off"; $("gTest").disabled = false; connect();
});
$("gArea").addEventListener("change", () => { if (on) connect(); });
$("gTest").addEventListener("click", () => alarm({ area: $("gArea").value || "this device", kind: "test", ts: new Date().toISOString() }));
document.addEventListener("visibilitychange", async () => { if (on && document.visibilityState === "visible" && navigator.wakeLock) { try { wake = await navigator.wakeLock.request("screen"); } catch (e) { /* ignore */ } } });


/* ---------- push notifications: they reach this device with the page closed. Needs https, or localhost. ---------- */
const pushOk = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const b64ToBytes = b => { const p = "=".repeat((4 - b.length % 4) % 4), raw = atob((b + p).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from(raw, c => c.charCodeAt(0)); };
if (pushOk) {
  $("gPush").classList.remove("hidden");
  navigator.serviceWorker.getRegistration("/").then(r => r && r.pushManager.getSubscription()).then(sub => { if (sub) $("gPush").textContent = "Stop notifications when this page is closed"; }).catch(() => {});
}
$("gPush").addEventListener("click", async () => {
  const note = $("gPushNote"); note.classList.remove("hidden");
  if (!window.isSecureContext) { note.textContent = "Notifications need a secure address. This page is on plain http, which browsers refuse for push. It works on localhost, or behind an https link. The siren while the page is open still works."; return; }
  try {
    const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" }); await navigator.serviceWorker.ready;
    const existing = await reg.pushManager.getSubscription();
    if (existing) {
      await api("/guard/push-unsubscribe", { method: "POST", auth: false, body: { endpoint: existing.endpoint, keys: {} } }).catch(() => {}); await existing.unsubscribe();
      $("gPush").textContent = "Also notify me when this page is closed"; note.textContent = "Notifications are off."; return;
    }
    if ((await Notification.requestPermission()) !== "granted") { note.textContent = "Notifications are blocked for this site. Allow them in the browser settings."; return; }
    const { key } = await api("/guard/push-key", { auth: false });
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(key) });
    const j = sub.toJSON();
    await api("/guard/push-subscribe", { method: "POST", auth: false, body: { endpoint: j.endpoint, keys: j.keys, area: $("gArea").value || null } });
    $("gPush").textContent = "Stop notifications when this page is closed"; note.textContent = "Done. An alert now shows as a notification even when this page is closed.";
  } catch (e) { note.textContent = "Could not turn notifications on: " + e.message; }
});

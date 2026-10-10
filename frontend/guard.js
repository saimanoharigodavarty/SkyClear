// Guard page: listens to the public alert stream and sounds a siren on this device. No sign-in, nothing about the pilot is received.
let es = null, ctx = null, siren = null, wake = null, on = false;
const status = (text, kind) => { $("gStatus").textContent = text; $("gStatus").className = "gstatus " + kind; };

(async function areas() {
  try { (await api("/notices/active", { auth: false })).forEach(n => { const o = document.createElement("option"); o.value = n.title; o.textContent = n.title; $("gArea").appendChild(o); }); } catch (e) { /* the list stays with "every area" */ }
  const want = new URLSearchParams(location.search).get("area");
  if (want) { if (![...$("gArea").options].some(o => o.value === want)) { const o = document.createElement("option"); o.value = want; o.textContent = want; $("gArea").appendChild(o); } $("gArea").value = want; }
})();

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
  es.addEventListener("alert", ev => { try { alarm(JSON.parse(ev.data)); } catch (e) { /* ignore a bad event */ } });
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

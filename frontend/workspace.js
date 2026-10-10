// The workspace on the home page: the whole platform as one ordered path for whoever is signed in, with a live count where there is one.
(async function workspace() {
  const box = $("workspace"); if (!box) return;
  const s = session(), role = s ? s.user.role : null;
  const steps = {
    visitor: [
      ["Check a spot", "Click the map. The code decides the verdict, the AI explains and cites the rule.", "index.html#check", "Open the map"],
      ["Ask the rules", "Ask a plain question. The rules appear at once, the AI wording fills in.", "index.html#ask", "Ask"],
      ["Sign in to fly legally", "Create a pilot account, register your drone, get verified.", "signin.html?tab=register", "Create an account"],
      ["Protect an area", "Anyone inside a declared area can turn on guard alerts on their own device.", "guard.html", "Open guard alerts"],
    ],
    pilot: [
      ["Check a spot", "Is it allowed here, now, with this drone? Rules and nearby zones.", "index.html#check", "Open the map", null],
      ["Request permission", "In a yellow zone, send a request. It is routed to the right office.", "index.html#check", "Pick a spot", "requests"],
      ["Permit and preflight", "An approved request becomes a signed permit. Preflight clears the flight.", "index.html#flights", "My flights", "ready"],
      ["Fly it, in 3D", "Take off on the big screen, fly from your phone, watch the map and the drone view.", "display.html", "Open the 3D screen", null],
      ["Alerts", "Decisions, restrictions and breaches that touch your flights.", "index.html#alerts", "Open alerts", "alerts"],
      ["Guard alerts", "Turn on siren alerts on this device for a protected area.", "guard.html", "Open guard alerts", null],
    ],
    official: [
      ["Decide requests", "Permission requests routed to your office, with the rules that apply.", "official.html#requests", "Open the queue", "pending"],
      ["Verify pilots and drones", "Check documents before someone may request permission.", "official.html#verify", "Open verification", "verify"],
      ["Watch the sky", "Flights in the air, breaches, recall a drone, watch any flight in 3D.", "official.html#live", "Open live", "flying"],
      ["Declare an area", "Draw a boundary or a circle. Pilots with flights there are alerted.", "official.html#publish", "Publish an area", null],
      ["Guard alerts and drill", "Link and QR for devices in the area, a test siren, a drill with a simulated drone.", "official.html#notices", "Open notices", "notices"],
      ["Insights and audit", "What the data says, who did what, how updates reach the screens.", "official.html#insights", "Open insights", null],
    ],
  };
  const list = steps[role] || steps.visitor;
  box.innerHTML = `<h2 class="ws-title">${role === "official" ? "Your console" : role === "pilot" ? "Your workspace" : "Where to start"}</h2>
    <p class="ws-lead">${role ? `Signed in as ${esc(s.user.name)}, ${esc(role)}.` : "Everything is one path. Start at the first step."}</p>
    <ol class="pipeline">${list.map((st, i) => `<li><span class="pn">${i + 1}</span><div class="pb"><b>${esc(st[0])}</b><span>${esc(st[1])}</span></div><span class="pc" data-k="${esc(st[4] || "")}"></span><a class="btn-sm" href="${esc(st[2])}">${esc(st[3])}</a></li>`).join("")}</ol>`;
  const put = (k, n, label) => { const e = box.querySelector(`.pc[data-k="${k}"]`); if (e && n > 0) e.textContent = `${n} ${label}`; };
  try {
    if (role === "pilot") {
      const [a, f] = await Promise.all([api("/notifications").catch(() => null), api("/flights").catch(() => [])]);
      if (a) put("alerts", a.unread, "unread");
      put("ready", f.filter(x => ["approved", "cleared", "flying"].includes(x.status) && new Date(x.end) > new Date()).length, "ready");
      put("requests", f.filter(x => x.status === "requested").length, "waiting");
    } else if (role === "official") {
      const o = await api("/overview").catch(() => null);
      if (o) { put("pending", o.pending_requests, "waiting"); put("notices", o.active_notices, "active"); }
      const q = await api("/verification/queue").catch(() => []); put("verify", q.length, "waiting");
      const f = await api("/flights").catch(() => []); put("flying", f.filter(x => x.status === "flying").length, "in the air");
    }
  } catch (e) { /* the counts are a bonus */ }
})();

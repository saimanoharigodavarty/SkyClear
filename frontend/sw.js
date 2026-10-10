// Service worker for guard alerts: shows a notification when the server pushes one, even if the guard page is closed.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("push", e => {
  let m = { title: "SkyClear guard alert", body: "", kind: "intrusion" };
  try { m = { ...m, ...e.data.json() }; } catch (err) { /* keep the default text */ }
  e.waitUntil(self.registration.showNotification(m.title, {
    body: m.body, tag: "skyclear-guard-" + m.kind, renotify: true, requireInteraction: m.kind !== "test",
    vibrate: m.kind === "intrusion" ? [400, 150, 400, 150, 400, 150, 400] : [200, 100, 200], data: { url: "/guard.html" },
  }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    const open = list.find(c => c.url.includes("/guard.html"));
    return open ? open.focus() : self.clients.openWindow((e.notification.data && e.notification.data.url) || "/guard.html");
  }));
});

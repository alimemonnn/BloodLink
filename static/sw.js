/* BloodLink service worker: shows push notifications and a friendly offline page.
   It never caches pages that contain personal data. */
const OFFLINE_URL = "/offline";
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open("bloodlink-offline-v1").then((c) => c.add(OFFLINE_URL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE_URL)));
});
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { /* ignore malformed payload */ }
  event.waitUntil(self.registration.showNotification(data.title || "BloodLink", {
    body: data.body || "You have a new update.",
    icon: "/static/images/pwa/icon-192.png", badge: "/static/images/pwa/icon-192.png",
    data: { url: data.url || "/" }
  }));
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(self.clients.matchAll({ type: "window" }).then((list) => {
    for (const c of list) { if ("focus" in c) { c.navigate(target); return c.focus(); } }
    return self.clients.openWindow(target);
  }));
});

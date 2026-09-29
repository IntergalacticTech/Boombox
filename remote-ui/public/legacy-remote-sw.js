// Kill-switch for the old phone remote's service worker (scope /remote/).
// nginx serves this file at /remote/sw.js, so an installed old PWA's update
// check finds a "new" worker: it installs at once, drops the old app's
// caches, unregisters itself and sends any open old-app tab to the new app
// (/?from=remote shows the one-time "reinstall from this address" hint).
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys
      .filter((key) => key.includes("/remote/"))
      .map((key) => caches.delete(key)));
    await self.registration.unregister();
    const clients = await self.clients.matchAll({ type: "window" });
    for (const client of clients) client.navigate("/?from=remote");
  })());
});

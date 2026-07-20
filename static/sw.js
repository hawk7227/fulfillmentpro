self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const cacheNames = await caches.keys();
      await Promise.all(cacheNames.map((name) => caches.delete(name)));

      await self.clients.claim();

      const registration = await self.registration;
      await registration.unregister();

      const clients = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true
      });

      for (const client of clients) {
        client.navigate(client.url);
      }
    })()
  );
});

self.addEventListener("fetch", () => {
  // Intentionally do not intercept requests.
});

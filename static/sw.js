const CACHE_NAME = 'fulfillment-v2';

const STATIC_ASSETS = [
  '/manifest.json'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();

  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    Promise.all([
      caches.keys().then((cacheNames) => {
        return Promise.all(
          cacheNames
            .filter((name) => name !== CACHE_NAME)
            .map((name) => caches.delete(name))
        );
      }),
      self.clients.claim()
    ])
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;

  if (request.method !== 'GET') {
    return;
  }

  const url = new URL(request.url);

  // Always retrieve dashboard pages and API data from the network.
  if (
    request.mode === 'navigate' ||
    url.pathname === '/' ||
    url.pathname === '/index.html' ||
    url.pathname.startsWith('/api/')
  ) {
    event.respondWith(
      fetch(request).catch(() => caches.match(request))
    );
    return;
  }

  // Cache-first is acceptable only for static assets.
  event.respondWith(
    caches.match(request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }

      return fetch(request).then((networkResponse) => {
        const responseCopy = networkResponse.clone();

        caches.open(CACHE_NAME).then((cache) => {
          cache.put(request, responseCopy);
        });

        return networkResponse;
      });
    })
  );
});

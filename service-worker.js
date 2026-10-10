const CACHE_NAME = 'sovapp-cache-v2';
const ASSETS = [
  '/',
  '/index.html',
  '/tasks.html',
  '/manifest.json',
  '/qrcode.min.js'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  if (e.request.url.includes('/api/')) {
    e.respondWith(
      fetch(e.request).catch(() => new Response(JSON.stringify({ offline: true }), { headers: { 'Content-Type': 'application/json' } }))
    );
    return;
  }

  // Network First for HTML navigation requests
  if (e.request.mode === 'navigate' || e.request.destination === 'document') {
    e.respondWith(
      fetch(e.request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(e.request, copy));
          return response;
        })
        .catch(() => {
          return caches.match(e.request).then((res) => res || caches.match('/tasks.html'));
        })
    );
    return;
  }

  // Cache First for other assets
  e.respondWith(
    caches.match(e.request).then((res) => res || fetch(e.request))
  );
});

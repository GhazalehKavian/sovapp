const CACHE_NAME = 'sovapp-cache-v1';
const ASSETS = [
  '/',
  '/tasks.html',
  '/manifest.json'
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
  // درخواست‌های دیتابیس و همگام‌سازی نباید از کش خوانده شوند
  if (e.request.url.includes('/api/')) {
    e.respondWith(fetch(e.request).catch(() => new Response(JSON.stringify({ offline: true }), { headers: { 'Content-Type': 'application/json' } })));
    return;
  }
  // کش کردن ظاهر برنامه برای باز شدن در هر شرایطی
  e.respondWith(
    caches.match(e.request).then((res) => res || fetch(e.request))
  );
});
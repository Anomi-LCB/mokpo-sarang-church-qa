const SHELL_CACHE = 'church-search-shell-v3';
const ASSET_CACHE = 'church-search-assets-v3';
const SHELL_URLS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
  '/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_URLS))
      .catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter(
            (k) =>
              k !== SHELL_CACHE &&
              k !== ASSET_CACHE &&
              k !== 'church-search-offline-pdfs-v1'
          )
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Never intercept live API calls or APK binaries (offline data lives in IndexedDB / dedicated PDF cache)
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/downloads/')) {
    return;
  }

  // Hashed Vite assets: cache-first for instant offline boot on iOS/Android PWA
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.open(ASSET_CACHE).then(async (cache) => {
        const cached = await cache.match(req);
        if (cached) return cached;
        const fresh = await fetch(req);
        if (fresh && fresh.ok) {
          cache.put(req, fresh.clone()).catch(() => {});
        }
        return fresh;
      })
    );
    return;
  }

  // App shell navigations & static icons: network-first with cached fallback
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res && res.ok) {
            caches.open(SHELL_CACHE).then((c) => c.put('/index.html', res.clone())).catch(() => {});
          }
          return res;
        })
        .catch(async () => {
          const cached = await caches.match('/index.html');
          return cached || (await caches.match('/')) || new Response('오프라인 상태입니다.', { status: 503 });
        })
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((res) => {
        if (res && res.ok) {
          caches.open(SHELL_CACHE).then((c) => c.put(req, res.clone())).catch(() => {});
        }
        return res;
      });
    })
  );
});

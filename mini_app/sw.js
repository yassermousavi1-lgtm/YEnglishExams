// ============================================================
// YEnglish Exams — Service Worker (v3)
// ============================================================

const CACHE_VERSION = 'yenglish-v3';
const STATIC_ASSETS = [
    '/',
    '/index.html',
    '/style.css',
    'https://telegram.org/js/telegram-web-app.js'
];

// ----- Install: pre-cache static assets -----
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_VERSION).then(async (cache) => {
            for (const asset of STATIC_ASSETS) {
                try {
                    const response = await fetch(asset, { cache: 'reload' });
                    if (response.ok) {
                        await cache.put(asset, response);
                    }
                } catch (err) {
                    console.warn('SW pre-cache failed for', asset, err);
                }
            }
        }).then(() => self.skipWaiting())
    );
});

// ----- Activate: clean up old caches -----
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.map((key) => {
                    if (key !== CACHE_VERSION) {
                        return caches.delete(key);
                    }
                })
            );
        }).then(() => self.clients.claim())
    );
});

// ----- Fetch -----
self.addEventListener('fetch', (event) => {
    const req = event.request;

    // Only handle GET
    if (req.method !== 'GET') return;

    const url = new URL(req.url);

    // Never intercept API calls
    if (url.pathname.startsWith('/api/')) return;

    // Only handle same-origin + the Telegram script
    const isSameOrigin = url.origin === self.location.origin;
    const isTelegramScript = req.url.indexOf('telegram-web-app.js') !== -1;
    if (!isSameOrigin && !isTelegramScript) return;

    // Detect navigation requests (opening the Mini App)
    const isNavigation =
        req.mode === 'navigate' ||
        req.destination === 'document' ||
        req.destination === '';

    event.respondWith(
        fetch(req)
            .then((response) => {
                if (response && response.ok) {
                    const clone = response.clone();
                    caches.open(CACHE_VERSION).then((cache) => {
                        cache.put(req, clone).catch(() => {});
                    });
                }
                return response;
            })
            .catch(async () => {
                // 1) Exact match (ignore query params like tgWebAppData=...)
                const exact = await caches.match(req, { ignoreSearch: true });
                if (exact) return exact;

                // 2) For navigation: always fall back to index.html
                if (isNavigation) {
                    const indexFallback =
                        (await caches.match('/index.html', { ignoreSearch: true })) ||
                        (await caches.match('/', { ignoreSearch: true }));
                    if (indexFallback) return indexFallback;
                }

                // 3) Nothing in cache
                return new Response('Offline', {
                    status: 503,
                    statusText: 'Offline',
                    headers: { 'Content-Type': 'text/plain' }
                });
            })
    );
});
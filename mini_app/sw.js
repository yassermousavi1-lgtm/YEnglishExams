// ============================================================
// YEnglish Exams — Service Worker
// ============================================================
//
// Purpose:
//   Cache static files (HTML, CSS, JS) so that the Mini App
//   loads faster and works even if the connection is slow.
//
// Strategy:
//   Network First, Fallback to Cache
//   - Try the network first.
//   - If the network fails, serve the cached version.
//   - For navigation requests, fall back to /index.html.
//
// Versioning:
//   When you change any cached file, bump CACHE_VERSION below
//   to force the old cache to be replaced.
// ============================================================

const CACHE_VERSION = 'yenglish-v2';
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
            // Cache each asset individually so one failure
            // does not prevent the others from being cached.
            for (const asset of STATIC_ASSETS) {
                try {
                    await cache.add(asset);
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

// ----- Fetch: Network First, Fallback to Cache -----
self.addEventListener('fetch', (event) => {
    const req = event.request;

    // Only handle GET requests
    if (req.method !== 'GET') {
        return;
    }

    // Never intercept API calls — always go to network.
    const url = new URL(req.url);
    if (url.pathname.startsWith('/api/')) {
        return;
    }

    // Only handle same-origin requests and the Telegram script
    const isSameOrigin = url.origin === self.location.origin;
    const isTelegramScript = req.url.indexOf('telegram-web-app.js') !== -1;

    if (!isSameOrigin && !isTelegramScript) {
        return;
    }

    event.respondWith(
        fetch(req)
            .then((response) => {
                // Cache the fresh response
                if (response && response.ok) {
                    const responseClone = response.clone();
                    caches.open(CACHE_VERSION).then((cache) => {
                        cache.put(req, responseClone).catch(() => {});
                    });
                }
                return response;
            })
            .catch(() => {
                // Network failed — try the exact cache entry first
                return caches.match(req).then((cached) => {
                    if (cached) {
                        return cached;
                    }

                    // If this is a navigation request (opening the Mini App),
                    // fall back to the cached index.html.
                    if (req.mode === 'navigate') {
                        return caches.match('/index.html').then((indexCached) => {
                            if (indexCached) {
                                return indexCached;
                            }
                            return new Response('Offline', {
                                status: 503,
                                statusText: 'Offline',
                                headers: { 'Content-Type': 'text/plain' }
                            });
                        });
                    }

                    // Nothing in cache and not a navigation — return offline
                    return new Response('Offline', {
                        status: 503,
                        statusText: 'Offline',
                        headers: { 'Content-Type': 'text/plain' }
                    });
                });
            })
    );
});
/// <reference types="@sveltejs/kit" />
/// <reference no-default-lib="true"/>
/// <reference lib="esnext" />
/// <reference lib="webworker" />

// PWA service worker — what makes the app installable (Chrome requires a SW
// with a fetch handler) and gives it a basic offline story. SvelteKit
// auto-registers this file because it lives at src/service-worker.js.
//
// Strategy:
//   - /api/* and cross-origin: never touched — always straight to network.
//   - hashed build assets: cache-first (they're immutable).
//   - navigations: network-first, falling back to the cached SPA shell when
//     offline (so the app still boots and shows its offline banner).
//   - other same-origin GETs (icons, manifest): network, then cache.

import { build, files, version } from '$service-worker';

const sw = /** @type {ServiceWorkerGlobalScope & typeof globalThis} */ (
  /** @type {unknown} */ (self)
);

const CACHE = `seohealth-${version}`;
const SHELL = '/'; // adapter-static fallback is index.html, served at /
const PRECACHE = [SHELL, ...build, ...files];

sw.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => sw.skipWaiting())
  );
});

sw.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => sw.clients.claim())
  );
});

sw.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== location.origin) return; // fonts, Razorpay, etc. — pass through
  if (url.pathname.startsWith('/api')) return; // API is always live

  event.respondWith(respond(request, url));
});

/**
 * @param {Request} request
 * @param {URL} url
 */
async function respond(request, url) {
  const cache = await caches.open(CACHE);

  // Immutable hashed build assets: cache-first.
  if (build.includes(url.pathname)) {
    const hit = await cache.match(url.pathname);
    if (hit) return hit;
  }

  try {
    const response = await fetch(request);
    if (response.ok && (request.mode === 'navigate' || files.includes(url.pathname))) {
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    if (request.mode === 'navigate') {
      const shell = await cache.match(SHELL);
      if (shell) return shell;
    }
    throw err;
  }
}

// --- Web Push --------------------------------------------------------------
// Notifications fired by the backend (scheduled-audit-done, competitor-moved).
// Payload shape: { title, body, url }.

sw.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {};
  }
  const title = data.title || 'SEO Health';
  const options = {
    body: data.body || '',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    data: { url: data.url || '/dashboard' },
    // Coalesce a burst targeting the same place into one notification.
    tag: data.url || 'seo-health'
  };
  event.waitUntil(sw.registration.showNotification(title, options));
});

sw.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = event.notification.data?.url || '/dashboard';
  event.waitUntil(
    sw.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      // Focus an existing tab already on the target; otherwise open a new one.
      for (const client of clients) {
        if (client.url.includes(target) && 'focus' in client) return client.focus();
      }
      return sw.clients.openWindow(target);
    })
  );
});

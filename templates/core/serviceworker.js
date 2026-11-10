/* Partly service worker. Rendered by apps.core.views.serviceworker and served from "/". */
"use strict";

const VERSION = {{ cache_version }};
const SHELL_CACHE = `partly-shell-${VERSION}`;
// Anything user-specific (HTML pages, later /tickets/ + QR passes) lives here and is
// wiped on logout via the CLEAR_USER_CACHE message.
const USER_CACHE = `partly-user-${VERSION}`;
const USER_CACHE_PREFIX = "partly-user-";
const OFFLINE_URL = {{ offline_url }};
const SHELL_ASSETS = {{ shell_assets }};
const NEVER_CACHE = {{ never_cache }};
const TICKETS_PREFIX = "/tickets/";
const FONT_HOSTS = ["fonts.googleapis.com", "fonts.gstatic.com"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll([OFFLINE_URL, ...SHELL_ASSETS]))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  const keep = new Set([SHELL_CACHE, USER_CACHE]);
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k.startsWith("partly-") && !keep.has(k)).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

async function clearUserCaches() {
  const keys = await caches.keys();
  await Promise.all(keys.filter((k) => k.startsWith(USER_CACHE_PREFIX)).map((k) => caches.delete(k)));
}

self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type === "CLEAR_USER_CACHE") {
    const reply = (msg) => { if (event.ports && event.ports[0]) event.ports[0].postMessage(msg); };
    event.waitUntil(
      clearUserCaches().then(() => reply({ ok: true }), (err) => reply({ ok: false, error: String(err) }))
    );
  } else if (data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

function isCacheable(response) {
  if (!response || !response.ok || response.redirected || response.type === "opaqueredirect") return false;
  const cc = response.headers.get("Cache-Control") || "";
  return !/no-store/i.test(cc);
}

async function networkFirstPage(request) {
  const cache = await caches.open(USER_CACHE);
  try {
    const response = await fetch(request);
    if (isCacheable(response)) cache.put(request, response.clone());
    return response;
  } catch (err) {
    const cached = await cache.match(request, { ignoreVary: true });
    if (cached) return cached;
    if (request.mode !== "navigate") return Response.error();
    return (await caches.match(OFFLINE_URL)) || Response.error();
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response && (response.ok || response.type === "opaque")) cache.put(request, response.clone());
      return response;
    })
    .catch(() => cached);
  return cached || network;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  if (FONT_HOSTS.includes(url.hostname)) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }
  if (url.origin !== self.location.origin) return;
  if (NEVER_CACHE.some((prefix) => url.pathname.startsWith(prefix))) return;
  if (url.pathname === "/serviceworker.js") return;

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }
  // Tickets and QR passes: network first, with the last copy kept in the user cache so a
  // guest can still show their pass with no signal at the venue. Wiped on logout.
  if (url.pathname.startsWith(TICKETS_PREFIX)) {
    event.respondWith(networkFirstPage(request));
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(networkFirstPage(request));
  }
});

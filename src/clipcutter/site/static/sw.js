// Minimal service worker: makes the site installable; always uses the network for data (no stale clips).
const SHELL = "cc-shell-v1";
self.addEventListener("install", e => { e.waitUntil(caches.open(SHELL).then(c => c.addAll(["/", "/static/icon.svg"]))); self.skipWaiting(); });
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.pathname.startsWith("/api/")) return;   // never cache API or clips
  if (e.request.mode === "navigate") e.respondWith(fetch(e.request).catch(() => caches.match("/")));
});

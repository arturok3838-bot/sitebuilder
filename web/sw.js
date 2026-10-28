// Service worker ARTurokAI: оболочка сайта работает офлайн, запросы к API — только по сети.
const CACHE = "arturokai-v1";
const SHELL = ["/", "/static/style.css", "/static/app.js", "/icon-192.png", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  // Личные данные и API никогда не кэшируем — всегда свежие с сервера.
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/files") || url.pathname.startsWith("/outputs")) return;
  e.respondWith(
    caches.match(e.request).then((hit) =>
      hit || fetch(e.request).then((resp) => {
        if (resp.ok && resp.type === "basic") {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return resp;
      }).catch(() => hit),
    ),
  );
});

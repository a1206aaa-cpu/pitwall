/* 피트월 노트 — 오프라인 캐시
   앱 껍데기는 캐시해서 바로 띄우고, 데이터(live.json)는 항상 네트워크를 먼저 본다. */
const V = 'pitwall-v1';
const SHELL = ['./', './index.html', './manifest.json',
               './icon-192.png', './icon-512.png', './icon-180.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;           // 폰트 등은 브라우저에 맡김

  if (url.pathname.endsWith('live.json')) {             // 데이터: 네트워크 우선
    e.respondWith(
      fetch(req).then(r => {
        const copy = r.clone();
        caches.open(V).then(c => c.put(req, copy));
        return r;
      }).catch(() => caches.match(req))
    );
    return;
  }
  e.respondWith(                                        // 나머지: 캐시 우선
    caches.match(req).then(hit => hit || fetch(req).then(r => {
      const copy = r.clone();
      caches.open(V).then(c => c.put(req, copy));
      return r;
    }))
  );
});

/* 피트월 노트 — 오프라인 캐시
   페이지와 데이터는 "네트워크 먼저": 새 버전이 올라오면 바로 반영된다.
   네트워크가 안 되면 캐시로 떨어져서 비행기 모드에서도 열린다. */
const V = 'pitwall-v3';
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

const netFirst = req => fetch(req).then(r => {
  const copy = r.clone();
  caches.open(V).then(c => c.put(req, copy));
  return r;
}).catch(() => caches.match(req).then(hit => hit || caches.match('./index.html')));

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;           // 폰트 등은 브라우저에 맡김

  // 페이지와 데이터는 항상 새 걸 먼저 — 앱에 구버전이 박히는 걸 막는다
  if (req.mode === 'navigate' || url.pathname.endsWith('/') ||
      url.pathname.endsWith('index.html') || url.pathname.endsWith('live.json')) {
    e.respondWith(netFirst(req));
    return;
  }
  // 아이콘·매니페스트는 캐시 우선 (바뀔 일이 거의 없음)
  e.respondWith(caches.match(req).then(hit => hit || netFirst(req)));
});

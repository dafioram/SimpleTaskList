/* SimpleTaskList service worker: makes the app open and work with no connection.
 *
 * The app files are cached when the worker installs and served from the cache
 * afterwards. When you change any file, bump VERSION below: the new worker
 * downloads everything again and the app offers a "Reload" to switch over.
 * Your tasks are not stored here (they're in IndexedDB) and are never touched
 * by an update.
 */
var VERSION = 'v1.0.0';
var CACHE = 'simpletasklist-' + VERSION;
var LAZY_CACHE = 'simpletasklist-lazy';   // big files fetched only when needed (database import)

var APP_FILES = [
  './',
  'index.html',
  'styles.css',
  'store.js',
  'importer.js',
  'app.js',
  'manifest.webmanifest',
  'vendor/Sortable.min.js',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/icon-maskable-512.png',
  'icons/apple-touch-icon.png',
  'icons/favicon-32.png'
];
var LAZY_FILES = ['vendor/sql-wasm.js', 'vendor/sql-wasm.wasm'];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      // Bypass the HTTP cache so a new version never picks up stale files.
      return cache.addAll(APP_FILES.map(function (url) { return new Request(url, { cache: 'reload' }); }));
    })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (key) {
        if (key !== CACHE && key !== LAZY_CACHE && key.indexOf('simpletasklist-') === 0) return caches.delete(key);
      }));
    }).then(function () {
      // The database reader may have changed with this version; fetch it fresh next time.
      return caches.open(LAZY_CACHE).then(function (c) {
        return Promise.all(LAZY_FILES.map(function (f) { return c.delete(new URL(f, self.registration.scope).href); }));
      });
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('message', function (event) {
  if (event.data === 'skipWaiting') self.skipWaiting();
});

self.addEventListener('fetch', function (event) {
  var req = event.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Page loads (with or without ?label=... filters) all get the cached app page.
  if (req.mode === 'navigate') {
    event.respondWith(
      caches.match('index.html', { cacheName: CACHE }).then(function (hit) {
        return hit || fetch(req);
      }).catch(function () { return fetch(req); })
    );
    return;
  }

  var path = url.pathname.slice(new URL(self.registration.scope).pathname.length);
  if (LAZY_FILES.indexOf(path) !== -1) {
    event.respondWith(
      caches.open(LAZY_CACHE).then(function (cache) {
        return cache.match(req).then(function (hit) {
          return hit || fetch(req).then(function (res) {
            if (res.ok) cache.put(req, res.clone());
            return res;
          });
        });
      })
    );
    return;
  }

  event.respondWith(
    caches.match(req, { cacheName: CACHE, ignoreSearch: true }).then(function (hit) {
      return hit || fetch(req);
    })
  );
});

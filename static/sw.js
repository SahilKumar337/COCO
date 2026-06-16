/**
 * sw.js — SIFRA AI Service Worker
 * This SW does one job: unregisters itself and clears all caches.
 * SIFRA is a live voice app — no offline caching needed.
 */

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
    event.waitUntil(
        // Delete every cache that exists
        caches.keys()
            .then((keys) => Promise.all(keys.map((k) => caches.delete(k))))
            .then(() => {
                // Unregister this SW so it never intercepts requests again
                self.registration.unregister();
                // Tell all clients to reload with fresh files
                return self.clients.matchAll({ type: 'window' });
            })
            .then((clients) => clients.forEach((client) => client.navigate(client.url)))
    );
});

// Never intercept any fetch — let everything go straight to the network

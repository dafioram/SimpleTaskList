// Copies the web app into www/, the folder Capacitor packs into the Android app.
// The repo root stays the source (GitHub Pages serves it as-is), so this is the
// only list of files the app needs. sw.js is left out: the app ships inside the
// APK, so the native build never registers a service worker.
import { cpSync, rmSync } from "node:fs";

const FILES = [
  "index.html",
  "styles.css",
  "platform.js",
  "store.js",
  "importer.js",
  "app.js",
  "manifest.webmanifest",
  "vendor",
  "icons",
];

rmSync("www", { recursive: true, force: true });
for (const f of FILES) cpSync(f, `www/${f}`, { recursive: true });
console.log(`Copied ${FILES.length} entries into www/`);

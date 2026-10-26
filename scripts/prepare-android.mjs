// Makes the generated android/ project ours: launcher icon, splash colour and
// version numbers. Runs right after `cap add android`.
//
// Every edit checks that its target text exists first, so a Capacitor template
// change fails the build instead of quietly shipping Capacitor's default branding.
import { copyFileSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const APP = join("android", "app");
const RES = join(APP, "src/main/res");
const BACKGROUND = "#121212";   // the app's theme_color and background_color
const pkg = JSON.parse(readFileSync("package.json", "utf8"));

function edit(file, replacements) {
  let text = readFileSync(file, "utf8");
  for (const [pattern, replacement] of replacements) {
    if (!pattern.test(text)) throw new Error(`${file}: expected text not found: ${pattern}`);
    text = text.replace(pattern, replacement);
  }
  writeFileSync(file, text);
}

// 1. Versions. Android refuses to install an older versionCode over a newer one,
//    so CI passes the workflow run number.
edit(join(APP, "build.gradle"), [
  [/^([ \t]*)versionCode \d+$/m, `$1versionCode ${Number(process.env.VERSION_CODE) || 1}`],
  [/^([ \t]*)versionName ".*"$/m, `$1versionName "${pkg.version}"`],
]);

// 2. Launcher icon, as an adaptive icon. Launchers draw a PNG-only icon on their own
//    backing, which is where the white circle came from. An adaptive icon with a dark
//    background avoids that, and launchers can mask it to their own shape. The full
//    icon is inset into the foreground, so its glyph stays inside the 66dp safe zone.
const densities = readdirSync(RES).filter((d) => /^mipmap-[a-z]+dpi$/.test(d));
if (!densities.length) throw new Error(`${RES}: no mipmap-*dpi folders found`);
for (const dir of densities) {
  for (const name of ["ic_launcher.png", "ic_launcher_round.png", "ic_launcher_foreground.png"]) {
    copyFileSync(join("icons", "icon-512.png"), join(RES, dir, name));
  }
}
const XML_HEADER = '<?xml version="1.0" encoding="utf-8"?>\n';
const ADAPTIVE =
  XML_HEADER +
  '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n' +
  '    <background android:drawable="@drawable/ic_launcher_background"/>\n' +
  '    <foreground android:drawable="@drawable/ic_launcher_foreground"/>\n' +
  "</adaptive-icon>\n";
mkdirSync(join(RES, "mipmap-anydpi-v26"), { recursive: true });
for (const name of ["ic_launcher.xml", "ic_launcher_round.xml"]) {
  writeFileSync(join(RES, "mipmap-anydpi-v26", name), ADAPTIVE);
}
mkdirSync(join(RES, "drawable"), { recursive: true });
writeFileSync(
  join(RES, "drawable/ic_launcher_background.xml"),
  XML_HEADER +
    '<shape xmlns:android="http://schemas.android.com/apk/res/android">\n' +
    `    <solid android:color="${BACKGROUND}"/>\n` +
    "</shape>\n"
);
writeFileSync(
  join(RES, "drawable/ic_launcher_foreground.xml"),
  XML_HEADER +
    '<inset xmlns:android="http://schemas.android.com/apk/res/android"\n' +
    '    android:drawable="@mipmap/ic_launcher_foreground"\n' +
    '    android:insetLeft="21dp" android:insetTop="21dp" android:insetRight="21dp" android:insetBottom="21dp"/>\n'
);
// Capacitor's v24 foreground is a logo vector, and it would override ours on API 24+.
rmSync(join(RES, "drawable-v24/ic_launcher_foreground.xml"), { force: true });

// 3. Splash. A plain dark screen instead of Capacitor's logo image. The Android 12+
//    splash also draws the icon inside a circle; its fill defaults to white, so set
//    it to the same dark colour as the icon's own background.
edit(join(RES, "values/styles.xml"), [
  [
    /^([ \t]*)<item name="android:background">@drawable\/splash<\/item>$/m,
    `$1<item name="android:background">${BACKGROUND}</item>\n` +
      `$1<item name="windowSplashScreenBackground">${BACKGROUND}</item>\n` +
      `$1<item name="windowSplashScreenIconBackgroundColor">${BACKGROUND}</item>`
  ]
]);
for (const dir of readdirSync(RES).filter((d) => d.startsWith("drawable"))) {
  rmSync(join(RES, dir, "splash.png"), { force: true });
}

console.log(`Prepared ${APP}: version ${pkg.version}, ${densities.length} icon densities (adaptive), dark splash`);

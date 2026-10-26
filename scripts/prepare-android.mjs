// Makes the generated android/ project ours: launcher icon, splash colour and
// version numbers. Runs right after `cap add android`.
//
// Every edit checks that its target text exists first, so a Capacitor template
// change fails the build instead of quietly shipping Capacitor's default branding.
import { copyFileSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

// 2. Launcher icon. Use our 512px icon for every density, and delete the
//    adaptive-icon XML, which would otherwise take priority over the PNGs.
const densities = readdirSync(RES).filter((d) => /^mipmap-[a-z]+dpi$/.test(d));
if (!densities.length) throw new Error(`${RES}: no mipmap-*dpi folders found`);
for (const dir of densities) {
  for (const name of ["ic_launcher.png", "ic_launcher_round.png"]) {
    copyFileSync(join("icons", "icon-512.png"), join(RES, dir, name));
  }
}
rmSync(join(RES, "mipmap-anydpi-v26"), { recursive: true, force: true });

// 3. Splash. A plain dark screen instead of Capacitor's logo image.
edit(join(RES, "values/styles.xml"), [
  [
    /^([ \t]*)<item name="android:background">@drawable\/splash<\/item>$/m,
    `$1<item name="android:background">${BACKGROUND}</item>\n` +
      `$1<item name="windowSplashScreenBackground">${BACKGROUND}</item>`
  ]
]);
for (const dir of readdirSync(RES).filter((d) => d.startsWith("drawable"))) {
  rmSync(join(RES, dir, "splash.png"), { force: true });
}

console.log(`Prepared ${APP}: version ${pkg.version}, ${densities.length} icon densities, dark splash`);

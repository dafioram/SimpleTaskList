# SimpleTaskList

A task list that runs entirely in your browser: labels, assignees, due dates,
dependencies ("requires" / "blocks"), search, and drag-to-reorder. No server,
no account, and no build step for the web app. It works offline and installs to
your phone's home screen. The same files also build into an Android app (see below).

**Your tasks are stored on the device you use it on**: in the browser's IndexedDB,
or in the app's own storage in the Android app. Nothing is uploaded anywhere.

## Use it

Host the folder on any static web host. For GitHub Pages:

1. Push this folder to a GitHub repository
2. Settings → Pages → *Deploy from a branch* → `main` / root
3. Open `https://<you>.github.io/<repo>/`

To install it:
- **iPhone/iPad:** open in Safari → Share → **Add to Home Screen**
- **Android/Chrome/Edge:** menu → **Install app** (or ⋯ → Install app inside the app)

Offline mode and installing need HTTPS (GitHub Pages provides it) or `localhost`.
To try it locally: `python3 -m http.server` in this folder, then open
http://localhost:8000. Opening `index.html` straight from disk also works, but
without offline mode.

## Android app

The same files also build into an Android app, using [Capacitor](https://capacitorjs.com).
GitHub Actions builds it, so Android Studio isn't needed. The app keeps its tasks in
its own storage, which the browser's site-data settings don't touch, and it works offline.

**Install a build:** in the repository, open **Actions → Android app**, pick the latest
run, and download the `simpletasklist-android` artifact. Copy the `.apk` to the phone and
open it. Android will ask you to allow installs from that source.

Every run on `static-app` and every pull request builds an APK. The version name comes
from `package.json`, and the version code is the run number, so each build installs over
the last one. Without the signing secrets below, the build is an unsigned debug APK, and
it can't update an installed copy.

**Signing (needed for updates):** Android only installs an update signed with the same
key as the installed app. Create a release key once, and keep the file and both passwords
somewhere safe:

```sh
keytool -genkeypair -v -keystore release.jks -alias tasks -keyalg RSA -keysize 2048 -validity 10000
base64 -w0 release.jks > release.jks.b64
```

Then add these repository secrets (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | the contents of `release.jks.b64` |
| `ANDROID_KEYSTORE_PASSWORD` | the keystore password |
| `ANDROID_KEY_ALIAS` | the alias you used (`tasks` above) |
| `ANDROID_KEY_PASSWORD` | the same as the keystore password. The command above makes a PKCS12 keystore, which uses one password for both |

If the key is lost, the next build can't update installed copies. Reinstalling would
mean uninstalling first, and that deletes the tasks on the phone.

**Moving tasks:** the app and the browser keep separate storage. Use **⋯ → Export backup**
in one, and **Import** in the other.

**Before the first install:** the `appId` in `capacitor.config.json`
(`io.github.dafioram.simpletasklist`) is the app's permanent identity. Changing it later
installs a second app next to the first.

**Build locally (optional):**

```sh
npm ci
npm run android:add    # copies the web files into www/ and generates android/
```

`android/` and `www/` are generated and git-ignored. Delete `android/` before running
`android:add` again. Open `android/` in Android Studio to run the app on a device.

## Things to know

- **One device, one list.** Your phone and your computer each keep their own
  tasks. Move them with **⋯ → Export backup** on one and **Import** on the other.
- **Back up now and then.** Clearing the browser's site data deletes your tasks.
  The ⋯ button shows an orange dot when your last backup is over 30 days old.
- **iPhone:** Safari deletes storage for websites you haven't opened in 7 days.
  Apps added to the Home Screen are exempt, so install it.
- **Keep my tasks safe** (in the ⋯ menu, when shown) asks the browser not to clear
  the app's storage when the device runs low on space.

## Moving from the server version

In the old app's folder, stop the app (`docker compose down` or stop the service)
so everything is written to disk, then copy `data/tasks.db` to your phone or
computer. In this app, choose **⋯ → Import backup or old tasks.db** and pick it.
Both the original SimpleTaskList database and TaskApp's database work: labels,
assignees, due dates, details, completion notes and dependencies all come over.

## How to use

| Action | How |
|---|---|
| Add a task | Type at the top, add labels (Enter or comma), tap **+** |
| Complete | Tap the checkbox (an **Undo** appears for a few seconds) |
| Edit | Tap the task text or ✎. Enter saves; back / swipe / ✕ closes |
| Move to top | ▲ |
| Reorder | Drag the ⋮⋮ handle (works while filtered; hidden tasks keep their place) |
| Filter | Funnel button. Active filters show as chips under the search box; tap a chip to remove it. Filters are in the address bar, so you can bookmark them |
| Search | Words match title, details or ID (any word). `#12` searches IDs only |
| Code in details | Wrap it in ``` |
| Delete | Edit → Delete (with Undo) |

Rules carried over from the server version: labels are title-cased ("work" and
"Work" are the same label), labels no task uses are hidden, labels used only by
completed tasks appear under *Show empty labels*, and a dependency that would
create a loop can't be picked.

## Files

| File | Purpose |
|---|---|
| `index.html`, `styles.css` | The page |
| `app.js` | Screens and interactions |
| `platform.js` | Tells the browser and the Android app apart. Nothing else checks |
| `store.js` | Storage (IndexedDB, or app storage in the Android app) and all task rules |
| `importer.js` | Reads backups and old `tasks.db` files |
| `sw.js` | Offline support. **Bump `VERSION` whenever you change any file** so installed copies update (they show a "Reload" prompt) |
| `vendor/` | SortableJS (drag and drop) and sql.js (reads old `tasks.db`; only downloaded when you import one) |
| `package.json`, `capacitor.config.json`, `scripts/` | Android build: Capacitor, copying the web files into `www/`, and launcher/splash/version setup |
| `.github/workflows/android.yml` | Builds the Android APK on GitHub |

## Backup format

A backup is plain JSON: `{ "app": "SimpleTaskList", "format": 1, "next_id": N, "tasks": [...] }`.
Each task has `id, content, context, labels, assignee, due_date, requires, position,
created_at, updated_at, completed_at, completion_note`.

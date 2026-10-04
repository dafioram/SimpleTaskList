# SimpleTaskList

A task list that runs entirely in your browser: labels, assignees, due dates,
dependencies ("requires" / "blocks"), search, and drag-to-reorder. No server,
no account, no build step. It works offline and installs to your phone's home
screen.

**Your tasks are stored on the device you use it on**, in the browser's IndexedDB.
Nothing is uploaded anywhere.

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
| `store.js` | Storage (IndexedDB) and all task rules |
| `importer.js` | Reads backups and old `tasks.db` files |
| `sw.js` | Offline support. **Bump `VERSION` whenever you change any file** so installed copies update (they show a "Reload" prompt) |
| `vendor/` | SortableJS (drag and drop) and sql.js (reads old `tasks.db`; only downloaded when you import one) |

## Backup format

A backup is plain JSON: `{ "app": "SimpleTaskList", "format": 1, "next_id": N, "tasks": [...] }`.
Each task has `id, content, context, labels, assignee, due_date, requires, position,
created_at, updated_at, completed_at, completion_note`.

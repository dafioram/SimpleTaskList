# Task List

A task list with multiple labels per task, assignees, due dates, dependencies
("requires" / "blocks"), search and drag-to-reorder. Flask + SQLite, built for
local use on a home LAN; everything it needs (Tagify, SortableJS) is bundled, so
it works without internet. **There is no login**, so don't expose it to the internet.

## Running it

All Linux methods run the same server: gunicorn with `gunicorn.conf.py` (1 worker × 4 threads, which suits a Raspberry Pi).

### Docker
1. `cp .env.example .env` and edit it
2. `docker compose up -d --build`
3. Open `http://YOUR-SERVER-IP:5000` (or the `PORT` you set)

The container starts as root only long enough to make `./data` writable, then runs as an unprivileged `app` user.

### systemd service (config.env)
`config.env` selects gunicorn (OPTION 3). The service runs:

    gunicorn -c $INSTALL_DIR/gunicorn.conf.py --bind 0.0.0.0:$PORT

Optional settings are listed at the bottom of `config.env`.

### Directly (Linux or Windows Git Bash)
1. `./python_install.sh`
2. `./run.sh`

On Linux this starts gunicorn. On Windows it runs `run.py` (Flask's built-in server), because gunicorn doesn't run on Windows. Requires Python 3.9 or newer. `run.sh` reads `.env` if present. Use `FLASK_DEBUG=1 ./run.sh` for auto-reload and the debugger; in that mode it only listens on 127.0.0.1.

## Settings (environment / .env)

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | 5000 | Port to listen on (in Docker, the host-side port) |
| `TZ` | America/New_York | Docker only: time zone for due/done dates |
| `API_BACKUP_KEY` | *(disabled)* | Enables `POST /api/backup`; values starting with `CHANGE_ME` count as unset |
| `WEB_WORKERS` / `WEB_THREADS` | 1 / 4 | gunicorn processes / threads per process |
| `ACCESS_LOG` | 0 | 1 = log every request |

## Backups

Backups are taken on demand through the API (set `API_BACKUP_KEY` first), for example from a cron job:

    curl -X POST -H "X-Backup-Key: YOUR_KEY" http://YOUR-SERVER-IP:5000/api/backup

Each call writes `data/backups/tasks_backup_YYYYMMDD_HHMMSS.db` and then deletes the previous backup, so only the latest is kept. `GET /api/health` reports whether the database is reachable.

### Restore
1. Stop the app (`docker compose down`, or stop the service)
2. Delete `data/tasks.db`, `data/tasks.db-wal` and `data/tasks.db-shm`
3. Copy the backup from `data/backups/` to `data/tasks.db`
4. Start the app

## Security notes

- No accounts: anyone who can reach the port can use the app.
- Changes (add, edit, complete, delete, reorder) only happen through POST requests, and the server rejects them when a browser sends them from another website. Scripts and `curl` (which send no Origin/Referer) still work.
- Pages can't be embedded in other sites, and scripts only load from the app itself.
- Debug mode is off unless `FLASK_DEBUG=1`.

## Labels

Labels are title-cased ("work" and "Work" are the same label). Labels that no task uses are hidden everywhere; labels used only by completed tasks appear when you click Show Empty Labels.

## Repairing old dependency links

An earlier version migrated old parent/subtask links backwards (the subtask ended up requiring the parent). `tools/flip_dependencies.py` lists every dependency with an id and flips the ones you choose; it saves a database copy to `data/backups/` first.

    python tools/flip_dependencies.py            # list
    python tools/flip_dependencies.py 3 7 12     # flip these
    docker exec -u app task-list python tools/flip_dependencies.py   # in Docker

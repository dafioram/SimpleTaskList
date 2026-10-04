"""One-time repair: flip dependency links that the old parent_id migration reversed.

The old migration turned "parent requires child" into "child requires parent".
Nothing marks which links came from that migration, so you pick them.

Usage (from the app folder; stop the app first if you can):
    python tools/flip_dependencies.py              list every dependency with its id
    python tools/flip_dependencies.py 3 7 12       flip the links with those ids
    python tools/flip_dependencies.py --all        flip every dependency

Docker:
    docker exec -u app task-list python tools/flip_dependencies.py
(-u app keeps file ownership correct.)

A copy of the database is saved to data/backups/ before anything changes.
"""
import datetime
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, '..', 'data', 'tasks.db')
BACKUP_DIR = os.path.join(HERE, '..', 'data', 'backups')


def short(text, n=40):
    text = (text or '').replace('\n', ' ')
    return text if len(text) <= n else text[:n - 1] + '…'


def load(conn):
    return conn.execute("""
        SELECT r.id, r.task_id, t.content, r.related_task_id, p.content
        FROM task_relationship r
        LEFT JOIN task t ON t.id = r.task_id
        LEFT JOIN task p ON p.id = r.related_task_id
        WHERE r.relationship_type = 'dependency'
        ORDER BY r.id""").fetchall()


def show(rows):
    if not rows:
        print("No dependencies found.")
        return
    print(f"{'id':>4}  link")
    for rid, tid, tcontent, pid, pcontent in rows:
        print(f"{rid:>4}  #{tid} {short(tcontent)!r}  requires  #{pid} {short(pcontent)!r}")


def backup(conn):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(BACKUP_DIR, f'before_flip_{stamp}.db')
    dst = sqlite3.connect(path)
    with dst:
        conn.backup(dst)
    dst.close()
    return os.path.normpath(path)


def main(args):
    if not os.path.exists(DB_PATH):
        sys.exit(f"Database not found at {os.path.normpath(DB_PATH)}")
    conn = sqlite3.connect(DB_PATH)
    rows = load(conn)

    if not args:
        show(rows)
        print("\nPass ids to flip them, or --all.")
        return

    by_id = {r[0]: r for r in rows}
    if args == ['--all']:
        ids = list(by_id)
    else:
        try:
            ids = [int(a) for a in args]
        except ValueError:
            sys.exit("Ids must be numbers (or use --all).")
        missing = [i for i in ids if i not in by_id]
        if missing:
            sys.exit(f"No dependency with id {', '.join(map(str, missing))}. Run without arguments to list them.")

    print(f"Backup saved to {backup(conn)}")
    existing = {(r[1], r[3]) for r in rows}
    flipped = 0
    with conn:
        for rid in ids:
            _, tid, _, pid, _ = by_id[rid]
            if (pid, tid) in existing:
                print(f"skip {rid}: the reverse link (#{pid} requires #{tid}) already exists")
                continue
            conn.execute("UPDATE task_relationship SET task_id = ?, related_task_id = ? WHERE id = ?",
                         (pid, tid, rid))
            existing.discard((tid, pid))
            existing.add((pid, tid))
            flipped += 1
    print(f"Flipped {flipped} link(s). Now:")
    show([r for r in load(conn) if r[0] in ids])
    conn.close()


if __name__ == '__main__':
    main(sys.argv[1:])

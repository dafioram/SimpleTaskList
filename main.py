import hmac
import json
import logging
import os
from datetime import datetime
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

from database import (DATA_DIR, DB_PATH, Label, Task, TaskRelationship, db,
                      init_db, perform_backup)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger('taskapp')

app = Flask(__name__)

# --- PROXY FIX ---
# Only matters if you put a reverse proxy in front; harmless otherwise.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# --- PATH CONFIGURATION ---
os.makedirs(DATA_DIR, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize the database and run migrations
init_db(app)

FILTER_KEYS = ('label', 'assignee', 'due_only', 'rel')


# --- SECURITY (no login; LAN-only app) ---

@app.before_request
def block_cross_site_writes():
    """Rejects state-changing requests that a browser sent from another site.

    Browsers always attach Origin (or at least Referer) to cross-site POSTs, so a
    malicious page can't submit forms to this app. Requests with neither header
    (curl, scripts, the backup API) are allowed through.
    """
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    source = request.headers.get('Origin') or request.headers.get('Referer')
    if not source:
        return None
    if source == 'null' or urlsplit(source).netloc.lower() != request.host.lower():
        log.warning("Blocked cross-site %s %s from %s", request.method, request.path, source)
        abort(403)
    return None


@app.after_request
def security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'same-origin')
    response.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
    )
    return response


# --- HELPER FUNCTIONS ---

def get_assignee_colors(unique_assignees):
    PALETTE = [
        '#d0bcff', '#448aff', '#69f0ae', '#ffab40', '#ff5252',
        '#ff80ab', '#64ffda', '#536dfe', '#f44336', '#e91e63',
        '#9c27b0', '#00bcd4', '#4caf50', '#ff9800', '#cddc39',
        '#8bc34a', '#03a9f4', '#009688', '#b388ff', '#8c9eff',
        '#80d8ff', '#a7ffeb', '#ccff90', '#ffe57f', '#ff9e80'
    ]
    colors = {}
    for a in unique_assignees:
        hash_val = sum(ord(c) * (i + 1) * 31 for i, c in enumerate(a))
        colors[a] = PALETTE[hash_val % len(PALETTE)]
    return colors


def get_label_colors(unique_labels):
    LABEL_PALETTE = ['purple', 'blue', 'green', 'orange', 'red', 'pink', 'teal', 'yellow', 'indigo']
    colors = {}
    for lbl in unique_labels:
        if not lbl: continue
        hash_val = sum(ord(c) * (i + 1) * 17 for i, c in enumerate(lbl))
        colors[lbl] = LABEL_PALETTE[hash_val % len(LABEL_PALETTE)]
    return colors


def build_sidebar(all_tasks):
    """Filter-bar lists, counts (active tasks only) and colors, shared by index and edit.

    Only labels attached to at least one task are listed. Labels used only by
    completed tasks get a count of 0 and sit behind "Show Empty Labels".
    """
    label_counts = {}
    assignee_counts = {}
    labels_in_use = set()
    unique_assignees = set()
    total_active = 0
    due_count = 0

    for t in all_tasks:
        for lbl in t.labels:
            labels_in_use.add(lbl.name)
        if t.assignee:
            unique_assignees.add(t.assignee)
        if t.completed_at is None:
            total_active += 1
            if t.due_date and t.due_date.strip():
                due_count += 1
            for lbl in t.labels:
                label_counts[lbl.name] = label_counts.get(lbl.name, 0) + 1
            key = t.assignee if t.assignee else "Unassigned"
            assignee_counts[key] = assignee_counts.get(key, 0) + 1

    labels_sorted = sorted(labels_in_use)
    assignees_sorted = sorted(unique_assignees)
    return {
        'all_labels': [(lbl, label_counts.get(lbl, 0)) for lbl in labels_sorted],
        'unique_labels_list': labels_sorted,
        'all_assignees': [(a, assignee_counts.get(a, 0)) for a in assignees_sorted],
        'unique_assignees': assignees_sorted,
        'unassigned_count': assignee_counts.get("Unassigned", 0),
        'total_active': total_active,
        'due_count': due_count,
        'assignee_colors': get_assignee_colors(unique_assignees),
        'label_colors': get_label_colors(labels_sorted),
    }


@app.template_global()
def filter_url(**changes):
    """URL for the task list with the current filters plus `changes`.

    filter_url(label='R&D') keeps the person/due/dependency filters and sets the
    label; passing None removes a filter. Values are URL-encoded.
    """
    params = {k: request.args.get(k) for k in FILTER_KEYS}
    params.update(changes)
    return url_for('index', **{k: v for k, v in params.items() if v})


def back_to_list():
    """Redirects to the task list, keeping the filter the user was looking at."""
    ref = urlsplit(request.referrer or '')
    if ref.netloc.lower() == request.host.lower() and ref.path == url_for('index'):
        return redirect(url_for('index') + (f'?{ref.query}' if ref.query else ''))
    return redirect(url_for('index'))


def parse_label_names(raw):
    """Turns the label field into a de-duplicated list of title-cased names.

    Accepts Tagify's JSON ([{"value": "..."}]) and, as a fallback (e.g. if
    Tagify didn't load), plain comma-separated text.
    """
    if not raw or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
        items = parsed if isinstance(parsed, list) else []
        values = [i.get('value', '') if isinstance(i, dict) else str(i) for i in items]
    except ValueError:
        values = raw.split(',')

    names, seen = [], set()
    for v in values:
        name = str(v).strip().title()[:50]
        if not name or name.lower() == 'all' or name.lower() in seen:
            continue
        seen.add(name.lower())
        names.append(name)
    return names


def update_task_labels(task, raw):
    task.labels.clear()
    for name in parse_label_names(raw):
        lbl = Label.query.filter_by(name=name).first()
        if not lbl:
            lbl = Label(name=name)
            db.session.add(lbl)
        task.labels.append(lbl)


def dependency_maps(task_map):
    """(prereq -> tasks it blocks, task -> its prereqs), skipping links to missing tasks."""
    blocks_map, requires_map = {}, {}
    for rel in TaskRelationship.query.filter_by(relationship_type='dependency').all():
        p_id, c_id = rel.related_task_id, rel.task_id
        if p_id in task_map and c_id in task_map:
            blocks_map.setdefault(p_id, []).append(task_map[c_id])
            requires_map.setdefault(c_id, []).append(task_map[p_id])
    return blocks_map, requires_map


def dependents_of(task_id):
    """IDs of every task that (directly or indirectly) requires task_id.

    Making any of these a prerequisite of task_id would create a loop.
    """
    blocked_by = {}
    for rel in TaskRelationship.query.filter_by(relationship_type='dependency').all():
        blocked_by.setdefault(rel.related_task_id, []).append(rel.task_id)
    found, stack = set(), [task_id]
    while stack:
        for dependent in blocked_by.get(stack.pop(), []):
            if dependent not in found:
                found.add(dependent)
                stack.append(dependent)
    return found


def top_position():
    min_pos = db.session.query(db.func.min(Task.position)).scalar()
    return (min_pos - 1) if min_pos is not None else 0


# --- ROUTES ---

@app.route('/')
def index():
    all_tasks_raw = Task.query.all()
    task_map = {t.id: t for t in all_tasks_raw}
    blocks_map, dependencies_map = dependency_maps(task_map)
    sidebar = build_sidebar(all_tasks_raw)

    filter_label = request.args.get('label') or None
    filter_assignee = request.args.get('assignee') or None
    filter_due = request.args.get('due_only') or None
    rel_filter = request.args.get('rel') or None

    tasks = all_tasks_raw
    if filter_label:
        tasks = [t for t in tasks if any(l.name == filter_label for l in t.labels)]
    if filter_assignee == 'Unassigned':
        tasks = [t for t in tasks if not t.assignee]
    elif filter_assignee:
        tasks = [t for t in tasks if t.assignee == filter_assignee]
    if filter_due == '1':
        tasks = [t for t in tasks if t.due_date and t.due_date.strip()]

    active_tasks = sorted((t for t in tasks if t.completed_at is None), key=lambda t: (t.position, t.id))
    finished_tasks = sorted((t for t in tasks if t.completed_at is not None), key=lambda t: t.completed_at, reverse=True)

    if rel_filter == 'requires':
        active_tasks = [t for t in active_tasks if t.id in dependencies_map]
    elif rel_filter == 'blocks':
        active_tasks = [t for t in active_tasks if t.id in blocks_map]

    return render_template('index.html',
                           tasks=active_tasks + finished_tasks,
                           active_filter=filter_label,
                           active_assignee=filter_assignee,
                           active_due=filter_due,
                           active_rel=rel_filter,
                           blocks_map=blocks_map,
                           dependencies_map=dependencies_map,
                           **sidebar)


@app.route('/add', methods=['POST'])
def add_task():
    content = (request.form.get('content') or '').strip()
    if content:
        new_task = Task(content=content, position=top_position(), color='default')
        db.session.add(new_task)
        update_task_labels(new_task, request.form.get('label'))
        db.session.commit()
    return back_to_list()


def render_edit(task, error=None, dependency_ids=None, status=200):
    all_tasks_raw = Task.query.all()
    if dependency_ids is None:
        dependency_ids = [r.related_task_id for r in
                          TaskRelationship.query.filter_by(task_id=task.id, relationship_type='dependency')]
    # The task itself and everything that already depends on it would make a loop.
    excluded = dependents_of(task.id) | {task.id}
    dependency_options = sorted((t for t in all_tasks_raw if t.id not in excluded), key=lambda t: t.id)
    return render_template('edit.html',
                           task=task,
                           dependency_options=dependency_options,
                           dependency_ids=dependency_ids,
                           error=error,
                           **build_sidebar(all_tasks_raw)), status


@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_task(id):
    task = db.session.get(Task, id)
    if not task:
        return redirect(url_for('index'))

    if request.method == 'GET':
        return render_edit(task)

    errors = []

    content = (request.form.get('content') or '').strip()
    if content:
        task.content = content
    else:
        errors.append("The task can't be empty.")

    update_task_labels(task, request.form.get('label'))

    raw_assignee = (request.form.get('assignee') or '').strip()
    if raw_assignee and raw_assignee.lower() not in ('anyone', 'unassigned'):
        task.assignee = raw_assignee.title()[:50]
    else:
        task.assignee = None

    task.due_date = request.form.get('due_date') or None
    task.context = request.form.get('context') or None
    if task.completed_at:
        task.completion_note = request.form.get('completion_note') or None

    # --- DEPENDENCIES (validated before anything is saved) ---
    dep_ids = []
    for raw in request.form.getlist('dependency_ids'):
        if raw and raw.isdigit() and int(raw) not in dep_ids:
            dep_ids.append(int(raw))
    loop_ids = dependents_of(task.id) | {task.id}
    for pid in dep_ids:
        if pid in loop_ids:
            errors.append(f"#{pid} already depends on this task, so it can't also be a prerequisite.")
        elif not db.session.get(Task, pid):
            errors.append(f"Task #{pid} no longer exists.")

    if errors:
        # Show the form again with what was typed; nothing is saved.
        response = render_edit(task, error=' '.join(errors), dependency_ids=dep_ids, status=400)
        db.session.rollback()
        return response

    TaskRelationship.query.filter_by(task_id=task.id, relationship_type='dependency').delete()
    for pid in dep_ids:
        db.session.add(TaskRelationship(task_id=task.id, related_task_id=pid, relationship_type='dependency'))

    task.touch()
    db.session.commit()
    return redirect(url_for('index'))


@app.route('/toggle/<int:id>', methods=['POST'])
def toggle_task(id):
    task = db.session.get(Task, id)
    if task:
        if task.completed_at:
            task.completed_at = None
            task.completion_note = None
            task.position = top_position()
        else:
            task.completed_at = datetime.now()
        task.touch()
        db.session.commit()
    return back_to_list()


@app.route('/promote/<int:id>', methods=['POST'])
def promote_task(id):
    task = db.session.get(Task, id)
    if task:
        task.position = top_position()
        db.session.commit()
    return back_to_list()


@app.route('/reorder', methods=['POST'])
def reorder_tasks():
    """Saves a new order for the tasks visible on screen.

    When a filter is active only some tasks are visible. Those tasks are
    shuffled among the slots they already occupy, so hidden tasks keep
    their place.
    """
    data = request.get_json(silent=True)
    try:
        if not isinstance(data, dict) or not isinstance(data.get('order'), list):
            raise TypeError
        requested = [int(x) for x in data['order']]
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'order must be a list of task ids'}), 400

    active = sorted(Task.query.filter(Task.completed_at.is_(None)).all(), key=lambda t: (t.position, t.id))
    by_id = {t.id: t for t in active}

    seen = set()
    visible_order = []
    for tid in requested:
        if tid in by_id and tid not in seen:
            seen.add(tid)
            visible_order.append(tid)

    slots = [i for i, t in enumerate(active) if t.id in seen]
    for slot, tid in zip(slots, visible_order):
        active[slot] = by_id[tid]
    for position, t in enumerate(active):
        t.position = position

    db.session.commit()
    return jsonify({'status': 'success'})


@app.route('/delete/<int:id>', methods=['POST'])
def delete_task(id):
    task = db.session.get(Task, id)
    if task:
        # Remove relationship records pointing to or from this task
        TaskRelationship.query.filter(
            (TaskRelationship.task_id == task.id) | (TaskRelationship.related_task_id == task.id)
        ).delete()
        db.session.delete(task)
        db.session.commit()
    return redirect(url_for('index'))


# --- API ENDPOINTS ---

@app.route('/api/health', methods=['GET'])
def api_health():
    health_status = {
        "status": "healthy",
        "database": "unknown",
        "timestamp": datetime.now().isoformat()
    }
    try:
        db.session.execute(text('SELECT 1'))
        health_status["database"] = "connected"
        return jsonify(health_status), 200
    except Exception:
        log.exception("Health check failed")
        health_status["status"] = "unhealthy"
        health_status["database"] = "error"
        return jsonify(health_status), 500


@app.route('/api/backup', methods=['POST'])
def api_backup():
    """Writes data/backups/tasks_backup_<timestamp>.db and removes the previous one."""
    expected_api_key = os.environ.get('API_BACKUP_KEY', '')
    if not expected_api_key or expected_api_key.startswith('CHANGE_ME'):
        return jsonify({"status": "error", "message": "Backup API key not configured on server."}), 403

    provided_key = request.headers.get('X-Backup-Key', '')
    if not hmac.compare_digest(provided_key.encode(), expected_api_key.encode()):
        return jsonify({"status": "error", "message": "Unauthorized: Invalid or missing Backup key."}), 401

    success, result = perform_backup()
    if success:
        return jsonify({"status": "success", "message": "Database backup completed.", "file": result}), 200
    return jsonify({"status": "error", "message": "Backup failed. See server log."}), 500

from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import shutil
from datetime import datetime
import json

from database import db, Task, Label, TaskRelationship, init_db, perform_backup

app = Flask(__name__)

# --- PROXY FIX ---
app.wsgi_app = ProxyFix(
    app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
)

# --- PATH CONFIGURATION ---
base_dir = os.path.abspath(os.path.dirname(__file__))
data_dir = os.path.join(base_dir, 'data')
db_path = os.path.join(data_dir, 'tasks.db')
os.makedirs(data_dir, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY') or 'change-me'

# Initialize the database and run migrations
init_db(app)

# --- HELPER FUNCTIONS ---

def would_cause_cycle(task_id, proposed_prereq_id):
    """
    Traces dependency links using BFS to verify if making 'proposed_prereq_id'
    a prerequisite of 'task_id' would introduce a circular dependency.
    """
    if task_id == proposed_prereq_id:
        return True
        
    visited = set()
    queue = [proposed_prereq_id]
    
    while queue:
        current = queue.pop(0)
        if current == task_id:
            return True
        if current not in visited:
            visited.add(current)
            # Find everything that 'current' depends on
            rels = TaskRelationship.query.filter_by(task_id=current, relationship_type='dependency').all()
            for r in rels:
                if r.related_task_id not in visited:
                    queue.append(r.related_task_id)
    return False

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

def update_task_labels(task, tagify_json_string):
    task.labels.clear()
    if not tagify_json_string:
        return
    try:
        parsed_data = json.loads(tagify_json_string)
        for item in parsed_data:
            name = item.get('value', '').strip().title()
            if name.lower() == 'all':
                continue
            if name:
                lbl = Label.query.filter_by(name=name).first()
                if not lbl:
                    lbl = Label(name=name)
                    db.session.add(lbl)
                task.labels.append(lbl)
    except json.JSONDecodeError:
        pass

# --- ROUTES ---

@app.route('/')
def index():
    all_tasks_raw = Task.query.all()
    task_map = {t.id: t for t in all_tasks_raw}
    
    # Build children_map using TaskRelationship instead of legacy parent_id
    # map key = prerequisite task ID, value = list of tasks blocked by it
    children_map = {}
    dependencies_map = {}  # 1. Initialize the missing map
    all_dependencies = TaskRelationship.query.filter_by(relationship_type='dependency').all()
    
    for rel in all_dependencies:
        p_id = rel.related_task_id  # The prerequisite task
        c_id = rel.task_id          # The blocked task
        
        if p_id in task_map and c_id in task_map:
            # Build children_map (Prereq -> Blocked)
            if p_id not in children_map:
                children_map[p_id] = []
            children_map[p_id].append(task_map[c_id])
            
            # 2. Build dependencies_map (Task -> Prereqs)
            if c_id not in dependencies_map:
                dependencies_map[c_id] = []
            dependencies_map[c_id].append(task_map[p_id])

    filter_label = request.args.get('label')
    filter_assignee = request.args.get('assignee')
    filter_due = request.args.get('due_only')
    rel_filter = request.args.get('rel')

    label_counts = {}
    assignee_counts = {}
    unique_assignees = set()
    total_active = 0
    due_count = 0
    
    for t in all_tasks_raw:
        if t.completed_at is None:
            total_active += 1
            if t.due_date and t.due_date.strip() != "":
                due_count += 1

            for lbl in t.labels:
                label_counts[lbl.name] = label_counts.get(lbl.name, 0) + 1
            
            assgn_key = t.assignee if t.assignee else "Unassigned"
            assignee_counts[assgn_key] = assignee_counts.get(assgn_key, 0) + 1
            
        if t.assignee:
            unique_assignees.add(t.assignee)

    query = Task.query
    if filter_label:
        query = query.filter(Task.labels.any(Label.name == filter_label))
    if filter_assignee:
        if filter_assignee == 'Unassigned':
            query = query.filter((Task.assignee == None) | (Task.assignee == ''))
        else:
            query = query.filter(Task.assignee == filter_assignee)
    if filter_due == '1': 
        query = query.filter(Task.due_date.isnot(None)).filter(Task.due_date != "")
        
    tasks = query.all()
    
    all_labels_query = Label.query.order_by(Label.name).all()
    unique_labels_list = [l.name for l in all_labels_query]
    
    all_labels = [(lbl, label_counts.get(lbl, 0)) for lbl in unique_labels_list]
    all_assignees = [(a, assignee_counts.get(a, 0)) for a in sorted(list(unique_assignees))]
    unassigned_count = assignee_counts.get("Unassigned", 0)

    assignee_colors = get_assignee_colors(unique_assignees)
    label_colors = get_label_colors(unique_labels_list)

    active_tasks = sorted([t for t in tasks if t.completed_at is None], key=lambda t: t.position)
    finished_tasks = sorted([t for t in tasks if t.completed_at is not None], key=lambda t: t.completed_at, reverse=True)

    if rel_filter == 'requires':
        # Only keep tasks that are keys in dependencies_map
        active_tasks = [t for t in active_tasks if t.id in dependencies_map]
    elif rel_filter == 'blocks':
        # Only keep tasks that are keys in children_map (the blockers)
        active_tasks = [t for t in active_tasks if t.id in children_map]

    return render_template('index.html', 
                           tasks=active_tasks + finished_tasks, 
                           all_labels=all_labels, 
                           all_assignees=all_assignees,
                           assignee_colors=assignee_colors,
                           label_colors=label_colors,
                           unassigned_count=unassigned_count,
                           active_filter=filter_label,
                           active_assignee=filter_assignee,
                           active_due=filter_due,
                           active_rel=rel_filter,
                           children_map=children_map,
                           blocks_map=children_map, # <--- Add this line
                           dependencies_map=dependencies_map,
                           unique_labels_list=unique_labels_list,
                           due_count=due_count,
                           total_active=total_active)

@app.route('/add', methods=['POST'])
def add_task():
    content = request.form.get('content')
    raw_labels = request.form.get('label')

    if content:
        min_pos = db.session.query(db.func.min(Task.position)).scalar()
        new_pos = (min_pos - 1) if min_pos is not None else 0
        
        new_task = Task(content=content, position=new_pos, color='default')
        db.session.add(new_task)
        update_task_labels(new_task, raw_labels)
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_task(id):
    task = db.session.get(Task, id)
    if not task: return redirect(url_for('index'))

    if request.method == 'POST':
        task.content = request.form.get('content')
        
        raw_labels = request.form.get('label')
        update_task_labels(task, raw_labels)
        
        raw_assignee = request.form.get('assignee')
        if raw_assignee and (raw_assignee.strip().lower() != 'anyone' and raw_assignee.strip().lower() != 'unassigned'):
            task.assignee = raw_assignee.strip().title()
        else:
            task.assignee = None

        dd = request.form.get('due_date')
        task.due_date = dd if dd else None
        
        ctxt = request.form.get('context')
        task.context = ctxt if ctxt else None

        if task.completed_at:
            note = request.form.get('completion_note')
            task.completion_note = note if note else None

        # --- SYNC DEPENDENCIES ---
        TaskRelationship.query.filter_by(task_id=task.id, relationship_type='dependency').delete()
        
        # Matches the 'name' attribute in our new edit.html <select>
        dependency_ids_raw = request.form.getlist('dependency_ids')
        for pid_str in dependency_ids_raw:
            if pid_str and pid_str.isdigit():
                pid_int = int(pid_str)
                # Ensure no self-referencing and trace for cycles before saving
                if pid_int != task.id and not would_cause_cycle(task.id, pid_int):
                    new_rel = TaskRelationship(
                        task_id=task.id,
                        related_task_id=pid_int,
                        relationship_type='dependency'
                    )
                    db.session.add(new_rel)

        db.session.commit()
        return redirect(url_for('index'))

    # GET requests processing
    all_tasks_raw = Task.query.all()
    
    label_counts = {}
    assignee_counts = {}
    unique_assignees = set()
    total_active = 0
    
    for t in all_tasks_raw:
        if t.completed_at is None:
            total_active += 1
            for lbl in t.labels:
                label_counts[lbl.name] = label_counts.get(lbl.name, 0) + 1
            
            assgn_key = t.assignee if t.assignee else "Unassigned"
            assignee_counts[assgn_key] = assignee_counts.get(assgn_key, 0) + 1
            
        if t.assignee:
            unique_assignees.add(t.assignee)

    all_labels_query = Label.query.order_by(Label.name).all()
    unique_labels_list = [l.name for l in all_labels_query]
    
    all_labels = [(lbl, label_counts.get(lbl, 0)) for lbl in unique_labels_list]
    all_assignees = [(a, assignee_counts.get(a, 0)) for a in sorted(list(unique_assignees))]
    unassigned_count = assignee_counts.get("Unassigned", 0)
    assignee_colors = get_assignee_colors(unique_assignees)

    # Fetch currently assigned dependencies to select them in the HTML dropdown
    current_deps = TaskRelationship.query.filter_by(task_id=id, relationship_type='dependency').all()
    dependency_ids = [r.related_task_id for r in current_deps]

    return render_template('edit.html', 
                           task=task,
                           all_tasks=all_tasks_raw,
                           dependency_ids=dependency_ids,  # Passed directly to jinja
                           all_labels=all_labels,
                           all_assignees=all_assignees,
                           unassigned_count=unassigned_count,
                           unique_assignees=sorted(list(unique_assignees)),
                           unique_labels_list=unique_labels_list,
                           assignee_colors=assignee_colors)

@app.route('/toggle/<int:id>', methods=['POST'])
def toggle_task(id):
    task = db.session.get(Task, id)
    if task:
        if task.completed_at:
            task.completed_at = None
            task.completion_note = None
            min_pos = db.session.query(db.func.min(Task.position)).scalar()
            task.position = (min_pos - 1) if min_pos is not None else 0
        else:
            task.completed_at = datetime.now()
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/reorder', methods=['POST'])
def reorder_tasks():
    data = request.get_json()
    new_order = data.get('order', []) 
    for index, task_id in enumerate(new_order):
        task = db.session.get(Task, task_id)
        if task: task.position = index
    db.session.commit()
    return {'status': 'success'}

@app.route('/delete/<int:id>', methods=['POST'])
def delete_task(id):
    task = db.session.get(Task, id)
    if task:
        # Clean up any relationship records pointing to or from this task to keep tables clean
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
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["database"] = "error"
        health_status["error_details"] = str(e)
        return jsonify(health_status), 500

@app.route('/api/backup', methods=['POST'])
def api_backup():
    expected_api_key = os.environ.get('API_BACKUP_KEY')
    if not expected_api_key:
        return jsonify({"status": "error", "message": "Backup API key not configured on server."}), 403
        
    provided_key = request.headers.get('X-Backup-Key')
    if not provided_key or provided_key != expected_api_key:
        return jsonify({"status": "error", "message": "Unauthorized: Invalid or missing Backup key."}), 401

    success, result = perform_backup(db_path, data_dir)
    if success:
        return jsonify({"status": "success", "message": "Database backup completed.", "file": result}), 200
    else:
        return jsonify({"status": "error", "message": "Backup failed.", "error_details": result}), 500

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')
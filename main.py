from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import shutil
import datetime

# Import database configuration, models, and utilities
from database import db, Task, init_db, perform_backup

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

# Initialize the database and run migrations
init_db(app)

# --- HELPER FUNCTIONS ---

def get_assignee_colors(unique_assignees):
    """Generates consistent colors for assignees using a hash."""
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
    """Generates consistent CSS classes for labels using a salted hash."""
    LABEL_PALETTE = ['purple', 'blue', 'green', 'orange', 'red', 'pink', 'teal', 'yellow', 'indigo']
    colors = {}
    for lbl in unique_labels:
        if not lbl: continue
        # Multiplying by 17 ensures "Maggie" the label is a different color than "Maggie" the assignee
        hash_val = sum(ord(c) * (i + 1) * 17 for i, c in enumerate(lbl))
        colors[lbl] = LABEL_PALETTE[hash_val % len(LABEL_PALETTE)]
    return colors

# --- ROUTES ---

@app.route('/')
def index():
    all_tasks_raw = Task.query.all()
    
    # Build a map of parent_id -> list of child tasks for the UI
    children_map = {}
    for t in all_tasks_raw:
        if t.parent_id:
            if t.parent_id not in children_map:
                children_map[t.parent_id] = []
            children_map[t.parent_id].append(t)

    filter_label = request.args.get('label')
    filter_assignee = request.args.get('assignee')

    label_counts = {}
    assignee_counts = {}
    unique_assignees = set()
    total_active = 0
    
    for t in all_tasks_raw:
        if t.completed_at is None:
            total_active += 1
            if t.label:
                label_counts[t.label] = label_counts.get(t.label, 0) + 1
            
            assgn_key = t.assignee if t.assignee else "Unassigned"
            assignee_counts[assgn_key] = assignee_counts.get(assgn_key, 0) + 1
            
        if t.assignee:
            unique_assignees.add(t.assignee)

    query = Task.query
    if filter_label:
        query = query.filter(Task.label == filter_label)
        
    if filter_assignee:
        if filter_assignee == 'Unassigned':
            query = query.filter((Task.assignee == None) | (Task.assignee == ''))
        else:
            query = query.filter(Task.assignee == filter_assignee)
        
    tasks = query.all()
    
    unique_labels_query = db.session.query(Task.label).filter(Task.label.isnot(None)).filter(Task.label != "").distinct().all()
    unique_labels_list = [l[0] for l in sorted(unique_labels_query)]
    
    all_labels = [(lbl, label_counts.get(lbl, 0)) for lbl in unique_labels_list]
    all_assignees = [(a, assignee_counts.get(a, 0)) for a in sorted(list(unique_assignees))]
    unassigned_count = assignee_counts.get("Unassigned", 0)

    # Use the shared helper functions
    assignee_colors = get_assignee_colors(unique_assignees)
    label_colors = get_label_colors(unique_labels_list)

    active_tasks = sorted([t for t in tasks if t.completed_at is None], key=lambda t: t.position)
    finished_tasks = sorted([t for t in tasks if t.completed_at is not None], key=lambda t: t.completed_at, reverse=True)

    return render_template('index.html', 
                           tasks=active_tasks + finished_tasks, 
                           all_labels=all_labels, 
                           all_assignees=all_assignees,
                           assignee_colors=assignee_colors,
                           label_colors=label_colors,
                           unassigned_count=unassigned_count,
                           active_filter=filter_label,
                           active_assignee=filter_assignee,
                           children_map=children_map,
                           total_active=total_active)

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/add', methods=['POST'])
def add_task():
    content = request.form.get('content')
    raw_label = request.form.get('label')
    label = raw_label.strip().title() if raw_label else None 

    if content:
        min_pos = db.session.query(db.func.min(Task.position)).scalar()
        new_pos = (min_pos - 1) if min_pos is not None else 0
        
        # Color column is permanently set to 'default' in DB, we ignore it going forward
        new_task = Task(content=content, position=new_pos, color='default', label=label)
        db.session.add(new_task)
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_task(id):
    task = db.session.get(Task, id)
    if not task: return redirect(url_for('index'))

    if request.method == 'POST':
        task.content = request.form.get('content')
        
        raw_label = request.form.get('label')
        task.label = raw_label.strip().title() if raw_label else None
        
        raw_assignee = request.form.get('assignee')
        task.assignee = raw_assignee.strip().title() if raw_assignee else None

        dd = request.form.get('due_date')
        task.due_date = dd if dd else None
        
        # --- PARENT ID / INFINITE LOOP PREVENTION ---
        parent_id_raw = request.form.get('parent_id')
        if parent_id_raw and parent_id_raw.isdigit():
            pid_int = int(parent_id_raw)
            parent_task = db.session.get(Task, pid_int)
            
            if parent_task and pid_int != task.id:
                # Walk up the tree to ensure we don't create a circular dependency
                circular = False
                curr = parent_task
                while curr:
                    if curr.id == task.id:
                        circular = True
                        break
                    curr = db.session.get(Task, curr.parent_id) if curr.parent_id else None
                
                if not circular:
                    task.parent_id = pid_int
                else:
                    task.parent_id = None
            else:
                task.parent_id = None
        else:
            task.parent_id = None

        ctxt = request.form.get('context')
        task.context = ctxt if ctxt else None

        if task.completed_at:
            note = request.form.get('completion_note')
            task.completion_note = note if note else None

        db.session.commit()
        return redirect(url_for('index'))

    all_tasks_raw = Task.query.all()
    label_counts = {}
    assignee_counts = {}
    unique_assignees = set()
    
    for t in all_tasks_raw:
        if t.completed_at is None:
            if t.label:
                label_counts[t.label] = label_counts.get(t.label, 0) + 1
            assgn_key = t.assignee if t.assignee else "Unassigned"
            assignee_counts[assgn_key] = assignee_counts.get(assgn_key, 0) + 1
        if t.assignee:
            unique_assignees.add(t.assignee)

    unique_labels_query = db.session.query(Task.label).filter(Task.label.isnot(None)).filter(Task.label != "").distinct().all()
    unique_labels_list = [l[0] for l in sorted(unique_labels_query)]
    
    all_labels = [(lbl, label_counts.get(lbl, 0)) for lbl in unique_labels_list]
    all_assignees = [(a, assignee_counts.get(a, 0)) for a in sorted(list(unique_assignees))]
    unassigned_count = assignee_counts.get("Unassigned", 0)

    # Use the shared helper functions
    assignee_colors = get_assignee_colors(unique_assignees)

    return render_template('edit.html', 
                           task=task,
                           all_tasks=all_tasks_raw,
                           all_labels=all_labels,
                           all_assignees=all_assignees,
                           unassigned_count=unassigned_count,
                           unique_assignees=sorted(list(unique_assignees)),
                           assignee_colors=assignee_colors)

@app.route('/toggle/<int:id>')
def toggle_task(id):
    task = db.session.get(Task, id)
    if task:
        if task.completed_at:
            task.completed_at = None
            task.completion_note = None
            min_pos = db.session.query(db.func.min(Task.position)).scalar()
            task.position = (min_pos - 1) if min_pos is not None else 0
        else:
            task.completed_at = datetime.datetime.now()
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

@app.route('/delete/<int:id>')
def delete_task(id):
    task = db.session.get(Task, id)
    if task:
        # Orphan management: reset children of deleted task
        children = Task.query.filter_by(parent_id=task.id).all()
        for child in children: child.parent_id = None
        
        db.session.delete(task)
        db.session.commit()
    return redirect(url_for('index'))

# --- API ENDPOINTS ---

@app.route('/api/health', methods=['GET'])
def api_health():
    health_status = {
        "status": "healthy",
        "database": "unknown",
        "timestamp": datetime.datetime.now().isoformat()
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

if __name__ == '__main__':
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        if os.path.exists(db_path):
            perform_backup(db_path, data_dir)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
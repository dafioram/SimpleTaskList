from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import shutil
import datetime
import sqlite3

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

db = SQLAlchemy(app)

# --- MODEL ---
class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    position = db.Column(db.Integer, default=0)
    color = db.Column(db.String(20), default='default')
    
    # Metadata
    label = db.Column(db.String(50), nullable=True) 
    assignee = db.Column(db.String(50), nullable=True)
    due_date = db.Column(db.String(20), nullable=True)
    completion_note = db.Column(db.Text, nullable=True)
    
    # Dependency
    requires_id = db.Column(db.Integer, nullable=True)

    # Context / Details
    context = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    completed_at = db.Column(db.DateTime, nullable=True) 

    def get_time_display(self):
        if not self.due_date: return None
        try:
            due = datetime.datetime.strptime(self.due_date, '%Y-%m-%d').date()
            today = datetime.date.today()
            delta = (due - today).days
            
            if delta == 0: return "Due today"
            if delta == 1: return "1 day left"
            if delta > 1:  return f"{delta} days left"
            if delta == -1: return "1 day overdue"
            return f"{abs(delta)} days overdue"
        except: return None

with app.app_context():
    db.session.execute(text("PRAGMA journal_mode=WAL"))
    db.create_all()
    
    # --- AUTO-MIGRATION ---
    with db.engine.connect() as conn:
        try: conn.execute(text("ALTER TABLE task ADD COLUMN color VARCHAR(20) DEFAULT 'default'"))
        except: pass
        try: conn.execute(text("ALTER TABLE task ADD COLUMN label VARCHAR(50)"))
        except: pass
        try: conn.execute(text("ALTER TABLE task ADD COLUMN due_date VARCHAR(20)"))
        except: pass
        try: conn.execute(text("ALTER TABLE task ADD COLUMN completion_note TEXT"))
        except: pass
        try: conn.execute(text("ALTER TABLE task ADD COLUMN requires_id INTEGER"))
        except: pass
        try: conn.execute(text("ALTER TABLE task ADD COLUMN context TEXT"))
        except: pass
        try: conn.execute(text("ALTER TABLE task ADD COLUMN assignee VARCHAR(50)"))
        except: pass

# --- ROUTES ---

@app.route('/')
def index():
    all_tasks_raw = Task.query.all()
    status_map = {t.id: (t.completed_at is not None) for t in all_tasks_raw}

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
    
    all_labels = [(l[0], label_counts.get(l[0], 0)) for l in sorted(unique_labels_query)]
    all_assignees = [(a, assignee_counts.get(a, 0)) for a in sorted(list(unique_assignees))]
    unassigned_count = assignee_counts.get("Unassigned", 0)

    PALETTE = ['#d0bcff', '#448aff', '#69f0ae', '#ffab40', '#ff5252', '#ff80ab', '#64ffda', '#536dfe', '#f44336', '#e91e63', '#9c27b0', '#00bcd4', '#4caf50', '#ff9800']
    assignee_colors = {}
    for a in unique_assignees:
        hash_val = sum(ord(c) for c in a)
        assignee_colors[a] = PALETTE[hash_val % len(PALETTE)]

    active_tasks = sorted([t for t in tasks if t.completed_at is None], key=lambda t: t.position)
    finished_tasks = sorted([t for t in tasks if t.completed_at is not None], key=lambda t: t.completed_at, reverse=True)

    return render_template('index.html', 
                           tasks=active_tasks + finished_tasks, 
                           all_labels=all_labels, 
                           all_assignees=all_assignees,
                           assignee_colors=assignee_colors,
                           unassigned_count=unassigned_count,
                           active_filter=filter_label,
                           active_assignee=filter_assignee,
                           status_map=status_map,
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
        task.color = request.form.get('color')
        
        raw_label = request.form.get('label')
        task.label = raw_label.strip().title() if raw_label else None
        
        raw_assignee = request.form.get('assignee')
        task.assignee = raw_assignee.strip().title() if raw_assignee else None

        dd = request.form.get('due_date')
        task.due_date = dd if dd else None
        
        req_id = request.form.get('requires_id')
        if req_id and req_id.isdigit():
            req_id_int = int(req_id)
            if req_id_int != task.id and db.session.get(Task, req_id_int):
                task.requires_id = req_id_int
            else:
                task.requires_id = None
        else:
            task.requires_id = None

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
    all_labels = [(l[0], label_counts.get(l[0], 0)) for l in sorted(unique_labels_query)]
    all_assignees = [(a, assignee_counts.get(a, 0)) for a in sorted(list(unique_assignees))]
    unassigned_count = assignee_counts.get("Unassigned", 0)

    PALETTE = ['#d0bcff', '#448aff', '#69f0ae', '#ffab40', '#ff5252', '#ff80ab', '#64ffda', '#536dfe', '#f44336', '#e91e63', '#9c27b0', '#00bcd4', '#4caf50', '#ff9800']
    assignee_colors = {}
    for a in unique_assignees:
        hash_val = sum(ord(c) for c in a)
        assignee_colors[a] = PALETTE[hash_val % len(PALETTE)]

    return render_template('edit.html', 
                           task=task, 
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
        dependents = Task.query.filter_by(requires_id=task.id).all()
        for dep in dependents: dep.requires_id = None
        db.session.delete(task)
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/sweep')
def sweep_completed():
    tasks_to_delete = db.session.query(Task).filter(Task.completed_at.isnot(None)).all()
    ids_to_delete = [t.id for t in tasks_to_delete]
    if ids_to_delete:
        dependents = Task.query.filter(Task.requires_id.in_(ids_to_delete)).all()
        for dep in dependents: dep.requires_id = None
        for t in tasks_to_delete: db.session.delete(t)
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
    expected_api_key = os.environ.get('BACKUP_API_KEY')
    
    # Fail completely if no key is configured on the server
    if not expected_api_key:
        return jsonify({"status": "error", "message": "Backup API key not configured on server."}), 403
        
    # Check the incoming request for the key
    provided_key = request.headers.get('X-API-Key')
    if not provided_key or provided_key != expected_api_key:
        return jsonify({"status": "error", "message": "Unauthorized: Invalid or missing API key."}), 401

    # Proceed if the key matches perfectly
    success, result = perform_backup(db_path, data_dir)
    if success:
        return jsonify({"status": "success", "message": "Database backup completed.", "file": result}), 200
    else:
        return jsonify({"status": "error", "message": "Backup failed.", "error_details": result}), 500


# --- HELPER FUNCTIONS ---

def perform_backup(src_path, backup_root):
    try:
        backup_dir = os.path.join(backup_root, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dst_path = os.path.join(backup_dir, f"tasks_backup_{timestamp}.db")
        
        src = sqlite3.connect(src_path)
        dst = sqlite3.connect(dst_path)
        with dst: 
            src.backup(dst)
        dst.close()
        src.close()
        
        return True, dst_path
    except Exception as e:
        return False, str(e)

if __name__ == '__main__':
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        if os.path.exists(db_path):
            perform_backup(db_path, data_dir)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
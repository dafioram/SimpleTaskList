from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os
import shutil
import datetime
import sqlite3

app = Flask(__name__)

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
    due_date = db.Column(db.String(20), nullable=True)
    completion_note = db.Column(db.Text, nullable=True)
    
    # NEW: Dependency (Self-referential ID)
    requires_id = db.Column(db.Integer, nullable=True)
    
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
        # Migrate Dependency Column
        try: conn.execute(text("ALTER TABLE task ADD COLUMN requires_id INTEGER"))
        except: pass

# --- ROUTES ---

@app.route('/')
def index():
    # 1. Get ALL tasks first to build the Status Map (Global lookup)
    # We need this separately because the 'tasks' query below might be filtered by label,
    # but a dependency might exist outside that label.
    all_tasks_raw = Task.query.all()
    status_map = {t.id: (t.completed_at is not None) for t in all_tasks_raw}

    # 2. Filter logic for display
    filter_label = request.args.get('label')
    query = Task.query
    if filter_label:
        query = query.filter(Task.label == filter_label)
        
    tasks = query.all()
    
    unique_labels_query = db.session.query(Task.label)\
        .filter(Task.label.isnot(None))\
        .filter(Task.label != "")\
        .distinct().all()
    
    all_labels = sorted([l[0] for l in unique_labels_query])

    active_tasks = sorted(
        [t for t in tasks if t.completed_at is None], 
        key=lambda t: t.position
    )

    finished_tasks = sorted(
        [t for t in tasks if t.completed_at is not None],
        key=lambda t: t.completed_at,
        reverse=True
    )

    return render_template('index.html', 
                           tasks=active_tasks + finished_tasks, 
                           all_labels=all_labels, 
                           active_filter=filter_label,
                           status_map=status_map) # Pass map to HTML

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/add', methods=['POST'])
def add_task():
    content = request.form.get('content')
    color = request.form.get('color', 'default')
    due_date = request.form.get('due_date')
    
    raw_label = request.form.get('label')
    label = raw_label.strip().title() if raw_label else None 

    if content:
        min_pos = db.session.query(db.func.min(Task.position)).scalar()
        new_pos = (min_pos - 1) if min_pos is not None else 0
        
        new_task = Task(
            content=content, position=new_pos, color=color,
            label=label, 
            due_date=due_date if due_date else None
        )
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
        
        dd = request.form.get('due_date')
        task.due_date = dd if dd else None
        
        # --- NEW: Save Dependency ID ---
        req_id = request.form.get('requires_id')
        if req_id and req_id.isdigit():
            req_id_int = int(req_id)
            # Validation: 1. Not self. 2. Task exists.
            if req_id_int != task.id and db.session.get(Task, req_id_int):
                task.requires_id = req_id_int
            else:
                task.requires_id = None # Invalid ID entered
        else:
            task.requires_id = None # Cleared or empty

        if task.completed_at:
            note = request.form.get('completion_note')
            task.completion_note = note if note else None

        db.session.commit()
        return redirect(url_for('index'))

    return render_template('edit.html', task=task)

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

@app.route('/move/<int:id>/<direction>')
def move_task(id, direction):
    current = db.session.get(Task, id)
    if not current or current.completed_at: return redirect(url_for('index'))
    query = Task.query.filter(Task.completed_at.is_(None))
    
    if direction == 'up':
        neighbor = query.filter(Task.position < current.position).order_by(Task.position.desc()).first()
    else: 
        neighbor = query.filter(Task.position > current.position).order_by(Task.position.asc()).first()

    if neighbor:
        current.position, neighbor.position = neighbor.position, current.position
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/delete/<int:id>')
def delete_task(id):
    task = db.session.get(Task, id)
    if task:
        # --- CASCADE UPDATE: Unlink dependents ---
        dependents = Task.query.filter_by(requires_id=task.id).all()
        for dep in dependents:
            dep.requires_id = None
            
        db.session.delete(task)
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/sweep')
def sweep_completed():
    # 1. Get IDs of tasks about to be deleted
    tasks_to_delete = db.session.query(Task).filter(Task.completed_at.isnot(None)).all()
    ids_to_delete = [t.id for t in tasks_to_delete]

    if ids_to_delete:
        # 2. Unlink any active tasks that depend on these
        dependents = Task.query.filter(Task.requires_id.in_(ids_to_delete)).all()
        for dep in dependents:
            dep.requires_id = None
        
        # 3. Delete
        for t in tasks_to_delete:
            db.session.delete(t)
            
        db.session.commit()
    return redirect(url_for('index'))

# --- HELPER FUNCTIONS ---
def perform_backup(src_path, backup_root):
    """Creates a timestamped backup using SQLite's native backup API."""
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
        print(f"Database successfully backed up to: {dst_path}")
    except Exception as e:
        print(f"Backup failed: {e}")

if __name__ == '__main__':
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        if os.path.exists(db_path):
            perform_backup(db_path, data_dir)

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
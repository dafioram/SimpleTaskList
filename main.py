from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os
import shutil
import datetime

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
    # New Field: Color (default, red, orange, blue)
    color = db.Column(db.String(20), default='default')
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    completed_at = db.Column(db.DateTime, nullable=True) 

with app.app_context():
    db.session.execute(text("PRAGMA journal_mode=WAL"))
    db.create_all()
    
    # --- AUTO-MIGRATION FOR EXISTING DB ---
    # This tries to add the 'color' column if it's missing from your old DB
    try:
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE task ADD COLUMN color VARCHAR(20) DEFAULT 'default'"))
            print("✅ Migration: Added 'color' column to database.")
    except Exception:
        # Fails silently if column already exists (which is good)
        pass

# --- ROUTES ---

@app.route('/')
def index():
    tasks = Task.query.all()

    # Active: Sorted by Position (Manual Order)
    active_tasks = sorted(
        [t for t in tasks if t.completed_at is None], 
        key=lambda t: t.position
    )

    # Finished: Sorted by Completion Date (Newest first)
    finished_tasks = sorted(
        [t for t in tasks if t.completed_at is not None],
        key=lambda t: t.completed_at,
        reverse=True
    )

    return render_template('index.html', tasks=active_tasks + finished_tasks)

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/add', methods=['POST'])
def add_task():
    content = request.form.get('content')
    color = request.form.get('color', 'default') # Get color from form
    
    if content:
        max_pos = db.session.query(db.func.max(Task.position)).scalar()
        new_pos = (max_pos + 1) if max_pos is not None else 0
        
        new_task = Task(content=content, position=new_pos, color=color)
        db.session.add(new_task)
        db.session.commit()
    return redirect(url_for('index'))

# --- NEW EDIT ROUTE ---
@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_task(id):
    task = db.session.get(Task, id)
    if not task:
        return redirect(url_for('index'))

    if request.method == 'POST':
        task.content = request.form.get('content')
        task.color = request.form.get('color')
        db.session.commit()
        return redirect(url_for('index'))

    return render_template('edit.html', task=task)

@app.route('/toggle/<int:id>')
def toggle_task(id):
    task = db.session.get(Task, id)
    if task:
        if task.completed_at:
            task.completed_at = None
            max_pos = db.session.query(db.func.max(Task.position)).scalar() or 0
            task.position = max_pos + 1
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
        neighbor = query.filter(Task.position < current.position)\
                        .order_by(Task.position.desc()).first()
    else: 
        neighbor = query.filter(Task.position > current.position)\
                        .order_by(Task.position.asc()).first()

    if neighbor:
        current.position, neighbor.position = neighbor.position, current.position
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/delete/<int:id>')
def delete_task(id):
    task = db.session.get(Task, id)
    if task:
        db.session.delete(task)
        db.session.commit()
    return redirect(url_for('index'))

# --- SWEEP FUNCTION ---
@app.route('/sweep')
def sweep_completed():
    # Deletes all completed tasks
    db.session.query(Task).filter(Task.completed_at.isnot(None)).delete()
    db.session.commit()
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Auto-Backup
    if os.path.exists(db_path):
        with app.app_context():
            try: db.session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            except: pass
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        shutil.copy(db_path, os.path.join(backup_dir, f"tasks_backup_{ts}.db"))

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
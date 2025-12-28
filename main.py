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
    color = db.Column(db.String(20), default='default')
    label = db.Column(db.String(50), nullable=True) 
    due_date = db.Column(db.String(20), nullable=True)
    
    # NEW FIELD: Completion Note
    completion_note = db.Column(db.Text, nullable=True)

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
        # Migrate new column
        try: conn.execute(text("ALTER TABLE task ADD COLUMN completion_note TEXT"))
        except: pass

# --- ROUTES ---

@app.route('/')
def index():
    # 1. Check for filter parameter
    filter_label = request.args.get('label')
    
    # 2. Base Query
    query = Task.query
    
    # 3. Apply Filter if it exists
    if filter_label:
        query = query.filter(Task.label == filter_label)
        
    tasks = query.all()
    
    # 4. Get Unique Labels for the top bar (SQL Distinct)
    # We only want labels that are not NULL and not empty strings
    unique_labels_query = db.session.query(Task.label)\
        .filter(Task.label.isnot(None))\
        .filter(Task.label != "")\
        .distinct().all()
    
    # Flatten the result (SQLAlchemy returns tuples like [('Work',), ('Home',)])
    all_labels = sorted([l[0] for l in unique_labels_query])

    # 5. Sorting Logic (Same as before)
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
                           active_filter=filter_label)

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/add', methods=['POST'])
def add_task():
    content = request.form.get('content')
    color = request.form.get('color', 'default')
    label = request.form.get('label')
    due_date = request.form.get('due_date')

    if content:
        max_pos = db.session.query(db.func.max(Task.position)).scalar()
        new_pos = (max_pos + 1) if max_pos is not None else 0
        new_task = Task(content=content, position=new_pos, color=color, label=label if label else None, due_date=due_date if due_date else None)
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
        
        lbl = request.form.get('label')
        dd = request.form.get('due_date')
        task.label = lbl if lbl else None
        task.due_date = dd if dd else None
        
        # Save completion note ONLY if task is completed
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
            # UN-CHECKING: Wipe the note and date
            task.completed_at = None
            task.completion_note = None  # <--- DISAPPEARING LOGIC
            max_pos = db.session.query(db.func.max(Task.position)).scalar() or 0
            task.position = max_pos + 1
        else:
            # CHECKING
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
        db.session.delete(task)
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/sweep')
def sweep_completed():
    db.session.query(Task).filter(Task.completed_at.isnot(None)).delete()
    db.session.commit()
    return redirect(url_for('index'))

if __name__ == '__main__':
    if os.path.exists(db_path):
        with app.app_context():
            try: db.session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            except: pass
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
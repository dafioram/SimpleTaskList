import datetime
import sqlite3
import os
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

# Initialize SQLAlchemy with no app explicitly bound yet
db = SQLAlchemy()

# --- ASSOCIATION TABLE ---
task_labels = db.Table('task_labels',
    db.Column('task_id', db.Integer, db.ForeignKey('task.id'), primary_key=True),
    db.Column('label_id', db.Integer, db.ForeignKey('label.id'), primary_key=True)
)

# --- NEW LABEL MODEL ---
class Label(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

# --- MODEL ---
class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    position = db.Column(db.Integer, default=0)
    color = db.Column(db.String(20), default='default')
    
    # Metadata
    # Legacy label column retained for safe migration. 
    label = db.Column(db.String(50), nullable=True) 
    
    # New Many-to-Many Relationship for multiple labels
    labels = db.relationship('Label', secondary=task_labels, lazy='subquery',
        backref=db.backref('tasks', lazy=True))
        
    assignee = db.Column(db.String(50), nullable=True)
    due_date = db.Column(db.String(20), nullable=True)
    completion_note = db.Column(db.Text, nullable=True)
    
    # Dependency (Top-Down Epic/Subtask Model)
    parent_id = db.Column(db.Integer, nullable=True)

    # Context / Details
    context = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    completed_at = db.Column(db.DateTime, nullable=True) 

    @property
    def due_color(self):
        if not self.due_date:
            return 'default'
        
        try:
            # If the database handed us a string, parse it into a date object first
            if isinstance(self.due_date, str):
                # Adjust the '%Y-%m-%d' format if your frontend sends it differently!
                target_date = datetime.datetime.strptime(self.due_date, '%Y-%m-%d').date()
            else:
                target_date = self.due_date

            days_left = (target_date - datetime.date.today()).days

            if days_left < 0:
                return 'red'
            elif days_left <= 3:
                return 'red'
            elif days_left <= 7:
                return 'orange'
            elif days_left <= 14:
                return 'yellow'
            elif days_left <= 30:
                return 'blue'
            else:
                return 'green'

        except Exception as e:
            print(f"CRASH in due_color logic: {e}")
            return 'default'

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

# --- INITIALIZATION & MIGRATION ---
def init_db(app):
    """Binds the database to the app and runs migrations."""
    db.init_app(app)
    
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
            # Switched to parent_id for the Epic/Sub-task structure
            try: conn.execute(text("ALTER TABLE task ADD COLUMN parent_id INTEGER"))
            except: pass
            try: conn.execute(text("ALTER TABLE task ADD COLUMN context TEXT"))
            except: pass
            try: conn.execute(text("ALTER TABLE task ADD COLUMN assignee VARCHAR(50)"))
            except: pass

        # --- ONE-TIME DATA MIGRATION FOR LABELS ---
        try:
            # Find any old string labels that haven't been moved yet
            legacy_tasks = db.session.execute(text("SELECT id, label FROM task WHERE label IS NOT NULL AND label != ''")).fetchall()
            for t_id, lbl_name in legacy_tasks:
                task = db.session.get(Task, t_id)
                if task:
                    # Clean and Title Case
                    clean_name = lbl_name.strip().title()
                    lbl = Label.query.filter_by(name=clean_name).first()
                    if not lbl:
                        lbl = Label(name=clean_name)
                        db.session.add(lbl)
                    if lbl not in task.labels:
                        task.labels.append(lbl)
            
            # Wipe old label string to prevent running migration again
            db.session.execute(text("UPDATE task SET label = NULL WHERE label IS NOT NULL"))
            db.session.commit()
        except Exception as e:
            pass # Old column might not exist yet or other DB error during migration

# --- UTILITIES ---
def perform_backup(src_path, backup_root):
    """Safely copies the SQLite database file."""
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
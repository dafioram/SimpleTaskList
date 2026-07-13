import datetime
import sqlite3
import os
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

# Initialize SQLAlchemy with no app explicitly bound yet
db = SQLAlchemy()

# --- ASSOCIATION TABLE FOR LABELS ---
task_labels = db.Table('task_labels',
    db.Column('task_id', db.Integer, db.ForeignKey('task.id'), primary_key=True),
    db.Column('label_id', db.Integer, db.ForeignKey('label.id'), primary_key=True)
)

# --- LABEL MODEL ---
class Label(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

# --- NEW TASK RELATIONSHIP MODEL ---
class TaskRelationship(db.Model):
    __tablename__ = 'task_relationship'
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id', ondelete='CASCADE'), nullable=False)
    related_task_id = db.Column(db.Integer, db.ForeignKey('task.id', ondelete='CASCADE'), nullable=False)
    # 1. For dependent relationship related_task_id must be done before task_id
    relationship_type = db.Column(db.String(50), nullable=False, default='dependency')

# --- MODEL ---
class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    position = db.Column(db.Integer, default=0)
    color = db.Column(db.String(20), default='default')
    
    # Metadata
    label = db.Column(db.String(50), nullable=True) 
    
    # Many-to-Many Relationship for multiple labels
    labels = db.relationship('Label', secondary=task_labels, lazy='subquery',
        backref=db.backref('tasks', lazy=True))
        
    assignee = db.Column(db.String(50), nullable=True)
    due_date = db.Column(db.String(20), nullable=True)
    completion_note = db.Column(db.Text, nullable=True)
    
    # Deprecated: Phasing out in favor of TaskRelationship table
    parent_id = db.Column(db.Integer, nullable=True)

    # Context / Details
    context = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at   = db.Column(db.DateTime, default=datetime.datetime.now)
    completed_at = db.Column(db.DateTime, nullable=True)
    updated_at   = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    @property
    def due_color(self):
        if not self.due_date:
            return 'default'
        
        try:
            if isinstance(self.due_date, str):
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
        
        # --- AUTO-MIGRATION FOR SCHEMA UPGRADES ---
        with db.engine.connect() as conn:
            columns_to_add = [
                ("color", "VARCHAR(20) DEFAULT 'default'"),
                ("label", "VARCHAR(50)"),
                ("due_date", "VARCHAR(20)"),
                ("completion_note", "TEXT"),
                ("parent_id", "INTEGER"),
                ("context", "TEXT"),
                ("assignee", "VARCHAR(50)"),
                ("updated_at", "DATETIME")
            ]
            for col_name, col_type in columns_to_add:
                try: conn.execute(text(f"ALTER TABLE task ADD COLUMN {col_name} {col_type}"))
                except: pass

        # --- ONE-TIME DATA MIGRATION FOR LABELS ---
        try:
            legacy_tasks = db.session.execute(text("SELECT id, label FROM task WHERE label IS NOT NULL AND label != ''")).fetchall()
            for t_id, lbl_name in legacy_tasks:
                task = db.session.get(Task, t_id)
                if task:
                    clean_name = lbl_name.strip().title()
                    lbl = Label.query.filter_by(name=clean_name).first()
                    if not lbl:
                        lbl = Label(name=clean_name)
                        db.session.add(lbl)
                    if lbl not in task.labels:
                        task.labels.append(lbl)
            
            db.session.execute(text("UPDATE task SET label = NULL WHERE label IS NOT NULL"))
            db.session.commit()
        except Exception:
            pass

        # --- NEW: ONE-TIME DATA MIGRATION FOR TASK DEPENDENCIES ---
        try:
            legacy_deps = db.session.execute(text("SELECT id, parent_id FROM task WHERE parent_id IS NOT NULL")).fetchall()
            for t_id, p_id in legacy_deps:
                # In the old structure, parent_id was the blocker (prerequisite)
                exists = TaskRelationship.query.filter_by(
                    task_id=t_id, 
                    related_task_id=p_id, 
                    relationship_type='dependency'
                ).first()
                if not exists:
                    migrated_rel = TaskRelationship(
                        task_id=t_id,
                        related_task_id=p_id,
                        relationship_type='dependency'
                    )
                    db.session.add(migrated_rel)
            
            # ADD THIS LINE: Clear out the deprecated parent_id so we don't migrate it again
            db.session.execute(text("UPDATE task SET parent_id = NULL WHERE parent_id IS NOT NULL"))
            
            db.session.commit()
        except Exception as e:
            print(f"Legacy dependency migration skipped or completed: {e}")

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
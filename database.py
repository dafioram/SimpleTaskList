import datetime
import glob
import logging
import os
import sqlite3

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

log = logging.getLogger(__name__)

# --- PATHS ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'tasks.db')
BACKUP_DIR = os.path.join(DATA_DIR, 'backups')

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

# --- TASK RELATIONSHIP MODEL ---
class TaskRelationship(db.Model):
    __tablename__ = 'task_relationship'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id', ondelete='CASCADE'), nullable=False)
    related_task_id = db.Column(db.Integer, db.ForeignKey('task.id', ondelete='CASCADE'), nullable=False)
    # 'dependency': related_task_id must be done before task_id
    relationship_type = db.Column(db.String(50), nullable=False, default='dependency')

# --- MODEL ---
class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    position = db.Column(db.Integer, default=0)
    color = db.Column(db.String(20), default='default')

    # Metadata
    label = db.Column(db.String(50), nullable=True)  # Deprecated: migrated to `labels`

    # Many-to-Many Relationship for multiple labels
    labels = db.relationship('Label', secondary=task_labels, lazy='subquery',
        backref=db.backref('tasks', lazy=True))

    assignee = db.Column(db.String(50), nullable=True)
    due_date = db.Column(db.String(20), nullable=True)
    completion_note = db.Column(db.Text, nullable=True)

    # Deprecated: migrated to the TaskRelationship table
    parent_id = db.Column(db.Integer, nullable=True)

    # Context / Details
    context = db.Column(db.Text, nullable=True)

    # Timestamps (server local time; set TZ for Docker).
    # updated_at is set explicitly on edits and completion changes, not on
    # reorder/promote, so dragging tasks around doesn't change it.
    created_at   = db.Column(db.DateTime, default=datetime.datetime.now)
    completed_at = db.Column(db.DateTime, nullable=True)
    updated_at   = db.Column(db.DateTime, default=datetime.datetime.now)

    def touch(self):
        self.updated_at = datetime.datetime.now()

    def _days_left(self):
        if not self.due_date:
            return None
        try:
            due = datetime.datetime.strptime(self.due_date, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            log.warning("Task %s has an unreadable due date: %r", self.id, self.due_date)
            return None
        return (due - datetime.date.today()).days

    @property
    def due_color(self):
        days_left = self._days_left()
        if days_left is None:
            return 'default'
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
        return 'green'

    def get_time_display(self):
        delta = self._days_left()
        if delta is None: return None
        if delta == 0: return "Due today"
        if delta == 1: return "1 day left"
        if delta > 1:  return f"{delta} days left"
        if delta == -1: return "1 day overdue"
        return f"{abs(delta)} days overdue"


# Columns added after the first release, created on older databases at startup.
_COLUMN_MIGRATIONS = [
    ("color", "VARCHAR(20) DEFAULT 'default'"),
    ("label", "VARCHAR(50)"),
    ("due_date", "VARCHAR(20)"),
    ("completion_note", "TEXT"),
    ("parent_id", "INTEGER"),
    ("context", "TEXT"),
    ("assignee", "VARCHAR(50)"),
    ("updated_at", "DATETIME"),
]


# --- INITIALIZATION & MIGRATION ---
def init_db(app):
    """Binds the database to the app and runs migrations."""
    db.init_app(app)

    with app.app_context():
        db.session.execute(text("PRAGMA journal_mode=WAL"))
        db.create_all()
        _migrate_columns()
        _migrate_legacy_labels()
        _migrate_legacy_parents()


def _migrate_columns():
    with db.engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(task)"))}
        for col_name, col_type in _COLUMN_MIGRATIONS:
            if col_name in existing:
                continue
            try:
                conn.execute(text(f"ALTER TABLE task ADD COLUMN {col_name} {col_type}"))
                log.info("Migrated: added column task.%s", col_name)
            except OperationalError as e:
                # Another worker may have added it a moment ago.
                if 'duplicate column' not in str(e).lower():
                    raise


def _migrate_legacy_labels():
    """One-time: copies the old single `label` column into the labels table."""
    try:
        legacy = db.session.execute(text(
            "SELECT id, label FROM task WHERE label IS NOT NULL AND label != ''")).fetchall()
        if not legacy:
            return
        for t_id, lbl_name in legacy:
            task = db.session.get(Task, t_id)
            clean_name = lbl_name.strip().title()
            if not task or not clean_name:
                continue
            lbl = Label.query.filter_by(name=clean_name).first()
            if not lbl:
                lbl = Label(name=clean_name)
                db.session.add(lbl)
            if lbl not in task.labels:
                task.labels.append(lbl)
        db.session.execute(text("UPDATE task SET label = NULL WHERE label IS NOT NULL"))
        db.session.commit()
        log.info("Migrated %d legacy labels", len(legacy))
    except Exception:
        db.session.rollback()
        log.exception("Legacy label migration failed; it will be retried on next start")


def _migrate_legacy_parents():
    """One-time: turns old parent_id links into dependencies.

    In the old app a parent (epic) showed "Requires: #child", i.e. the parent
    can't be finished until its subtasks are. So the parent is the dependent
    task and the child is the prerequisite.
    """
    try:
        legacy = db.session.execute(text(
            "SELECT id, parent_id FROM task WHERE parent_id IS NOT NULL")).fetchall()
        if not legacy:
            return
        for child_id, parent_id in legacy:
            exists = TaskRelationship.query.filter_by(
                task_id=parent_id, related_task_id=child_id, relationship_type='dependency'
            ).first()
            if not exists and child_id != parent_id:
                db.session.add(TaskRelationship(
                    task_id=parent_id, related_task_id=child_id, relationship_type='dependency'))
        db.session.execute(text("UPDATE task SET parent_id = NULL WHERE parent_id IS NOT NULL"))
        db.session.commit()
        log.info("Migrated %d legacy parent links to dependencies", len(legacy))
    except Exception:
        db.session.rollback()
        log.exception("Legacy dependency migration failed; it will be retried on next start")


# --- BACKUPS ---
def perform_backup(src_path=DB_PATH, backup_dir=BACKUP_DIR):
    """Copies the SQLite database with the online backup API.

    Only the newest backup is kept: older ones are removed after the new copy
    has been written successfully. Returns (success, filename_or_error).
    """
    src = dst = None
    try:
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dst_path = os.path.join(backup_dir, f"tasks_backup_{timestamp}.db")

        src = sqlite3.connect(src_path)
        dst = sqlite3.connect(dst_path)
        with dst:
            src.backup(dst)
    except Exception as e:
        log.exception("Database backup failed")
        return False, str(e)
    finally:
        if dst is not None: dst.close()
        if src is not None: src.close()

    for old in glob.glob(os.path.join(backup_dir, 'tasks_backup_*.db')):
        if os.path.abspath(old) != os.path.abspath(dst_path):
            try:
                os.remove(old)
            except OSError:
                log.warning("Could not remove old backup %s", old)

    log.info("Database backed up to %s", dst_path)
    return True, os.path.basename(dst_path)

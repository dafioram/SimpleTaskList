/* SimpleTaskList — reads backup files.
 *
 *   .json  a backup exported by this app
 *   .db    the tasks.db from the old server versions (SimpleTaskList or TaskApp).
 *          The SQLite reader (vendor/sql-wasm.*, ~700 KB) is only downloaded
 *          when one of these is imported.
 *
 * Importer.read(file) resolves to the same shape as Store.parseBackup().
 */
(function () {
  'use strict';

  var sqlPromise = null;

  function loadSqlJs() {
    if (sqlPromise) return sqlPromise;
    sqlPromise = new Promise(function (resolve, reject) {
      if (window.initSqlJs) return resolve();
      var s = document.createElement('script');
      s.src = 'vendor/sql-wasm.js';
      s.onload = resolve;
      s.onerror = function () { reject(new Error("Couldn't load the database reader. Connect to the internet once, then try again.")); };
      document.head.appendChild(s);
    }).then(function () {
      return window.initSqlJs({ locateFile: function (f) { return 'vendor/' + f; } });
    });
    sqlPromise.catch(function () { sqlPromise = null; });
    return sqlPromise;
  }

  function isSqlite(bytes) {
    var sig = 'SQLite format 3';
    if (bytes.length < 16) return false;
    for (var i = 0; i < sig.length; i++) if (bytes[i] !== sig.charCodeAt(i)) return false;
    return true;
  }

  /** "2026-01-02 13:45:00.123456" (naive local time, as Python stored it) -> ISO string. */
  function pyDate(v) {
    if (!v) return null;
    var m = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?$/.exec(String(v).trim());
    if (!m) return null;
    var ms = m[7] ? Number((m[7] + '000').slice(0, 3)) : 0;
    var d = new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0), ms);
    return isNaN(d) ? null : d.toISOString();
  }

  function rows(db, sql) {
    var res = db.exec(sql);
    if (!res.length) return [];
    var cols = res[0].columns;
    return res[0].values.map(function (vals) {
      var o = {};
      cols.forEach(function (c, i) { o[c] = vals[i]; });
      return o;
    });
  }

  function readDatabase(SQL, bytes) {
    var db = new SQL.Database(bytes);
    try {
      var tables = new Set(rows(db, "SELECT name FROM sqlite_master WHERE type='table'").map(function (r) { return r.name; }));
      if (!tables.has('task')) throw new Error("This database doesn't contain any tasks.");
      var cols = new Set(rows(db, 'PRAGMA table_info(task)').map(function (r) { return r.name; }));

      var tasks = new Map();
      rows(db, 'SELECT * FROM task').forEach(function (r) {
        tasks.set(r.id, {
          id: r.id,
          content: r.content,
          context: cols.has('context') ? r.context : null,
          labels: [],
          assignee: cols.has('assignee') ? r.assignee : null,
          due_date: cols.has('due_date') ? r.due_date : null,
          requires: [],
          position: r.position || 0,
          created_at: pyDate(r.created_at),
          updated_at: cols.has('updated_at') ? pyDate(r.updated_at) : null,
          completed_at: pyDate(r.completed_at),
          completion_note: cols.has('completion_note') ? r.completion_note : null,
          _label: cols.has('label') ? r.label : null,
          _parent: cols.has('parent_id') ? r.parent_id : null
        });
      });

      // Labels: TaskApp's label tables, plus the old single `label` column.
      if (tables.has('label') && tables.has('task_labels')) {
        rows(db, 'SELECT tl.task_id AS task_id, l.name AS name FROM task_labels tl JOIN label l ON l.id = tl.label_id')
          .forEach(function (r) { var t = tasks.get(r.task_id); if (t) t.labels.push(r.name); });
      }
      tasks.forEach(function (t) { if (t._label) t.labels.push(t._label); });

      // Dependencies: TaskApp's relationship table ("task requires related task").
      if (tables.has('task_relationship')) {
        rows(db, "SELECT task_id, related_task_id FROM task_relationship WHERE relationship_type = 'dependency'")
          .forEach(function (r) { var t = tasks.get(r.task_id); if (t) t.requires.push(r.related_task_id); });
      }
      // SimpleTaskList's parent_id: the parent showed "Requires: #child".
      tasks.forEach(function (child) {
        var parent = child._parent && tasks.get(child._parent);
        if (parent && parent.id !== child.id) parent.requires.push(child.id);
      });

      var list = Array.from(tasks.values()).map(function (t) { delete t._label; delete t._parent; return t; });
      var maxId = list.reduce(function (m, t) { return Math.max(m, t.id); }, 0);
      return Store.parseBackup({ tasks: list, next_id: maxId + 1 });
    } finally {
      db.close();
    }
  }

  function read(file) {
    return file.arrayBuffer().then(function (buf) {
      var bytes = new Uint8Array(buf);
      if (isSqlite(bytes)) {
        return loadSqlJs().then(function (SQL) {
          var parsed = readDatabase(SQL, bytes);
          parsed.source = 'database';
          return parsed;
        });
      }
      var data;
      try {
        data = JSON.parse(new TextDecoder().decode(bytes));
      } catch (e) {
        throw new Error("This file isn't a SimpleTaskList backup or tasks.db database.");
      }
      var parsed = Store.parseBackup(data);
      parsed.source = 'backup';
      return parsed;
    });
  }

  window.Importer = { read: read };
})();

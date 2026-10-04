/* SimpleTaskList — data layer.
 *
 * Everything the old Flask backend did, in the browser:
 *   - persistence (IndexedDB, falling back to localStorage, then memory)
 *   - the task rules (labels, dependencies, ordering, filters, counts)
 *   - export / import of backups
 *
 * No DOM code lives here. app.js renders whatever this module holds.
 *
 * Task shape:
 *   { id, content, context, labels: [name], assignee, due_date: 'YYYY-MM-DD',
 *     requires: [taskId], position, created_at, updated_at, completed_at,
 *     completion_note }        (timestamps are ISO strings, missing values are null)
 */
(function () {
  'use strict';

  var DB_NAME = 'simpletasklist';
  var DB_VERSION = 1;
  var LS_KEY = 'simpletasklist:data';
  var EXPORT_FORMAT = 1;

  // ---------------------------------------------------------------- helpers

  function nowISO() { return new Date().toISOString(); }

  function clone(obj) { return JSON.parse(JSON.stringify(obj)); }

  /** Python's str.title(): first letter after any non-letter is upper-cased, the rest lower. */
  function titleCase(s) {
    return String(s).toLowerCase().replace(/(^|[^\p{L}])(\p{L})/gu, function (m, before, letter) {
      return before + letter.toUpperCase();
    });
  }

  function cleanLabel(raw) {
    var name = titleCase(String(raw == null ? '' : raw).trim()).slice(0, 50).trim();
    if (!name || name.toLowerCase() === 'all') return null;
    return name;
  }

  /** De-duplicated, title-cased label list (same rules as the server version). */
  function cleanLabels(list) {
    var out = [], seen = Object.create(null);
    (list || []).forEach(function (raw) {
      var name = cleanLabel(raw);
      if (name && !seen[name.toLowerCase()]) {
        seen[name.toLowerCase()] = true;
        out.push(name);
      }
    });
    return out;
  }

  function cleanAssignee(raw) {
    var v = String(raw == null ? '' : raw).trim();
    if (!v || v.toLowerCase() === 'anyone' || v.toLowerCase() === 'unassigned') return null;
    return titleCase(v).slice(0, 50);
  }

  function cleanDue(raw) {
    var v = String(raw == null ? '' : raw).trim();
    return /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null;
  }

  function cleanText(raw) {
    var v = raw == null ? '' : String(raw);
    return v.trim() ? v : null;
  }

  function localDateString(d) {
    var m = d.getMonth() + 1, day = d.getDate();
    return d.getFullYear() + '-' + (m < 10 ? '0' : '') + m + '-' + (day < 10 ? '0' : '') + day;
  }

  /** Whole days from today (local time) until a 'YYYY-MM-DD' date, or null. */
  function daysLeft(due) {
    if (!due) return null;
    var p = due.split('-').map(Number);
    var target = new Date(p[0], p[1] - 1, p[2]);
    if (isNaN(target)) return null;
    var t = new Date();
    var today = new Date(t.getFullYear(), t.getMonth(), t.getDate());
    return Math.round((target - today) / 86400000);
  }

  function dueColor(task) {
    var d = daysLeft(task.due_date);
    if (d === null) return 'default';
    if (d < 0) return 'red';
    if (d <= 3) return 'red';
    if (d <= 7) return 'orange';
    if (d <= 14) return 'yellow';
    if (d <= 30) return 'blue';
    return 'green';
  }

  function timeDisplay(task) {
    var d = daysLeft(task.due_date);
    if (d === null) return null;
    if (d === 0) return 'Due today';
    if (d === 1) return '1 day left';
    if (d > 1) return d + ' days left';
    if (d === -1) return '1 day overdue';
    return Math.abs(d) + ' days overdue';
  }

  var ASSIGNEE_PALETTE = [
    '#d0bcff', '#448aff', '#69f0ae', '#ffab40', '#ff5252',
    '#ff80ab', '#64ffda', '#536dfe', '#f44336', '#e91e63',
    '#9c27b0', '#00bcd4', '#4caf50', '#ff9800', '#cddc39',
    '#8bc34a', '#03a9f4', '#009688', '#b388ff', '#8c9eff',
    '#80d8ff', '#a7ffeb', '#ccff90', '#ffe57f', '#ff9e80'
  ];
  var LABEL_PALETTE = ['purple', 'blue', 'green', 'orange', 'red', 'pink', 'teal', 'yellow', 'indigo'];

  // Same hashes as the server version, so colors don't change after moving over.
  function hashName(name, mult) {
    var h = 0, i = 0;
    for (var ch of name) { h += ch.codePointAt(0) * (i + 1) * mult; i++; }
    return h;
  }
  function assigneeColor(name) { return ASSIGNEE_PALETTE[hashName(name, 31) % ASSIGNEE_PALETTE.length]; }
  function labelColor(name) { return LABEL_PALETTE[hashName(name, 17) % LABEL_PALETTE.length]; }

  // ------------------------------------------------------------ persistence

  function idbAdapter() {
    var dbp = new Promise(function (resolve, reject) {
      if (!('indexedDB' in window)) return reject(new Error('IndexedDB not available'));
      var req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains('tasks')) db.createObjectStore('tasks', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('meta')) db.createObjectStore('meta');
      };
      req.onsuccess = function () {
        var db = req.result;
        // Another tab upgraded the schema: close so it can proceed.
        db.onversionchange = function () { db.close(); };
        resolve(db);
      };
      req.onerror = function () { reject(req.error); };
      req.onblocked = function () { reject(new Error('Database is blocked by another tab')); };
    });

    function tx(stores, mode, work) {
      return dbp.then(function (db) {
        return new Promise(function (resolve, reject) {
          var t = db.transaction(stores, mode);
          var result;
          t.oncomplete = function () { resolve(result); };
          t.onerror = function () { reject(t.error); };
          t.onabort = function () { reject(t.error || new Error('Transaction aborted')); };
          result = work(t);
        });
      });
    }

    function getAll(store) {
      return new Promise(function (resolve, reject) {
        var r = store.getAll();
        r.onsuccess = function () { resolve(r.result); };
        r.onerror = function () { reject(r.error); };
      });
    }

    return {
      kind: 'indexeddb',
      ready: dbp,
      load: function () {
        return dbp.then(function (db) {
          return new Promise(function (resolve, reject) {
            var t = db.transaction(['tasks', 'meta'], 'readonly');
            var tasks, metaKeys, metaVals;
            Promise.all([
              getAll(t.objectStore('tasks')),
              new Promise(function (res, rej) { var r = t.objectStore('meta').getAllKeys(); r.onsuccess = function () { res(r.result); }; r.onerror = function () { rej(r.error); }; }),
              getAll(t.objectStore('meta'))
            ]).then(function (all) {
              tasks = all[0]; metaKeys = all[1]; metaVals = all[2];
              var meta = {};
              metaKeys.forEach(function (k, i) { meta[k] = metaVals[i]; });
              resolve({ tasks: tasks, meta: meta });
            }, reject);
          });
        });
      },
      save: function (puts, deletes, meta) {
        return tx(['tasks', 'meta'], 'readwrite', function (t) {
          var ts = t.objectStore('tasks'), ms = t.objectStore('meta');
          (deletes || []).forEach(function (id) { ts.delete(id); });
          (puts || []).forEach(function (task) { ts.put(task); });
          Object.keys(meta || {}).forEach(function (k) { ms.put(meta[k], k); });
        });
      },
      replace: function (tasks, meta) {
        return tx(['tasks', 'meta'], 'readwrite', function (t) {
          var ts = t.objectStore('tasks'), ms = t.objectStore('meta');
          ts.clear();
          tasks.forEach(function (task) { ts.put(task); });
          Object.keys(meta).forEach(function (k) { ms.put(meta[k], k); });
        });
      }
    };
  }

  /** Whole dataset as one JSON blob. Used only if IndexedDB is unavailable. */
  function lsAdapter(state) {
    localStorage.setItem(LS_KEY + ':probe', '1');
    localStorage.removeItem(LS_KEY + ':probe');
    function write() {
      localStorage.setItem(LS_KEY, JSON.stringify({ tasks: Array.from(state.tasks.values()), meta: state.meta }));
      return Promise.resolve();
    }
    return {
      kind: 'localstorage',
      ready: Promise.resolve(),
      load: function () {
        var raw = localStorage.getItem(LS_KEY);
        var data = raw ? JSON.parse(raw) : { tasks: [], meta: {} };
        return Promise.resolve({ tasks: data.tasks || [], meta: data.meta || {} });
      },
      save: write,
      replace: write
    };
  }

  function memoryAdapter() {
    return {
      kind: 'memory',
      ready: Promise.resolve(),
      load: function () { return Promise.resolve({ tasks: [], meta: {} }); },
      save: function () { return Promise.resolve(); },
      replace: function () { return Promise.resolve(); }
    };
  }

  // ------------------------------------------------------------------ state

  var state = {
    tasks: new Map(),      // id -> task
    meta: { next_id: 1 },  // next_id, last_export
    adapter: null
  };
  var listeners = [];
  var channel = ('BroadcastChannel' in window) ? new BroadcastChannel('simpletasklist') : null;

  function emit(source) { listeners.forEach(function (fn) { fn(source); }); }

  function persist(puts, deletes, metaKeys) {
    var meta = {};
    (metaKeys || []).forEach(function (k) { meta[k] = state.meta[k]; });
    return state.adapter.save(puts.map(clone), deletes, meta).then(function () {
      if (channel) channel.postMessage('changed');
    }, function (err) {
      console.error('Save failed', err);
      throw err;
    });
  }

  function sanitizeTask(raw) {
    var id = Number(raw.id);
    if (!Number.isInteger(id) || id < 1) return null;
    var content = String(raw.content == null ? '' : raw.content).trim();
    if (!content) return null;
    function iso(v) {
      if (!v) return null;
      var d = new Date(v);
      return isNaN(d) ? null : d.toISOString();
    }
    var created = iso(raw.created_at) || nowISO();
    return {
      id: id,
      content: content,
      context: cleanText(raw.context),
      labels: cleanLabels(Array.isArray(raw.labels) ? raw.labels : []),
      assignee: raw.assignee ? cleanAssignee(raw.assignee) : null,
      due_date: cleanDue(raw.due_date),
      requires: Array.isArray(raw.requires)
        ? Array.from(new Set(raw.requires.map(Number).filter(function (n) { return Number.isInteger(n) && n !== id; })))
        : [],
      position: Number.isFinite(Number(raw.position)) ? Number(raw.position) : 0,
      created_at: created,
      updated_at: iso(raw.updated_at) || created,
      completed_at: iso(raw.completed_at),
      completion_note: raw.completed_at ? cleanText(raw.completion_note) : null
    };
  }

  function loadInto(data) {
    state.tasks = new Map();
    (data.tasks || []).forEach(function (raw) {
      var t = sanitizeTask(raw);
      if (t) state.tasks.set(t.id, t);
    });
    var maxId = 0;
    state.tasks.forEach(function (t) { if (t.id > maxId) maxId = t.id; });
    state.meta = Object.assign({}, data.meta || {});
    state.meta.next_id = Math.max(Number(state.meta.next_id) || 1, maxId + 1);
  }

  function init() {
    var adapter;
    try { adapter = idbAdapter(); } catch (e) { adapter = null; }
    var p = adapter ? adapter.ready.then(function () { return adapter; }) : Promise.reject();
    return p.catch(function (err) {
      if (err) console.warn('IndexedDB unavailable, trying localStorage:', err);
      try { return lsAdapter(state); } catch (e) {
        console.warn('localStorage unavailable; changes will not be saved', e);
        return memoryAdapter();
      }
    }).then(function (a) {
      state.adapter = a;
      return a.load();
    }).then(function (data) {
      loadInto(data);
      if (channel) {
        channel.onmessage = function () {
          state.adapter.load().then(function (d) { loadInto(d); emit('remote'); });
        };
      }
      return state.adapter.kind;
    });
  }

  // ------------------------------------------------------------------ reads

  function all() { return Array.from(state.tasks.values()); }
  function get(id) { return state.tasks.get(Number(id)) || null; }

  function topPosition() {
    var min = null;
    state.tasks.forEach(function (t) { if (min === null || t.position < min) min = t.position; });
    return min === null ? 0 : min - 1;
  }

  /** { requiresMap: id -> [prereq tasks], blocksMap: id -> [tasks it blocks] } */
  function dependencyMaps() {
    var requiresMap = new Map(), blocksMap = new Map();
    state.tasks.forEach(function (t) {
      t.requires.forEach(function (pid) {
        var p = state.tasks.get(pid);
        if (!p) return;
        if (!requiresMap.has(t.id)) requiresMap.set(t.id, []);
        requiresMap.get(t.id).push(p);
        if (!blocksMap.has(pid)) blocksMap.set(pid, []);
        blocksMap.get(pid).push(t);
      });
    });
    var byId = function (a, b) { return a.id - b.id; };
    requiresMap.forEach(function (v) { v.sort(byId); });
    blocksMap.forEach(function (v) { v.sort(byId); });
    return { requiresMap: requiresMap, blocksMap: blocksMap };
  }

  /** Every task that directly or indirectly requires taskId (picking one as a prerequisite would loop). */
  function dependentsOf(taskId) {
    var blockedBy = new Map();
    state.tasks.forEach(function (t) {
      t.requires.forEach(function (pid) {
        if (!blockedBy.has(pid)) blockedBy.set(pid, []);
        blockedBy.get(pid).push(t.id);
      });
    });
    var found = new Set(), stack = [taskId];
    while (stack.length) {
      (blockedBy.get(stack.pop()) || []).forEach(function (dep) {
        if (!found.has(dep)) { found.add(dep); stack.push(dep); }
      });
    }
    return found;
  }

  /** Filter-bar data. Counts cover active tasks only; only labels some task uses are listed. */
  function sidebar() {
    var labelCounts = {}, assigneeCounts = {}, labelsInUse = new Set(), assignees = new Set();
    var totalActive = 0, dueCount = 0;
    state.tasks.forEach(function (t) {
      t.labels.forEach(function (l) { labelsInUse.add(l); });
      if (t.assignee) assignees.add(t.assignee);
      if (!t.completed_at) {
        totalActive++;
        if (t.due_date) dueCount++;
        t.labels.forEach(function (l) { labelCounts[l] = (labelCounts[l] || 0) + 1; });
        var key = t.assignee || 'Unassigned';
        assigneeCounts[key] = (assigneeCounts[key] || 0) + 1;
      }
    });
    var cmp = function (a, b) { return a < b ? -1 : a > b ? 1 : 0; };  // same order as Python sorted()
    var labels = Array.from(labelsInUse).sort(cmp);
    var people = Array.from(assignees).sort(cmp);
    return {
      labels: labels.map(function (l) { return { name: l, count: labelCounts[l] || 0 }; }),
      assignees: people.map(function (a) { return { name: a, count: assigneeCounts[a] || 0 }; }),
      unassignedCount: assigneeCounts.Unassigned || 0,
      totalActive: totalActive,
      dueCount: dueCount
    };
  }

  /** Tasks matching the filters: active ones by position, then completed ones newest first. */
  function view(filters) {
    var f = filters || {};
    var maps = dependencyMaps();
    var list = all().filter(function (t) {
      if (f.label && t.labels.indexOf(f.label) === -1) return false;
      if (f.assignee === 'Unassigned' ? t.assignee : (f.assignee && t.assignee !== f.assignee)) return false;
      if (f.due_only && !t.due_date) return false;
      if (f.rel === 'requires' && !maps.requiresMap.has(t.id)) return false;
      if (f.rel === 'blocks' && !maps.blocksMap.has(t.id)) return false;
      return true;
    });
    var active = list.filter(function (t) { return !t.completed_at; })
      .sort(function (a, b) { return a.position - b.position || a.id - b.id; });
    var done = list.filter(function (t) { return t.completed_at; })
      .sort(function (a, b) { return a.completed_at < b.completed_at ? 1 : a.completed_at > b.completed_at ? -1 : 0; });
    return { active: active, done: done, maps: maps };
  }

  // ---------------------------------------------------------------- writes
  // Each write updates memory first (the UI renders from it right away), then
  // persists. It resolves to an undo snapshot that restore() can put back.

  function snapshot(ids) {
    var snap = { tasks: [], missing: [] };
    ids.forEach(function (id) {
      var t = state.tasks.get(id);
      if (t) snap.tasks.push(clone(t)); else snap.missing.push(id);
    });
    return snap;
  }

  function add(content, labels) {
    content = String(content || '').trim();
    if (!content) return Promise.resolve(null);
    var now = nowISO();
    var task = {
      id: state.meta.next_id++,
      content: content, context: null,
      labels: cleanLabels(labels),
      assignee: null, due_date: null, requires: [],
      position: topPosition(),
      created_at: now, updated_at: now,
      completed_at: null, completion_note: null
    };
    state.tasks.set(task.id, task);
    emit('local');
    return persist([task], [], ['next_id']).then(function () { return task; });
  }

  /** Validates and applies an edit. Resolves { errors } without saving anything if invalid. */
  function update(id, fields) {
    var task = get(id);
    if (!task) return Promise.resolve({ errors: ['This task no longer exists.'] });
    var errors = [];
    var content = String(fields.content || '').trim();
    if (!content) errors.push("The task can't be empty.");

    var requires = [];
    (fields.requires || []).forEach(function (raw) {
      var n = Number(raw);
      if (Number.isInteger(n) && requires.indexOf(n) === -1) requires.push(n);
    });
    var loop = dependentsOf(task.id); loop.add(task.id);
    requires.forEach(function (pid) {
      if (loop.has(pid)) errors.push('#' + pid + " already depends on this task, so it can't also be a prerequisite.");
      else if (!state.tasks.has(pid)) errors.push('Task #' + pid + ' no longer exists.');
    });
    if (errors.length) return Promise.resolve({ errors: errors });

    var snap = snapshot([task.id]);
    task.content = content;
    task.context = cleanText(fields.context);
    task.labels = cleanLabels(fields.labels);
    task.assignee = cleanAssignee(fields.assignee);
    task.due_date = cleanDue(fields.due_date);
    task.requires = requires;
    if (task.completed_at) task.completion_note = cleanText(fields.completion_note);
    task.updated_at = nowISO();
    emit('local');
    return persist([task], []).then(function () { return { task: task, undo: snap }; });
  }

  function toggle(id) {
    var task = get(id);
    if (!task) return Promise.resolve(null);
    var snap = snapshot([task.id]);
    if (task.completed_at) {
      task.completed_at = null;
      task.completion_note = null;
      task.position = topPosition();
    } else {
      task.completed_at = nowISO();
    }
    task.updated_at = nowISO();
    emit('local');
    return persist([task], []).then(function () { return { task: task, undo: snap }; });
  }

  /** Moves a task to the top. Doesn't change its "updated" date. */
  function promote(id) {
    var task = get(id);
    if (!task) return Promise.resolve(null);
    var snap = snapshot([task.id]);
    task.position = topPosition();
    emit('local');
    return persist([task], []).then(function () { return { task: task, undo: snap }; });
  }

  /** New order for the visible active tasks; hidden (filtered-out) tasks keep their slots. */
  function reorder(visibleIds) {
    var active = all().filter(function (t) { return !t.completed_at; })
      .sort(function (a, b) { return a.position - b.position || a.id - b.id; });
    var byId = new Map(active.map(function (t) { return [t.id, t]; }));
    var seen = new Set(), order = [];
    visibleIds.forEach(function (raw) {
      var id = Number(raw);
      if (byId.has(id) && !seen.has(id)) { seen.add(id); order.push(id); }
    });
    var slots = [];
    active.forEach(function (t, i) { if (seen.has(t.id)) slots.push(i); });
    slots.forEach(function (slot, i) { active[slot] = byId.get(order[i]); });
    var changed = [];
    active.forEach(function (t, i) {
      if (t.position !== i) { t.position = i; changed.push(t); }
    });
    if (!changed.length) return Promise.resolve();
    emit('local');
    return persist(changed, []);
  }

  /** Deletes a task and removes it from other tasks' prerequisites. */
  function remove(id) {
    var task = get(id);
    if (!task) return Promise.resolve(null);
    var affected = all().filter(function (t) { return t.requires.indexOf(task.id) !== -1; });
    var snap = snapshot([task.id].concat(affected.map(function (t) { return t.id; })));
    state.tasks.delete(task.id);
    affected.forEach(function (t) { t.requires = t.requires.filter(function (r) { return r !== task.id; }); });
    emit('local');
    return persist(affected, [task.id]).then(function () { return { undo: snap }; });
  }

  /** Puts an undo snapshot back exactly as it was. */
  function restore(snap) {
    if (!snap) return Promise.resolve();
    snap.tasks.forEach(function (t) { state.tasks.set(t.id, clone(t)); });
    snap.missing.forEach(function (id) { state.tasks.delete(id); });
    emit('local');
    return persist(snap.tasks, snap.missing);
  }

  // ----------------------------------------------------------- backups

  function exportData() {
    return {
      app: 'SimpleTaskList',
      format: EXPORT_FORMAT,
      exported_at: nowISO(),
      next_id: state.meta.next_id,
      tasks: all().sort(function (a, b) { return a.id - b.id; }).map(clone)
    };
  }

  function markExported() {
    state.meta.last_export = nowISO();
    return state.adapter.save([], [], { last_export: state.meta.last_export });
  }

  /** Parses a backup object; throws a readable Error if it isn't one. */
  function parseBackup(data) {
    if (!data || typeof data !== 'object' || !Array.isArray(data.tasks)) {
      throw new Error("This file isn't a SimpleTaskList backup.");
    }
    if (data.format && data.format > EXPORT_FORMAT) {
      throw new Error('This backup is from a newer version of the app. Update the app first.');
    }
    var tasks = [], ids = new Set();
    data.tasks.forEach(function (raw) {
      var t = raw && sanitizeTask(raw);
      if (t && !ids.has(t.id)) { ids.add(t.id); tasks.push(t); }
    });
    tasks.forEach(function (t) { t.requires = t.requires.filter(function (r) { return ids.has(r); }); });
    return { tasks: tasks, next_id: Number(data.next_id) || 1, skipped: data.tasks.length - tasks.length };
  }

  /** Replaces every task with a parsed backup. Resolves an undo snapshot of the old data. */
  function replaceAll(parsed) {
    var before = { tasks: all().map(clone), next_id: state.meta.next_id };
    loadInto({ tasks: parsed.tasks, meta: Object.assign({}, state.meta, { next_id: parsed.next_id }) });
    emit('local');
    return state.adapter.replace(all().map(clone), state.meta).then(function () {
      if (channel) channel.postMessage('changed');
      return { undo: before };
    });
  }

  function undoReplace(before) {
    loadInto({ tasks: before.tasks, meta: Object.assign({}, state.meta, { next_id: before.next_id }) });
    emit('local');
    return state.adapter.replace(all().map(clone), state.meta).then(function () {
      if (channel) channel.postMessage('changed');
    });
  }

  window.Store = {
    init: init,
    onChange: function (fn) { listeners.push(fn); },
    kind: function () { return state.adapter ? state.adapter.kind : null; },
    meta: function () { return state.meta; },
    all: all, get: get, view: view, sidebar: sidebar, dependentsOf: dependentsOf,
    add: add, update: update, toggle: toggle, promote: promote, reorder: reorder,
    remove: remove, restore: restore,
    exportData: exportData, markExported: markExported, parseBackup: parseBackup,
    replaceAll: replaceAll, undoReplace: undoReplace,
    util: {
      titleCase: titleCase, cleanLabel: cleanLabel, cleanLabels: cleanLabels,
      dueColor: dueColor, timeDisplay: timeDisplay, daysLeft: daysLeft,
      assigneeColor: assigneeColor, labelColor: labelColor, localDateString: localDateString
    }
  };
})();

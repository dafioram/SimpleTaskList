/* SimpleTaskList — UI. Renders what Store holds and turns taps into Store calls.
 * All user text goes into the page with textContent, never as HTML.
 */
(function () {
  'use strict';

  var U = Store.util;
  var $ = function (id) { return document.getElementById(id); };
  var coarse = window.matchMedia('(pointer: coarse)').matches;
  var FILTER_KEYS = ['label', 'assignee', 'due_only', 'rel'];   // same URL params as the server version

  // ------------------------------------------------------------ ui state

  var ui = {
    filters: readFiltersFromUrl(),
    search: '',
    openInfo: new Set(),
    openContext: new Set(),
    showEmptyLabels: pref('showEmptyLabels') === '1',
    editingId: null,
    editDeps: new Set(),
    lastAddedId: null,
    ready: false
  };

  function pref(key, value) {
    try {
      if (arguments.length > 1) {
        if (value === null) localStorage.removeItem('stl:' + key);
        else localStorage.setItem('stl:' + key, value);
      }
      return localStorage.getItem('stl:' + key);
    } catch (e) { return null; }
  }

  // ------------------------------------------------------------ dom helper

  function h(tag, props) {
    var el = document.createElement(tag);
    if (props) Object.keys(props).forEach(function (k) {
      var v = props[k];
      if (v == null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else if (k === 'dataset') Object.keys(v).forEach(function (d) { el.dataset[d] = v[d]; });
      else if (k === 'style') Object.keys(v).forEach(function (s) { el.style.setProperty(s, v[s]); });
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    });
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }
  function append(el, child) {
    if (child == null || child === false) return;
    if (Array.isArray(child)) child.forEach(function (c) { append(el, c); });
    else el.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }

  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function fmtDay(iso) { var d = new Date(iso); return MONTHS[d.getMonth()] + ' ' + pad(d.getDate()); }
  function fmtDate(iso) { var d = new Date(iso); return fmtDay(iso) + ', ' + d.getFullYear(); }
  function initial(name) { return Array.from(name)[0].toUpperCase(); }

  function avatar(name, small) {
    return h('span', { class: 'avatar' + (small ? ' small' : ''), style: { 'background-color': U.assigneeColor(name) }, 'aria-hidden': 'true' }, initial(name));
  }

  function vibrate() { if (coarse && navigator.vibrate) try { navigator.vibrate(10); } catch (e) { /* ignore */ } }

  // ------------------------------------------------------------ filters & url

  function readFiltersFromUrl() {
    var p = new URLSearchParams(location.search), f = {};
    FILTER_KEYS.forEach(function (k) { if (p.get(k)) f[k] = p.get(k); });
    return f;
  }

  /** Mirrors the current filters into the address bar (bookmarkable, survives reload). */
  function syncUrl() {
    var p = new URLSearchParams();
    FILTER_KEYS.forEach(function (k) { if (ui.filters[k]) p.set(k, ui.filters[k]); });
    var qs = p.toString();
    history.replaceState(history.state, '', location.pathname + (qs ? '?' + qs : ''));
  }

  function setFilter(key, value) {
    if (value) ui.filters[key] = value; else delete ui.filters[key];
    syncUrl();
    render();
  }

  function clearFilters() {
    ui.filters = {};
    syncUrl();
    render();
  }

  var REL_NAMES = { requires: 'Requires', blocks: 'Blocking' };

  function activeFilterChips() {
    var f = ui.filters, chips = [];
    if (f.label) chips.push(['label', 'Label: ' + f.label]);
    if (f.assignee) chips.push(['assignee', 'Person: ' + f.assignee]);
    if (f.due_only) chips.push(['due_only', 'Due only']);
    if (f.rel) chips.push(['rel', REL_NAMES[f.rel] || f.rel]);
    return chips;
  }

  // ------------------------------------------------------------ rendering

  function render() {
    var side = Store.sidebar();
    var v = Store.view(ui.filters);

    $('active-count').textContent = side.totalActive ? '(' + side.totalActive + ')' : '';

    // Filter badge + chips under search
    var chips = activeFilterChips();
    $('filter-badge').hidden = !chips.length;
    $('filter-badge').textContent = chips.length;
    var row = $('active-filters');
    row.replaceChildren.apply(row, chips.map(function (c) {
      return h('button', { type: 'button', class: 'active-chip', 'aria-label': 'Remove filter ' + c[1], onclick: function () { setFilter(c[0], null); } },
        c[1], h('span', { class: 'x', 'aria-hidden': 'true' }, '×'));
    }));
    row.hidden = !chips.length;

    // Task list
    var list = $('task-list');
    var nodes = v.active.map(function (t) { return card(t, v.maps); });
    if (v.active.length && v.done.length) nodes.push(h('div', { class: 'list-divider', role: 'separator' }, 'Completed (' + v.done.length + ')'));
    v.done.forEach(function (t) { nodes.push(card(t, v.maps)); });
    list.replaceChildren.apply(list, nodes);
    ui.lastAddedId = null;

    applySearch();
    if ($('filter-sheet').open) renderFilterSheet();
    updateMenuDot();
  }

  function card(t, maps) {
    var done = !!t.completed_at;
    var classes = 'task-card border-' + U.dueColor(t) + (done ? ' completed' : '') + (t.id === ui.lastAddedId ? ' just-added' : '');

    var meta = h('div', { class: 'task-meta' },
      h('span', { class: 'task-id' }, '#' + t.id),
      h('button', { type: 'button', class: 'info-toggle', 'aria-label': 'Task details', 'aria-expanded': String(ui.openInfo.has(t.id)), onclick: function () { toggleSet(ui.openInfo, t.id); } }, 'ⓘ'),
      depSpan('Requires:', maps.requiresMap.get(t.id)),
      depSpan('Blocks:', maps.blocksMap.get(t.id)),
      t.labels.map(function (l) {
        return h('button', { type: 'button', class: 'label-chip chip-' + U.labelColor(l), 'aria-label': 'Filter by label ' + l, onclick: function () { setFilter('label', l); window.scrollTo({ top: 0, behavior: 'smooth' }); } }, l);
      }),
      done ? h('span', null, '• Done: ' + fmtDay(t.completed_at))
           : (U.timeDisplay(t) ? h('span', null, '• ' + U.timeDisplay(t)) : null)
    );

    var info = ui.openInfo.has(t.id) ? h('div', { class: 'task-info' },
      'Created: ' + fmtDate(t.created_at), h('br'),
      'Updated: ' + (t.updated_at ? fmtDate(t.updated_at) : 'N/A'), h('br'),
      'Due: ' + (t.due_date || 'N/A'), h('br'),
      'Assignee: ' + (t.assignee || 'Unassigned')) : null;

    var context = null;
    if (t.context) {
      var open = ui.openContext.has(t.id);
      context = [
        h('button', { type: 'button', class: 'context-toggle', 'aria-expanded': String(open), onclick: function () { toggleSet(ui.openContext, t.id); } }, (open ? '▲' : '▼') + ' Details 📝'),
        open ? h('div', { class: 'task-context' }, contextNodes(t.context)) : null
      ];
    }

    return h('div', { class: classes, dataset: { id: t.id } },
      h('div', { class: 'drag-handle', 'aria-hidden': 'true', title: 'Drag to reorder' }, '⋮⋮'),
      h('div', { class: 'left-actions-column' },
        h('button', { type: 'button', class: 'toggle-btn', 'aria-label': done ? 'Mark as not done' : 'Mark as done', onclick: function () { onToggle(t.id); } },
          h('span', { class: 'box' }, '✓')),
        done ? null : h('button', { type: 'button', class: 'promote-btn', title: 'Move to top', 'aria-label': 'Move to top', onclick: function () { onPromote(t.id); } }, '▲')
      ),
      h('div', { class: 'task-content' },
        h('div', { class: 'task-text', onclick: function () { openEdit(t.id); } }, t.content),
        meta, info, context,
        t.completion_note ? h('div', { class: 'completion-note' }, '“' + t.completion_note + '”') : null
      ),
      h('div', { class: 'right-actions-column' },
        t.assignee ? h('span', { class: 'avatar', title: t.assignee, style: { 'background-color': U.assigneeColor(t.assignee) } }, initial(t.assignee)) : h('span'),
        h('button', { type: 'button', class: 'edit-btn', 'aria-label': 'Edit task', onclick: function () { openEdit(t.id); } }, '✎')
      )
    );
  }

  /** "Requires: #2, #5" with the same strike-through rules as the server version. */
  function depSpan(label, tasks) {
    if (!tasks || !tasks.length) return null;
    var allDone = tasks.every(function (x) { return x.completed_at; });
    var parts = [];
    tasks.forEach(function (x, i) {
      if (i) parts.push(', ');
      var cls = allDone ? 'dep-link strike-high' : (x.completed_at ? 'dep-link diag-slash' : 'dep-link');
      parts.push(h('button', { type: 'button', class: cls, 'aria-label': 'Show task ' + x.id, onclick: function () { showTask(x.id); } }, '#' + x.id));
    });
    return h('span', { class: allDone ? 'dep-done' : 'dep-active' }, '• ', h('span', { class: allDone ? 'strike-high' : null }, label), ' ', parts);
  }

  /** Details text with ```code blocks``` turned into <pre><code>. */
  function contextNodes(text) {
    var out = [], re = /```([\s\S]*?)```/g, last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) out.push(text.slice(last, m.index));
      out.push(h('pre', null, h('code', null, m[1])));
      last = re.lastIndex;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }

  function toggleSet(set, id) {
    if (set.has(id)) set.delete(id); else set.add(id);
    render();
  }

  function showTask(id) {
    clearFilters();
    setSearch('#' + id);
    var el = document.querySelector('.task-card[data-id="' + id + '"]');
    if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); flash(el); }
  }

  function flash(el) {
    el.classList.add('highlight-jump');
    setTimeout(function () { el.classList.remove('highlight-jump'); }, 1500);
  }

  // ------------------------------------------------------------ search
  // "#12" matches task IDs starting with 12; otherwise any word may match
  // the ID, title or details (OR search), same as the server version.

  function setSearch(value) {
    $('task-search').value = value;
    ui.search = value;
    $('clear-search').hidden = !value;
    applySearch();
  }

  function applySearch() {
    var term = ui.search.toLowerCase().trim();
    var words = term.startsWith('#') ? null : term.split(/\s+/).filter(Boolean);
    var shown = 0, total = 0;
    document.querySelectorAll('#task-list .task-card').forEach(function (el) {
      total++;
      var t = Store.get(el.dataset.id);
      var match = true;
      if (t && term) {
        var id = String(t.id);
        if (words === null) {
          var q = term.slice(1).trim();
          match = !q || id.startsWith(q);
        } else {
          var title = t.content.toLowerCase(), ctx = (t.context || '').toLowerCase();
          match = words.some(function (w) { return id.indexOf(w) !== -1 || title.indexOf(w) !== -1 || ctx.indexOf(w) !== -1; });
        }
      }
      el.hidden = !match;
      if (match) shown++;
    });
    var divider = document.querySelector('#task-list .list-divider');
    if (divider) divider.hidden = !!term;
    renderEmptyState(total, shown);
  }

  function renderEmptyState(total, shown) {
    var box = $('empty-state'), hasTasks = Store.all().length > 0;
    var msg = null;
    if (!hasTasks) {
      msg = [h('strong', null, 'No tasks yet'), 'Add one above. Everything is saved on this device and works offline.'];
    } else if (!total && Object.keys(ui.filters).length) {
      msg = [h('strong', null, 'Nothing matches these filters'), h('button', { type: 'button', class: 'action-chip sugg', onclick: clearFilters }, 'Clear filters')];
    } else if (total && !shown) {
      msg = [h('strong', null, 'No tasks match “' + ui.search.trim() + '”'), h('button', { type: 'button', class: 'sugg', onclick: function () { setSearch(''); } }, 'Clear search')];
    }
    box.hidden = !msg;
    if (msg) box.replaceChildren.apply(box, msg);
  }

  // ------------------------------------------------------------ actions

  function saveFailed(err) {
    console.error(err);
    showToast("Couldn't save. Your browser may be out of storage space.");
  }

  function onToggle(id) {
    var wasDone = !!(Store.get(id) || {}).completed_at;
    vibrate();
    Store.toggle(id).then(function (r) {
      if (r && !wasDone) showToast('Task #' + id + ' completed', 'Undo', function () { Store.restore(r.undo).catch(saveFailed); });
    }, saveFailed);
  }

  function onPromote(id) {
    Store.promote(id).catch(saveFailed);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function requestPersistence() {
    if (!navigator.storage || !navigator.storage.persist || pref('askedPersist')) return;
    pref('askedPersist', '1');
    navigator.storage.persisted().then(function (p) { if (!p) return navigator.storage.persist(); }).catch(function () {});
  }

  // ------------------------------------------------------------ chip input (labels)

  function ChipField(container, opts) {
    var values = [];
    var chipsWrap = h('span', { class: 'chips' });
    var input = h('input', { type: 'text', class: 'chip-input', placeholder: opts.placeholder, autocomplete: 'off', autocapitalize: 'words', enterkeyhint: opts.enterHint || 'enter', 'aria-label': opts.placeholder, maxlength: '50' });
    var sugg = h('div', { class: 'label-suggestions' });
    container.replaceChildren(chipsWrap, input, sugg);
    container.addEventListener('click', function (e) { if (e.target === container || e.target === chipsWrap) input.focus(); });

    function commit(text) {
      var added = false;
      String(text).split(',').forEach(function (part) {
        var name = U.cleanLabel(part);
        if (name && !values.some(function (v) { return v.toLowerCase() === name.toLowerCase(); })) { values.push(name); added = true; }
      });
      return added;
    }
    function commitInput() {
      if (!input.value.trim()) { input.value = ''; return false; }
      commit(input.value); input.value = ''; draw(); return true;
    }
    function draw() {
      chipsWrap.replaceChildren.apply(chipsWrap, values.map(function (v, i) {
        return h('span', { class: 'chip' }, v,
          h('button', { type: 'button', class: 'chip-remove', 'aria-label': 'Remove label ' + v,
            onclick: function (e) { e.stopPropagation(); values.splice(i, 1); draw(); } }, '×'));
      }));
      drawSuggestions();
    }
    function drawSuggestions() {
      var focused = container.contains(document.activeElement);
      if (opts.compact && !focused) { sugg.replaceChildren(); return; }
      var q = input.value.trim().toLowerCase();
      var taken = new Set(values.map(function (v) { return v.toLowerCase(); }));
      var names = opts.suggestions().filter(function (n) {
        return !taken.has(n.toLowerCase()) && (!q || n.toLowerCase().indexOf(q) !== -1);
      }).slice(0, 12);
      sugg.replaceChildren.apply(sugg, names.map(function (n) {
        return h('button', { type: 'button', class: 'sugg', tabindex: '-1',
          onpointerdown: function (e) { e.preventDefault(); },       // keep the keyboard open
          onclick: function () { commit(n); input.value = ''; draw(); input.focus(); } }, '+ ' + n);
      }));
    }

    input.addEventListener('keydown', function (e) {
      if ((e.key === 'Enter' || e.key === ',' || e.key === 'Tab') && input.value.trim()) {
        if (e.key !== 'Tab' || input.value.trim()) e.preventDefault();
        commitInput();
      } else if (e.key === 'Backspace' && !input.value && values.length) {
        values.pop(); draw();
      } else if (e.key === 'Enter' && opts.onEnterEmpty) {
        e.preventDefault(); opts.onEnterEmpty();
      }
    });
    // Android keyboards often send "," without a usable keydown.
    input.addEventListener('input', function () {
      if (input.value.indexOf(',') !== -1) commitInput(); else drawSuggestions();
    });
    container.addEventListener('focusin', drawSuggestions);
    container.addEventListener('focusout', function () {
      setTimeout(function () {
        if (!container.contains(document.activeElement)) { commitInput(); drawSuggestions(); }
      }, 0);
    });

    return {
      get: function () { commitInput(); return values.slice(); },
      set: function (list) { values = U.cleanLabels(list); input.value = ''; draw(); },
      focus: function () { input.focus(); },
      input: input
    };
  }

  function labelSuggestions() { return Store.sidebar().labels.map(function (l) { return l.name; }); }

  // ------------------------------------------------------------ add form

  var addLabels = ChipField($('add-labels'), {
    placeholder: 'Add labels...', compact: true, suggestions: labelSuggestions, enterHint: 'done',
    onEnterEmpty: function () { $('add-form').requestSubmit(); }
  });

  $('add-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var input = $('add-content');
    var content = input.value.trim();
    if (!content) { input.focus(); return; }
    if (!ui.ready) return;   // storage still opening (first instant after launch); keep the text
    var labels = addLabels.get();
    ui.lastAddedId = Store.meta().next_id;   // the id the new task will get, so it animates in
    Store.add(content, labels).then(function (task) {
      if (task) requestPersistence();
    }, saveFailed);
    input.value = '';
    addLabels.set([]);
    if (ui.search) setSearch('');
    input.focus();
  });

  Store.onChange(function (source) {
    render();
    if (source === 'remote' && ui.editingId && !Store.get(ui.editingId)) closeSheet($('edit-sheet'));
  });

  // ------------------------------------------------------------ sheets & back button

  function openSheet(dlg) {
    if (dlg.open) return;
    document.querySelectorAll('dialog[open]').forEach(function (d) { if (d !== dlg) d.close(); });
    dlg.showModal();
    history.pushState({ sheet: dlg.id }, '');
  }

  function closeSheet(dlg) {
    if (!dlg.open) return;
    if (history.state && history.state.sheet === dlg.id) history.back();   // popstate closes it
    else dlg.close();
  }

  window.addEventListener('popstate', function () {
    var keep = history.state && history.state.sheet;
    document.querySelectorAll('dialog[open]').forEach(function (d) { if (d.id !== keep) d.close(); });
    // Going back restores the URL from before the sheet opened; filters may have changed since.
    syncUrl();
  });

  document.querySelectorAll('dialog.sheet').forEach(function (dlg) {
    dlg.addEventListener('cancel', function (e) { e.preventDefault(); closeSheet(dlg); });   // Esc
    dlg.addEventListener('click', function (e) { if (e.target === dlg) closeSheet(dlg); });  // backdrop
    dlg.querySelectorAll('[data-close]').forEach(function (b) { b.addEventListener('click', function () { closeSheet(dlg); }); });
    dlg.addEventListener('close', function () { if (dlg.id === 'edit-sheet') ui.editingId = null; });
  });

  // ------------------------------------------------------------ edit sheet

  var editLabels = ChipField($('edit-labels'), { placeholder: 'Add labels...', suggestions: labelSuggestions });

  function autosize(el) { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px'; }
  $('edit-content').addEventListener('input', function () { autosize(this); });
  $('edit-content').addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('edit-form').requestSubmit(); }   // Enter saves
  });

  function openEdit(id) {
    var t = Store.get(id);
    if (!t) return;
    ui.editingId = t.id;
    ui.editDeps = new Set(t.requires.filter(function (r) { return Store.get(r); }));
    $('edit-id').textContent = '#' + t.id;
    $('edit-error').hidden = true;
    $('edit-content').value = t.content;
    $('edit-context').value = t.context || '';
    editLabels.set(t.labels);
    $('edit-assignee').value = t.assignee || '';
    $('edit-due').value = t.due_date || '';
    $('dep-search').value = '';
    $('completion-group').hidden = !t.completed_at;
    $('edit-note').value = t.completion_note || '';
    renderAssigneeSuggestions();
    renderDeps();
    openSheet($('edit-sheet'));
    $('edit-sheet').querySelector('.sheet-body').scrollTop = 0;
    autosize($('edit-content'));
    if (!coarse) $('edit-content').focus();
  }

  function renderAssigneeSuggestions() {
    var current = $('edit-assignee').value.trim().toLowerCase();
    var names = Store.sidebar().assignees.map(function (a) { return a.name; })
      .filter(function (n) { return n.toLowerCase() !== current; }).slice(0, 8);
    var box = $('assignee-suggestions');
    box.replaceChildren.apply(box, names.map(function (n) {
      return h('button', { type: 'button', class: 'sugg', onclick: function () { $('edit-assignee').value = n; renderAssigneeSuggestions(); } },
        avatar(n, true), n);
    }));
  }
  $('edit-assignee').addEventListener('input', renderAssigneeSuggestions);

  document.querySelectorAll('[data-due]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (b.dataset.due === '') { $('edit-due').value = ''; return; }
      var d = new Date(); d.setDate(d.getDate() + Number(b.dataset.due));
      $('edit-due').value = U.localDateString(d);
    });
  });

  /** Prerequisite checklist: leaves out this task and anything that already depends on it. */
  function renderDeps() {
    var id = ui.editingId;
    var excluded = Store.dependentsOf(id); excluded.add(id);
    var q = $('dep-search').value.trim().toLowerCase().replace(/^#/, '');
    var options = Store.all().filter(function (t) { return !excluded.has(t.id); })
      .sort(function (a, b) { return a.id - b.id; });
    var shown = options.filter(function (t) {
      return !q || String(t.id).startsWith(q) || t.content.toLowerCase().indexOf(q) !== -1;
    });
    var box = $('dep-list');
    if (!shown.length) {
      box.replaceChildren(h('div', { class: 'dep-empty' }, options.length ? 'No tasks match.' : 'No other tasks yet.'));
    } else {
      box.replaceChildren.apply(box, shown.map(function (t) {
        var cb = h('input', { type: 'checkbox', checked: ui.editDeps.has(t.id), onchange: function () {
          if (cb.checked) ui.editDeps.add(t.id); else ui.editDeps.delete(t.id);
          updateDepCount();
        } });
        return h('label', { class: 'dep-row' + (t.completed_at ? ' done' : '') }, cb,
          h('span', { class: 'dep-id' }, '#' + t.id), h('span', { class: 'dep-text' }, t.content));
      }));
    }
    updateDepCount();
  }
  function updateDepCount() {
    $('dep-count').textContent = ui.editDeps.size ? '· ' + ui.editDeps.size + ' selected' : '';
  }
  $('dep-search').addEventListener('input', renderDeps);
  $('dep-search').addEventListener('keydown', function (e) { if (e.key === 'Enter') e.preventDefault(); });

  $('edit-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var id = ui.editingId;
    Store.update(id, {
      content: $('edit-content').value,
      context: $('edit-context').value,
      labels: editLabels.get(),
      assignee: $('edit-assignee').value,
      due_date: $('edit-due').value,
      requires: Array.from(ui.editDeps),
      completion_note: $('edit-note').value
    }).then(function (r) {
      if (r.errors) {
        var box = $('edit-error');
        box.textContent = r.errors.join(' ');
        box.hidden = false;
        $('edit-sheet').querySelector('.sheet-body').scrollTop = 0;
        return;
      }
      closeSheet($('edit-sheet'));
    }, saveFailed);
  });

  $('edit-delete').addEventListener('click', function () {
    var id = ui.editingId;
    closeSheet($('edit-sheet'));
    Store.remove(id).then(function (r) {
      if (r) showToast('Task #' + id + ' deleted', 'Undo', function () { Store.restore(r.undo).catch(saveFailed); });
    }, saveFailed);
  });

  // ------------------------------------------------------------ filter sheet

  function pill(text, active, onclick, extraClass, lead) {
    return h('button', { type: 'button', class: 'filter-pill' + (active ? ' active' : '') + (extraClass ? ' ' + extraClass : ''), 'aria-pressed': String(!!active), onclick: onclick }, lead || null, text);
  }

  function renderFilterSheet() {
    var side = Store.sidebar(), f = ui.filters;

    $('label-section').hidden = !side.labels.length;
    $('label-pills').replaceChildren.apply($('label-pills'), [
      pill('All (' + side.totalActive + ')', !f.label, function () { setFilter('label', null); })
    ].concat(side.labels.map(function (l) {
      return pill(l.name + ' (' + l.count + ')', f.label === l.name, function () { setFilter('label', f.label === l.name ? null : l.name); },
        l.count === 0 && f.label !== l.name ? 'empty-label' : null);
    })));
    $('filter-sheet').classList.toggle('show-empty-labels', ui.showEmptyLabels);
    var emptyCount = side.labels.filter(function (l) { return l.count === 0; }).length;
    $('toggle-empty-labels').hidden = !emptyCount;
    $('toggle-empty-labels').textContent = (ui.showEmptyLabels ? 'Hide' : 'Show') + ' empty labels (' + emptyCount + ')';

    var people = [pill('Anyone', !f.assignee, function () { setFilter('assignee', null); })];
    side.assignees.forEach(function (a) {
      people.push(pill(a.name + ' (' + a.count + ')', f.assignee === a.name, function () { setFilter('assignee', f.assignee === a.name ? null : a.name); }, null, avatar(a.name, true)));
    });
    if (side.unassignedCount > 0 || f.assignee === 'Unassigned') {
      people.push(pill('Unassigned (' + side.unassignedCount + ')', f.assignee === 'Unassigned', function () { setFilter('assignee', f.assignee === 'Unassigned' ? null : 'Unassigned'); },
        null, h('span', { class: 'avatar small unassigned', 'aria-hidden': 'true' }, '?')));
    }
    $('person-section').hidden = !side.assignees.length && !side.unassignedCount && !f.assignee;
    $('person-pills').replaceChildren.apply($('person-pills'), people);

    $('due-pills').replaceChildren(
      pill('All', !f.due_only, function () { setFilter('due_only', null); }),
      pill('Due only (' + side.dueCount + ')', f.due_only === '1', function () { setFilter('due_only', f.due_only ? null : '1'); })
    );
    $('rel-pills').replaceChildren(
      pill('All', !f.rel, function () { setFilter('rel', null); }),
      pill('Requires', f.rel === 'requires', function () { setFilter('rel', f.rel === 'requires' ? null : 'requires'); }),
      pill('Blocking', f.rel === 'blocks', function () { setFilter('rel', f.rel === 'blocks' ? null : 'blocks'); })
    );
  }

  $('filter-btn').addEventListener('click', function () { renderFilterSheet(); openSheet($('filter-sheet')); });
  $('clear-filters').addEventListener('click', clearFilters);
  $('toggle-empty-labels').addEventListener('click', function () {
    ui.showEmptyLabels = !ui.showEmptyLabels;
    pref('showEmptyLabels', ui.showEmptyLabels ? '1' : null);
    renderFilterSheet();
  });

  // ------------------------------------------------------------ menu

  function daysAgo(iso) {
    var d = Math.floor((Date.now() - new Date(iso)) / 86400000);
    return d <= 0 ? 'today' : d === 1 ? 'yesterday' : d + ' days ago';
  }

  function backupOverdue() {
    var tasks = Store.all();
    if (!tasks.length) return false;
    var last = Store.meta().last_export;
    if (last) return Date.now() - new Date(last) > 30 * 86400000;
    var oldest = tasks.reduce(function (m, t) { return t.created_at < m ? t.created_at : m; }, tasks[0].created_at);
    return Date.now() - new Date(oldest) > 7 * 86400000;
  }

  function updateMenuDot() { $('menu-dot').hidden = !backupOverdue(); }

  function renderMenu() {
    var last = Store.meta().last_export;
    $('last-export').textContent = last ? 'Last backup: ' + daysAgo(last) : 'No backup yet';
    var info = $('storage-info');
    var kind = { indexeddb: 'this device (IndexedDB)', localstorage: 'this device (localStorage)', memory: 'memory only — not saved' }[Store.kind()];
    var n = Store.all().length;
    var lines = [n + ' task' + (n === 1 ? '' : 's') + ' saved on ' + kind + '.'];
    info.textContent = lines.join(' ');
    $('menu-persist').hidden = true;
    if (navigator.storage && navigator.storage.persisted) {
      Promise.all([navigator.storage.persisted(), navigator.storage.estimate ? navigator.storage.estimate() : null]).then(function (r) {
        var persisted = r[0], est = r[1];
        if (est && est.usage != null) lines.push('Using ' + Math.max(1, Math.round(est.usage / 1024)) + ' KB.');
        lines.push(persisted ? 'The browser won’t clear this storage on its own.' : 'The browser may clear this storage if the device runs low on space.');
        if (isIosSafariTab()) lines.push('On iPhone/iPad, add this app to your Home Screen (Share → Add to Home Screen) so Safari keeps your tasks.');
        lines.push('Tasks aren’t shared between devices or browsers; use Export and Import to move them.');
        info.textContent = lines.join(' ');
        $('menu-persist').hidden = persisted || !navigator.storage.persist;
      }).catch(function () {});
    }
  }

  $('menu-btn').addEventListener('click', function () { renderMenu(); openSheet($('menu-sheet')); });

  $('menu-jump').addEventListener('click', function () {
    closeSheet($('menu-sheet'));
    var cards = Array.from(document.querySelectorAll('#task-list .task-card:not(.completed)')).filter(function (el) { return !el.hidden; });
    if (!cards.length) { showToast('No unfinished tasks'); return; }
    var last = cards[cards.length - 1];
    setTimeout(function () { last.scrollIntoView({ behavior: 'smooth', block: 'center' }); flash(last); }, 50);
  });

  $('menu-persist').addEventListener('click', function () {
    navigator.storage.persist().then(function (ok) {
      showToast(ok ? 'Storage is now protected' : 'The browser declined. Installing the app usually helps.');
      renderMenu();
    });
  });

  // Export: share sheet on phones (save to Files/Drive), download elsewhere.
  $('menu-export').addEventListener('click', function () {
    var data = JSON.stringify(Store.exportData(), null, 2);
    var name = 'tasks-backup-' + U.localDateString(new Date()) + '.json';
    var file;
    try { file = new File([data], name, { type: 'application/json' }); } catch (e) { file = null; }
    var done = function () { Store.markExported().then(function () { renderMenu(); updateMenuDot(); }); showToast('Backup saved'); };

    if (coarse && file && navigator.canShare && navigator.canShare({ files: [file] })) {
      navigator.share({ files: [file], title: 'Tasks backup' }).then(done, function (err) {
        if (err && err.name !== 'AbortError') download(data, name, done);
      });
    } else {
      download(data, name, done);
    }
  });

  function download(text, name, then) {
    var url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
    var a = h('a', { href: url, download: name });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 10000);
    then();
  }

  $('menu-import').addEventListener('click', function () { $('import-file').click(); });
  $('import-file').addEventListener('change', function () {
    var file = this.files && this.files[0];
    this.value = '';
    if (!file) return;
    closeSheet($('menu-sheet'));
    showToast('Reading ' + file.name + '…');
    Importer.read(file).then(function (parsed) {
      var current = Store.all().length;
      var what = parsed.tasks.length + ' task' + (parsed.tasks.length === 1 ? '' : 's');
      if (current && !confirm('Replace the ' + current + ' task' + (current === 1 ? '' : 's') + ' on this device with ' + what + ' from ' + file.name + '?')) {
        hideToast(); return;
      }
      return Store.replaceAll(parsed).then(function (r) {
        clearFilters(); setSearch('');
        var note = parsed.skipped ? ' (' + parsed.skipped + ' unreadable skipped)' : '';
        showToast('Imported ' + what + note, current ? 'Undo' : null, current ? function () { Store.undoReplace(r.undo).catch(saveFailed); } : null);
      });
    }).catch(function (err) {
      console.warn('Import failed:', err);
      showToast(err && err.message ? err.message : "Couldn't read that file.");
    });
  });

  // Install (Chrome/Edge/Android). iOS installs from the Share menu.
  var installEvent = null;
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault(); installEvent = e; $('menu-install').hidden = false;
  });
  $('menu-install').addEventListener('click', function () {
    if (!installEvent) return;
    installEvent.prompt();
    installEvent.userChoice.finally(function () { installEvent = null; $('menu-install').hidden = true; });
    closeSheet($('menu-sheet'));
  });
  window.addEventListener('appinstalled', function () { $('menu-install').hidden = true; });

  function isStandalone() {
    return window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  }
  function isIosSafariTab() {
    var ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    return ios && !isStandalone();
  }

  // ------------------------------------------------------------ toast

  var toastTimer = null;
  function showToast(text, actionText, action) {
    clearTimeout(toastTimer);
    $('toast-text').textContent = text;
    var btn = $('toast-action');
    btn.hidden = !actionText;
    btn.textContent = actionText || '';
    btn.onclick = function () { hideToast(); if (action) action(); };
    $('toast').hidden = false;
    toastTimer = setTimeout(hideToast, actionText ? 6000 : 3000);
  }
  function hideToast() { clearTimeout(toastTimer); $('toast').hidden = true; }

  // ------------------------------------------------------------ banner

  function renderBanner() {
    var b = $('banner'), msg = null;
    if (Store.kind() === 'memory') {
      msg = [h('strong', null, 'Tasks won’t be saved. '), 'This browser is blocking storage (private mode or site data turned off).'];
    } else if (isIosSafariTab() && Store.all().length && !pref('dismissIosHint')) {
      msg = ['On iPhone, add this app to your Home Screen (Share → Add to Home Screen) so Safari doesn’t clear your tasks after a week without visits. ',
        h('button', { type: 'button', onclick: function () { pref('dismissIosHint', '1'); renderBanner(); } }, 'Got it')];
    }
    b.hidden = !msg;
    if (msg) b.replaceChildren.apply(b, msg);
  }

  // ------------------------------------------------------------ search box

  $('task-search').addEventListener('input', function () { setSearch(this.value); });
  $('clear-search').addEventListener('click', function () { setSearch(''); $('task-search').focus(); });

  // ------------------------------------------------------------ drag to reorder

  function setupSortable() {
    if (!window.Sortable) return;   // the list still works; only dragging is unavailable
    Sortable.create($('task-list'), {
      handle: '.drag-handle',
      draggable: '.task-card',
      filter: '.completed',
      animation: 150,
      ghostClass: 'sortable-ghost',
      chosenClass: 'sortable-chosen',
      forceFallback: false,
      fallbackTolerance: 4,
      scrollSensitivity: 80,
      onMove: function (evt) { return !evt.related.classList.contains('completed'); },
      onEnd: function (evt) {
        if (evt.oldIndex === evt.newIndex) return;
        var ids = Array.from(document.querySelectorAll('#task-list .task-card:not(.completed)')).map(function (el) { return el.dataset.id; });
        vibrate();
        Store.reorder(ids).catch(function (err) { saveFailed(err); render(); });
      }
    });
  }

  // ------------------------------------------------------------ service worker (offline + updates)

  function setupServiceWorker() {
    if (!('serviceWorker' in navigator) || location.protocol === 'file:') return;
    // Reload only when the user tapped "Reload" on an update. (On the very first
    // visit the worker also takes control; reloading then would wipe what's being typed.)
    var updateRequested = false;
    navigator.serviceWorker.addEventListener('controllerchange', function () {
      if (!updateRequested) return;
      updateRequested = false;
      location.reload();
    });
    navigator.serviceWorker.register('sw.js').then(function (reg) {
      function offer(worker) {
        showToast('A new version is ready', 'Reload', function () { updateRequested = true; worker.postMessage('skipWaiting'); });
      }
      if (reg.waiting && navigator.serviceWorker.controller) offer(reg.waiting);
      reg.addEventListener('updatefound', function () {
        var w = reg.installing;
        if (!w) return;
        w.addEventListener('statechange', function () {
          if (w.state === 'installed' && navigator.serviceWorker.controller) offer(w);
        });
      });
      document.addEventListener('visibilitychange', function () { if (!document.hidden) reg.update().catch(function () {}); });
    }).catch(function (err) { console.warn('Service worker not registered:', err); });
  }

  // Due-date colors depend on today's date: refresh when the app comes back.
  document.addEventListener('visibilitychange', function () { if (!document.hidden) render(); });

  // ------------------------------------------------------------ start

  Store.init().then(function () {
    ui.ready = true;
    document.body.dataset.ready = '1';
    render();
    renderBanner();
    setupSortable();
    setupServiceWorker();
    history.replaceState(null, '', location.href);   // a reload never reopens a sheet
  }, function (err) {
    console.error(err);
    $('banner').textContent = 'The app couldn’t start: ' + (err && err.message ? err.message : err);
    $('banner').hidden = false;
  });
})();

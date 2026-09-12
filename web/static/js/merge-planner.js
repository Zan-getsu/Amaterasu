(() => {
  const shell = document.querySelector('.merge-shell');
  if (!shell) return;

  const planId = shell.dataset.planId;
  const params = new URLSearchParams(window.location.search);
  const authPanel = document.getElementById('authPanel');
  const planner = document.getElementById('planner');
  const errorPanel = document.getElementById('errorPanel');
  const errorMessage = document.getElementById('errorMessage');
  const list = document.getElementById('mergeList');
  const emptyState = document.getElementById('emptyState');
  const state = document.getElementById('planState');
  const notice = document.getElementById('planNotice');
  const saveState = document.getElementById('saveState');
  const pinInput = document.getElementById('pinInput');
  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

  let pin = params.get('pin') || '';
  let current = null;
  let dragging = null;
  let saving = false;
  let pendingSave = false;
  let retryTimer = null;

  const apiUrl = () => `/api/merge-plan/${encodeURIComponent(planId)}?pin=${encodeURIComponent(pin)}`;

  function showError(message) {
    planner.hidden = true;
    authPanel.hidden = true;
    errorPanel.hidden = false;
    errorMessage.textContent = message;
  }

  function showAuth() {
    planner.hidden = true;
    errorPanel.hidden = true;
    authPanel.hidden = false;
    pinInput.focus();
  }

  function statusLabel(value) {
    return ({
      collecting: 'Collecting files',
      downloading: 'Downloading',
      merging: 'Merging',
      completed: 'Completed',
      failed: 'Stopped',
      cancelled: 'Cancelled',
    })[value] || value || 'Preparing';
  }

  function episodeKey(name) {
    const text = String(name || '');
    let match = text.match(/(?:^|\D)s(\d{1,3})[ ._-]*e(\d{1,4})(?:\D|$)/i);
    if (match) return [Number(match[1]), Number(match[2]), text];
    match = text.match(/(?:^|\D)(\d{1,3})x(\d{1,4})(?:\D|$)/i);
    if (match) return [Number(match[1]), Number(match[2]), text];
    match = text.match(/(?:episode|ep)[ ._-]*(\d{1,4})(?:\D|$)/i);
    if (match) return [0, Number(match[1]), text];
    match = text.match(/(?:^|\D)(\d{1,4})(?:\D|$)/);
    return match ? [0, Number(match[1]), text] : [Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER, text];
  }

  function compareEpisode(a, b) {
    const left = episodeKey(a.dataset.name);
    const right = episodeKey(b.dataset.name);
    return left[0] - right[0] || left[1] - right[1] || collator.compare(left[2], right[2]);
  }

  function moveRow(row, direction) {
    if (!row || current?.locked) return;
    const sibling = direction < 0 ? row.previousElementSibling : row.nextElementSibling;
    if (!sibling) return;
    if (direction < 0) list.insertBefore(row, sibling);
    else list.insertBefore(sibling, row);
    saveOrder();
  }

  function rowFor(item) {
    const row = document.createElement('li');
    row.className = 'merge-row';
    row.dataset.id = item.id;
    row.dataset.name = item.name || '';
    row.dataset.originalIndex = item.original_index || 0;
    row.draggable = !current.locked;

    const handle = document.createElement('button');
    handle.className = 'merge-handle';
    handle.type = 'button';
    handle.disabled = current.locked;
    handle.setAttribute('aria-label', `Drag ${item.name}`);
    handle.innerHTML = '<span data-lucide="grip-vertical"></span>';

    const file = document.createElement('div');
    file.className = 'merge-file';
    const title = document.createElement('strong');
    title.textContent = item.name || 'Preparing item';
    const detail = document.createElement('span');
    detail.textContent = item.placeholder ? 'Resolving filename' : item.ready ? 'Ready' : 'Queued';
    file.append(title, detail);

    const actions = document.createElement('div');
    actions.className = 'merge-row-actions';
    for (const [label, icon, direction] of [['Move up', 'chevron-up', -1], ['Move down', 'chevron-down', 1]]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'bs-btn bs-btn--ghost bs-btn--icon';
      button.disabled = current.locked;
      button.setAttribute('aria-label', `${label}: ${item.name}`);
      button.innerHTML = `<span data-lucide="${icon}"></span>`;
      button.addEventListener('click', () => moveRow(row, direction));
      actions.append(button);
    }

    row.append(handle, file, actions);

    row.addEventListener('dragstart', () => {
      dragging = row;
      row.classList.add('is-dragging');
    });
    row.addEventListener('dragend', () => {
      row.classList.remove('is-dragging');
      document.querySelectorAll('.is-drop-target').forEach(el => el.classList.remove('is-drop-target'));
      dragging = null;
      saveOrder();
    });
    row.addEventListener('dragover', event => {
      if (!dragging || dragging === row) return;
      event.preventDefault();
      row.classList.add('is-drop-target');
      const before = event.clientY < row.getBoundingClientRect().top + row.offsetHeight / 2;
      list.insertBefore(dragging, before ? row : row.nextSibling);
    });
    row.addEventListener('dragleave', () => row.classList.remove('is-drop-target'));

    handle.addEventListener('pointerdown', event => {
      if (event.pointerType === 'mouse' || current.locked) return;
      dragging = row;
      handle.setPointerCapture(event.pointerId);
      row.classList.add('is-dragging');
      event.preventDefault();
    });
    handle.addEventListener('pointermove', event => {
      if (!dragging || event.pointerType === 'mouse') return;
      const target = document.elementFromPoint(event.clientX, event.clientY)?.closest('.merge-row');
      if (!target || target === dragging) return;
      const before = event.clientY < target.getBoundingClientRect().top + target.offsetHeight / 2;
      list.insertBefore(dragging, before ? target : target.nextSibling);
    });
    const finishPointerDrag = event => {
      if (!dragging || event.pointerType === 'mouse') return;
      row.classList.remove('is-dragging');
      dragging = null;
      saveOrder();
    };
    handle.addEventListener('pointerup', finishPointerDrag);
    handle.addEventListener('pointercancel', finishPointerDrag);
    return row;
  }

  function render(data) {
    current = data;
    authPanel.hidden = true;
    errorPanel.hidden = true;
    planner.hidden = false;
    document.getElementById('planTitle').textContent = data.title || 'Merged video';
    document.getElementById('readyCount').textContent = data.ready_count;
    document.getElementById('itemCount').textContent = data.items.length;
    state.dataset.state = data.status;
    state.lastElementChild.textContent = statusLabel(data.status);
    list.replaceChildren(...data.items.map(rowFor));
    emptyState.hidden = data.items.length > 0;
    list.hidden = data.items.length === 0;
    notice.dataset.kind = data.locked ? 'locked' : 'active';
    notice.lastElementChild.textContent = data.locked
      ? 'The timeline is locked because merging has started.'
      : 'Downloads continue in the background. If you leave this page, Amaterasu uses the latest saved order.';
    document.querySelectorAll('[data-sort]').forEach(button => { button.disabled = data.locked; });
    if (data.error) showError(data.error);
    if (window.lucide) window.lucide.createIcons();
  }

  async function loadPlan() {
    if (saving || dragging) return;
    try {
      const response = await fetch(apiUrl(), { cache: 'no-store' });
      if (response.status === 403) return showAuth();
      const data = await response.json();
      if (!response.ok) return showError(data.message || 'This merge plan is unavailable.');
      render(data);
    } catch (_) {
      saveState.textContent = 'Reconnecting';
    }
  }

  async function saveOrder() {
    if (!current || current.locked) return;
    if (saving) {
      pendingSave = true;
      return;
    }
    saving = true;
    saveState.textContent = 'Saving…';
    const order = [...list.children].map(row => row.dataset.id);
    try {
      const response = await fetch(apiUrl(), {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order, revision: current.revision }),
      });
      const data = await response.json();
      if (!response.ok) {
        saveState.textContent = 'List updated';
        if (data.plan) render(data.plan);
      } else {
        current = data;
        saveState.textContent = 'Up to date';
      }
    } catch (_) {
      saveState.textContent = 'Retrying';
      pendingSave = true;
      retryTimer = setTimeout(() => {
        retryTimer = null;
        if (pendingSave) {
          pendingSave = false;
          saveOrder();
        }
      }, 1500);
    } finally {
      saving = false;
      if (pendingSave && !retryTimer) {
        pendingSave = false;
        saveOrder();
      }
    }
  }

  document.getElementById('pinForm').addEventListener('submit', event => {
    event.preventDefault();
    pin = pinInput.value.trim();
    if (!/^[A-Za-z0-9_-]{12}$/.test(pin)) return;
    params.set('pin', pin);
    history.replaceState(null, '', `${location.pathname}?${params}`);
    loadPlan();
  });

  document.querySelectorAll('[data-sort]').forEach(button => {
    button.addEventListener('click', () => {
      const rows = [...list.children];
      switch (button.dataset.sort) {
        case 'input': rows.sort((a, b) => Number(a.dataset.originalIndex) - Number(b.dataset.originalIndex)); break;
        case 'filename': rows.sort((a, b) => collator.compare(a.dataset.name, b.dataset.name)); break;
        case 'episode': rows.sort(compareEpisode); break;
        case 'reverse': rows.reverse(); break;
      }
      list.replaceChildren(...rows);
      saveOrder();
    });
  });

  loadPlan();
  setInterval(loadPlan, 3000);
})();

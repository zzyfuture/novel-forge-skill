// web/js/store.js
// 极简前端状态 + 订阅。

const state = {
  project: {},
  chapters: [],
  currentChapter: null,
  currentContract: null,
  currentIssues: [],
  schemes: [],
  domain: { terms: [], stages: [], era: [] },
  llm: null,
  job: null,
};

const listeners = new Set();

export const store = {
  get(key) { return key ? state[key] : state; },
  set(key, value) {
    state[key] = value;
    notify(key);
  },
  update(patch) {
    Object.assign(state, patch);
    notify(null);
  },
  subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};

function notify(key) {
  for (const fn of listeners) {
    try { fn(key, state); } catch (e) { console.error(e); }
  }
}

// Toast
export function toast(message, kind = 'info', ms = 3000) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity 0.2s';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 200);
  }, ms);
}

// ============================================================ 工具函数

export function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

export function fmtDate(s) {
  if (!s) return '—';
  try {
    const d = new Date(s);
    return d.toLocaleString('zh-CN', { hour12: false });
  } catch {
    return s;
  }
}

// ============================================================ Job 进度条

export function showJobBar(initial = {}) {
  let bar = document.getElementById('job-bar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'job-bar';
    bar.className = 'job-bar';
    bar.innerHTML = `
      <span class="job-step"></span>
      <span class="job-msg"></span>
      <div class="job-progress"><div class="job-progress-fill"></div></div>
    `;
    document.body.appendChild(bar);
  }
  bar.classList.remove('hidden');
  updateJobBar(initial);
  return bar;
}

export function updateJobBar(job) {
  const bar = document.getElementById('job-bar');
  if (!bar) return;
  bar.querySelector('.job-step').textContent = job.step || '';
  bar.querySelector('.job-msg').textContent = job.message || '';
  bar.querySelector('.job-progress-fill').style.width = (job.progress || 0) + '%';
}

export function hideJobBar() {
  const bar = document.getElementById('job-bar');
  if (bar) bar.classList.add('hidden');
}

// ============================================================ 状态栏

export function setStatus(text) {
  const el = document.getElementById('status-text');
  if (el) el.textContent = text || '就绪';
}

// ============================================================ Modal

export function confirmDialog(opts) {
  const o = typeof opts === 'string' ? { message: opts } : (opts || {});
  const {
    title = '',
    message = '',
    okText = '确定',
    cancelText = '取消',
    showCancel = true,
    danger = false,
  } = o;

  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal" role="dialog">
        ${title ? `<div class="modal-title">${escapeHtml(title)}</div>` : ''}
        <div class="modal-body">${escapeHtml(message)}</div>
        <div class="modal-actions">
          ${showCancel ? `<button class="btn-ghost" data-modal-cancel>${escapeHtml(cancelText)}</button>` : ''}
          <button class="btn ${danger ? 'btn-danger' : ''}" data-modal-ok autofocus>${escapeHtml(okText)}</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    let done = false;
    function close(result) {
      if (done) return;
      done = true;
      overlay.classList.add('closing');
      setTimeout(() => overlay.remove(), 150);
      resolve(result);
    }

    overlay.querySelector('[data-modal-ok]').onclick = () => close(true);
    if (showCancel) {
      overlay.querySelector('[data-modal-cancel]').onclick = () => close(false);
    }
    overlay.onclick = (e) => { if (e.target === overlay) close(false); };
    const onKey = (e) => {
      if (e.key === 'Escape') { document.removeEventListener('keydown', onKey); close(false); }
      if (e.key === 'Enter') { document.removeEventListener('keydown', onKey); close(true); }
    };
    document.addEventListener('keydown', onKey);

    setTimeout(() => overlay.querySelector('[data-modal-ok]').focus(), 30);
  });
}

export function alertDialog(opts) {
  const o = typeof opts === 'string' ? { message: opts } : (opts || {});
  return confirmDialog({ ...o, showCancel: false, okText: o.okText || '知道了' });
}
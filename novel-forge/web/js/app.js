// web/js/app.js
import { api } from './api.js';
import { store, toast } from './store.js';
import { renderOverview } from './views/overview.js';
import { renderBible } from './views/bible.js';
import { renderOutline } from './views/outline.js';
import { renderStudio } from './views/studio.js';
import { renderContinuity } from './views/continuity.js';
import { renderSettings } from './views/settings.js';

const VIEWS = {
  overview: renderOverview,
  bible: renderBible,
  outline: renderOutline,
  studio: renderStudio,
  continuity: renderContinuity,
  settings: renderSettings,
};

const DEFAULT_VIEW = 'overview';

let currentView = null;

async function route() {
  const hash = (location.hash || '').replace('#', '');
  const [view, arg] = hash.split('/');
  const name = VIEWS[view] ? view : DEFAULT_VIEW;

  // 更新导航高亮
  document.querySelectorAll('.nav-item').forEach((el) => {
    el.classList.toggle('active', el.dataset.view === name);
  });

  // 更新视图
  const main = document.getElementById('main-view');
  if (currentView === name && name !== 'studio') {
    // 同一个非 studio 视图，也可以直接重渲染（简化处理）
  }
  currentView = name;
  main.innerHTML = '<div class="empty">加载中…</div>';
  try {
    await VIEWS[name](main, arg);
  } catch (e) {
    console.error(e);
    main.innerHTML = `<div class="empty">加载失败：${escapeHtml(e.message)}</div>`;
  }
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// 全局 toast 容器
function ensureToastContainer() {
  if (!document.getElementById('toast-container')) {
    const el = document.createElement('div');
    el.id = 'toast-container';
    document.body.appendChild(el);
  }
}

// 顶部状态灯
async function refreshLlmStatus() {
  const dot = document.getElementById('llm-status');
  try {
    const data = await api.llm.options('text');
    if (data.source === 'yaml') {
      dot.className = 'status-dot ok';
      dot.title = `LLM：${data.hint}`;
    } else if (data.source === 'env') {
      dot.className = 'status-dot warn';
      dot.title = `LLM：${data.hint}`;
    } else {
      dot.className = 'status-dot error';
      dot.title = `LLM：${data.hint}`;
    }
  } catch (e) {
    dot.className = 'status-dot error';
    dot.title = 'LLM 状态未知';
  }
}

// 刷新项目名 + 进度
async function refreshHeader() {
  try {
    const data = await api.project.get();
    const p = data.project || {};
    document.getElementById('project-title').textContent = p.title || '未命名作品';
    store.set('project', p);
  } catch (e) { /* ignore */ }

  try {
    const data = await api.chapters.list();
    const chapters = data.chapters || [];
    store.set('chapters', chapters);
    const total = 36;
    const done = chapters.filter((c) => c.status === 'accepted').length;
    document.getElementById('progress-text').textContent = `${done} / ${total}`;
    document.getElementById('progress-fill').style.width = `${(done / total) * 100}%`;
  } catch (e) { /* ignore */ }

  try {
    const data = await api.hello();
    document.getElementById('meta-info').textContent =
      `后端就绪 · ${data.message}`;
  } catch (e) { /* ignore */ }
}

// ============================================================ 启动
function init() {
  ensureToastContainer();

  // 导航点击
  document.querySelectorAll('.nav-item').forEach((el) => {
    el.addEventListener('click', (e) => {
      e.preventDefault();
      const view = el.dataset.view;
      if (view) location.hash = '#' + view;
    });
  });

  // 设置按钮
  document.getElementById('btn-settings').addEventListener('click', () => {
    location.hash = '#settings';
  });

  // hash 路由
  window.addEventListener('hashchange', route);

  // 首次路由
  if (!location.hash) {
    location.hash = '#' + DEFAULT_VIEW;
  } else {
    route();
  }

  // 异步刷新
  refreshHeader();
  refreshLlmStatus();
  setInterval(refreshHeader, 30000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

// 导出给 views 用
export { api, store, toast, escapeHtml };
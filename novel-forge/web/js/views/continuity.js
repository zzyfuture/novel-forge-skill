// web/js/views/continuity.js
import { api } from '../api.js';
import { escapeHtml, setStatus, toast } from '../store.js';

let local = {
  chapterFilter: null,
  severityFilter: 'all',
  issues: [],
  chapters: [],
};

export async function renderContinuity(main, arg) {
  setStatus('加载一致性中心…');
  main.innerHTML = '<div class="empty">加载中…</div>';

  local.chapterFilter = arg ? parseInt(arg, 10) : null;

  const chapRes = await api.chapters.list().catch(() => ({ chapters: [] }));
  local.chapters = chapRes.chapters || [];

  // 收集所有章节的 issues
  const all = [];
  for (const c of local.chapters) {
    try {
      const d = await api.chapters.issues(c.chapter_no);
      for (const it of (d.issues || [])) {
        if (it.status !== 'open') continue;
        all.push({ ...it, chapter_no: c.chapter_no });
      }
    } catch { /* ignore */ }
  }
  local.issues = all;

  draw(main);
  setStatus('就绪');
}

function draw(main) {
  let list = local.issues;
  if (local.chapterFilter) {
    list = list.filter((i) => i.chapter_no === local.chapterFilter);
  }
  if (local.severityFilter !== 'all') {
    list = list.filter((i) => i.severity === local.severityFilter);
  }

  const blockers = local.issues.filter((i) => i.severity === 'blocker').length;
  const warnings = local.issues.filter((i) => i.severity === 'warning').length;
  const infos = local.issues.filter((i) => i.severity === 'info').length;

  main.innerHTML = `
    <h1 class="page-title">
      一致性中心
      <div class="page-actions">
        <button class="btn-ghost" id="btn-refresh">重新扫描</button>
      </div>
    </h1>

    <div class="row mb-2" style="gap:8px;">
      <select id="sel-chapter" style="padding:6px 10px;background:var(--panel-2);border:1px solid var(--border);border-radius:6px;color:var(--text);">
        <option value="">全部章节</option>
        ${local.chapters.map((c) => `
          <option value="${c.chapter_no}" ${local.chapterFilter === c.chapter_no ? 'selected' : ''}>
            第 ${c.chapter_no} 章 · ${escapeHtml(c.title || '—')}
          </option>
        `).join('')}
      </select>

      <select id="sel-severity" style="padding:6px 10px;background:var(--panel-2);border:1px solid var(--border);border-radius:6px;color:var(--text);">
        <option value="all" ${local.severityFilter === 'all' ? 'selected' : ''}>全部（${blockers + warnings + infos}）</option>
        <option value="blocker" ${local.severityFilter === 'blocker' ? 'selected' : ''}>阻断（${blockers}）</option>
        <option value="warning" ${local.severityFilter === 'warning' ? 'selected' : ''}>警告（${warnings}）</option>
        <option value="info" ${local.severityFilter === 'info' ? 'selected' : ''}>建议（${infos}）</option>
      </select>
    </div>

    <div id="issue-list">
      ${list.length ? list.map((it) => issueCard(it)).join('') : '<div class="empty">没有待处理问题 ✅</div>'}
    </div>
  `;

  document.getElementById('btn-refresh').onclick = () => renderContinuity(main);
  document.getElementById('sel-chapter').onchange = (e) => {
    const v = e.target.value;
    local.chapterFilter = v ? parseInt(v, 10) : null;
    draw(main);
  };
  document.getElementById('sel-severity').onchange = (e) => {
    local.severityFilter = e.target.value;
    draw(main);
  };

  main.querySelectorAll('[data-resolve]').forEach((el) => {
    el.onclick = () => resolveIssue(+el.dataset.resolve, el.dataset.action);
  });
}

function issueCard(it) {
  const sev = it.severity;
  const label = sev === 'blocker' ? '阻断' : sev === 'warning' ? '警告' : '建议';
  return `
    <div class="issue ${sev}">
      <div class="issue-title">
        <span class="badge ${sev}">${label}</span>
        <span class="mono small">${escapeHtml(it.code)}</span>
        <span class="muted small" style="margin-left:auto;">第 ${it.chapter_no} 章</span>
      </div>
      <div class="issue-detail">${escapeHtml(it.title)}</div>
      ${it.detail ? `<div class="issue-detail muted small">${escapeHtml(it.detail)}</div>` : ''}
      ${(it.evidence || []).length ? `
        <div class="issue-evidence">${it.evidence.map((e) => escapeHtml(typeof e === 'string' ? e : JSON.stringify(e))).join('\n')}</div>
      ` : ''}
      ${it.suggestion ? `<div class="muted small mb-1">建议：${escapeHtml(it.suggestion)}</div>` : ''}
      <div class="issue-actions">
        <a class="btn-ghost" href="#studio/${it.chapter_no}">去章节</a>
        <button class="btn-ghost" data-resolve="${it.id}" data-action="accepted">接受现状</button>
        <button class="btn-ghost" data-resolve="${it.id}" data-action="waived">豁免</button>
      </div>
    </div>
  `;
}

async function resolveIssue(id, action) {
  try {
    await api.issues.resolve(id, action);
    toast('已处理', 'success');
    // 从本地列表移除
    local.issues = local.issues.filter((i) => i.id !== id);
    const main = document.getElementById('main-view');
    draw(main);
  } catch (e) {
    toast('处理失败：' + e.message, 'error');
  }
}
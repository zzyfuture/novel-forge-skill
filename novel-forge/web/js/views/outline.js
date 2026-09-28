// web/js/views/outline.js
import { api } from '../api.js';
import { escapeHtml, setStatus } from '../store.js';

const STATUS_LABEL = {
  draft: '草稿合同',
  frozen: '已冻结',
  superseded: '已废弃',
};

export async function renderOutline(main) {
  setStatus('加载大纲…');
  main.innerHTML = '<div class="empty">加载中…</div>';

  const [chapRes, outlineRes] = await Promise.all([
    api.chapters.list().catch(() => ({ chapters: [] })),
    api.outline.list().catch(() => ({ outline: [] })),
  ]);

  const chapters = chapRes.chapters || [];
  const outline = outlineRes.outline || [];
  const outlineByNo = Object.fromEntries(outline.map((o) => [o.chapter_no, o]));

  // 合并：以 1..36 为骨架
  const rows = [];
  for (let n = 1; n <= 36; n++) {
    const ch = chapters.find((c) => c.chapter_no === n) || {};
    const ol = outlineByNo[n] || {};
    rows.push({
      chapter_no: n,
      title: ch.title || ol.intent || '—',
      status: ch.status || 'pending',
      intent: ol.intent || '',
      contract: ch.contract_status,
    });
  }

  // 按部切分
  const parts = [
    { name: '第一部 · 破局篇', from: 1, to: 12 },
    { name: '第二部 · 弈局篇', from: 13, to: 24 },
    { name: '第三部 · 终局篇', from: 25, to: 36 },
  ];

  main.innerHTML = `
    <h1 class="page-title">
      大纲
      <div class="page-actions">
        <button class="btn-ghost" id="btn-refresh">刷新</button>
      </div>
    </h1>

    ${parts.map((p) => {
      const list = rows.filter((r) => r.chapter_no >= p.from && r.chapter_no <= p.to);
      const done = list.filter((r) => r.status === 'accepted').length;
      return `
        <div class="card">
          <div class="card-title">
            ${escapeHtml(p.name)}
            <span class="meta">${done} / ${list.length}</span>
          </div>
          <div>
            ${list.map((r) => `
              <div class="chapter-item" style="cursor:pointer;"
                   onclick="location.hash='#studio/${r.chapter_no}'">
                <span class="num">${r.chapter_no}</span>
                <span class="status-icon">${icon(r.status)}</span>
                <span style="flex:1;">${escapeHtml(r.title)}</span>
                <span class="muted small">${statusLabel(r.status)}</span>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }).join('')}
  `;

  document.getElementById('btn-refresh').onclick = () => renderOutline(main);
  setStatus('就绪');
}

function icon(status) {
  if (status === 'accepted') return '✅';
  if (status === 'reviewing') return '◐';
  if (status === 'blocked') return '⛔';
  if (status === 'draft') return '◌';
  return '○';
}

function statusLabel(status) {
  if (status === 'accepted') return '已验收';
  if (status === 'reviewing') return '待验收';
  if (status === 'blocked') return '阻断';
  if (status === 'draft') return '草稿';
  return '未开始';
}
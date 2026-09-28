// web/js/views/studio.js
import { api, pollJob } from '../api.js';
import {
  escapeHtml, setStatus, toast,
  showJobBar, updateJobBar, hideJobBar,
  confirmDialog, alertDialog,
} from '../store.js';

let local = {
  chapterNo: null,
  chapter: null,
  contract: null,
  issues: [],
  busy: false,
  view: 'text',
  storyboard: null,
  shotCount: 8,           // ← 新增，默认 8
};

export async function renderStudio(main, arg) {
  setStatus('加载章节工作台…');
  main.innerHTML = '<div class="empty">加载中…</div>';

  const chapterNo = parseInt(arg, 10) || 1;

  const [chapRes, issueRes] = await Promise.all([
    api.chapters.get(chapterNo).catch(() => ({})),
    api.chapters.issues(chapterNo).catch(() => ({ issues: [] })),
  ]);

  local.chapterNo = chapterNo;
  local.view = 'text';
  local.shotCount = 8;
  local.storyboard = null;
  local.busy = false;       
  local.chapter = chapRes.chapter;
  local.contract = chapRes.contract;
  local.issues = issueRes.issues || [];

  main.innerHTML = `
    <h1 class="page-title">
      章节工作台
      <span class="muted small">第 ${chapterNo} 章</span>
      <div class="page-actions">
        <button class="btn-ghost" id="btn-prev">← 上一章</button>
        <button class="btn-ghost" id="btn-next">下一章 →</button>
      </div>
    </h1>

    <div class="grid-studio">
      <div class="chapter-list" id="chapter-list"></div>
      <div id="studio-main"></div>
      <div class="inspector" id="studio-inspector"></div>
    </div>
  `;

  document.getElementById('btn-prev').onclick = () => {
    if (chapterNo > 1) location.hash = `#studio/${chapterNo - 1}`;
  };
  document.getElementById('btn-next').onclick = () => {
    if (chapterNo < 36) location.hash = `#studio/${chapterNo + 1}`;
  };

  await refreshChapterList();
  drawMain();
  drawInspector();
  setStatus('就绪');
}

// ---------------------------------------------------------- 左侧章节列表
async function refreshChapterList() {
  const res = await api.chapters.list().catch(() => ({ chapters: [] }));
  const chapters = res.chapters || [];
  const list = document.getElementById('chapter-list');
  if (!list) return;

  const map = Object.fromEntries(chapters.map((c) => [c.chapter_no, c]));
  const parts = [
    { from: 1, to: 12, name: '第一部' },
    { from: 13, to: 24, name: '第二部' },
    { from: 25, to: 36, name: '第三部' },
  ];

  list.innerHTML = parts.map((p) => `
    <div style="padding:8px 14px;background:var(--panel-2);font-size:10px;
                color:var(--text-mute);text-transform:uppercase;letter-spacing:0.5px;">
      ${p.name}
    </div>
    ${Array.from({ length: p.to - p.from + 1 }, (_, i) => {
      const n = p.from + i;
      const c = map[n] || {};
      const active = n === local.chapterNo;
      const st = c.status || 'pending';
      return `
        <div class="chapter-item ${active ? 'active' : ''} ${n <= 3 && st === 'pending' ? 'guide-highlight' : ''}"
             data-chapter="${n}">
          <span class="num">${n}</span>
          <span class="status-icon">${icon(st)}</span>
          <span style="flex:1;">${escapeHtml(c.title || '—')}</span>
          ${n <= 3 && st === 'pending' ? '<span class="badge primary" style="font-size:9px;">先跑这章</span>' : ''}
        </div>
      `;
    }).join('')}
  `).join('');

  list.querySelectorAll('[data-chapter]').forEach((el) => {
    el.onclick = () => { location.hash = `#studio/${el.dataset.chapter}`; };
  });
}

function icon(st) {
  if (st === 'accepted') return '✅';
  if (st === 'reviewing') return '◐';
  if (st === 'blocked') return '⛔';
  if (st === 'draft') return '◌';
  return '○';
}

// ---------------------------------------------------------- 中间主区
function drawMain() {
  if (local.view === 'storyboard') {
    drawStoryboardMain();
  } else {
    drawTextMain();
  }
}

function drawTextMain() {
  const main = document.getElementById('studio-main');
  const ch = local.chapter;
  const ct = local.contract;
  const n = local.chapterNo;

  const hasContract = !!ct;
  const frozen = ct && ct.status === 'frozen';
  const hasBody = ch && ch.body_md;

  main.innerHTML = `
    <div class="card" style="height:100%;display:flex;flex-direction:column;">
      <div class="card-title" style="flex-shrink:0;">
        <div class="row" style="gap:12px;">
          <span>第 ${n} 章${ch && ch.title ? ' · ' + escapeHtml(ch.title) : ''}</span>
          <span class="view-tabs">
            <a class="view-tab active" data-view="text">正文</a>
            <a class="view-tab" data-view="storyboard">分镜</a>
          </span>
        </div>
        <span class="meta">
          ${hasContract ? `
            合同 v${ct.version}
            <span class="badge ${frozen ? 'ok' : 'warning'}">${frozen ? '已冻结' : '草稿'}</span>
          ` : '<span class="badge warning">无合同</span>'}
        </span>
      </div>

      <div style="flex:1;display:flex;flex-direction:column;overflow:hidden;">
        ${hasBody ? `
          <textarea class="chapter-editor" id="chapter-editor"
            style="flex:1;min-height:0;">${escapeHtml(ch.body_md)}</textarea>
        ` : `
          <div class="empty" style="flex:1;display:flex;align-items:center;justify-content:center;">
            ${hasContract
              ? (frozen ? '尚无正文，点「生成草稿」开始'
                        : '合同还没冻结，先冻结合同')
              : '还没有合同，先由大纲生成'}
          </div>
        `}
      </div>

      <div class="row mt-2" style="flex-shrink:0;gap:8px;">
        ${!hasContract ? `
          <button class="btn" id="btn-make-contract">生成合同</button>
        ` : (!frozen ? `
          <button class="btn" id="btn-edit-contract">编辑合同</button>
          <button class="btn" id="btn-freeze">冻结合同</button>
        ` : `
          <button class="btn-ghost" id="btn-unfreeze"
            title="退回草稿状态，可重新编辑；已生成的正文会保留">
            取消冻结
          </button>
          <button class="btn" id="btn-write"
            ${local.busy ? 'disabled' : ''}
            ${ch && ch.status === 'accepted' ? 'disabled title="已验收的章节不可重写"' : ''}>
            ${hasBody ? '重新生成' : '生成草稿'}
          </button>
          ${hasBody ? `
            <button class="btn-ghost" id="btn-save-body">保存改动</button>
          ` : ''}
          ${hasBody ? `
            <button class="btn-success btn" id="btn-accept"
              ${local.issues.some((i) => i.status === 'open' && i.severity === 'blocker') ? 'disabled' : ''}>
              验收本章
            </button>
          ` : ''}
          <button class="btn-ghost" id="btn-check">重新审校</button>
        `)}
        ${hasBody ? `
          <span class="muted small" style="margin-left:auto;">
            ${ch.word_count || 0} / ${ct.word_target || 3500} 字
          </span>
        ` : ''}
      </div>
    </div>
  `;

  // 事件
  const btnMake = document.getElementById('btn-make-contract');
  if (btnMake) btnMake.onclick = () => makeContract(n);

  const btnEdit = document.getElementById('btn-edit-contract');
  if (btnEdit) btnEdit.onclick = () => openContractEditor(local.contract, n);

  const btnUnfreeze = document.getElementById('btn-unfreeze');
  if (btnUnfreeze) btnUnfreeze.onclick = () => unfreezeContract(n);

  const btnFreeze = document.getElementById('btn-freeze');
  if (btnFreeze) btnFreeze.onclick = () => freezeContract(n);

  const btnWrite = document.getElementById('btn-write');
  if (btnWrite) btnWrite.onclick = () => startWrite(n);

  const btnSave = document.getElementById('btn-save-body');
  if (btnSave) {
    btnSave.onclick = async () => {
      const editor = document.getElementById('chapter-editor');
      if (!editor) return;
      try {
        setStatus('保存中…');
        const r = await api.chapters.save(n, editor.value);
        toast(`已保存 · ${r.word_count} 字`, 'success');
        local.chapter.body_md = editor.value;
        local.chapter.word_count = r.word_count;
        setStatus('就绪');
      } catch (e) {
        toast('保存失败：' + e.message, 'error');
        setStatus('就绪');
      }
    };
  }

  const btnAccept = document.getElementById('btn-accept');
  if (btnAccept) btnAccept.onclick = () => startAccept(n);

  const btnCheck = document.getElementById('btn-check');
  if (btnCheck) btnCheck.onclick = () => startRecheck(n);

  const editor = document.getElementById('chapter-editor');
  if (editor) {
    editor.oninput = () => {
      // 本地暂存，不自动保存（用户手动触发验收时一次性落库）
      local.chapter.body_md = editor.value;
    };
  }

  // view tab 切换（无论有没有正文都要绑）
  main.querySelectorAll('.view-tab').forEach((el) => {
    el.onclick = () => {
      local.view = el.dataset.view;
      drawMain();
    };
  });
}

// ---------------------------------------------------------- 分镜视图
async function drawStoryboardMain() {
  const main = document.getElementById('studio-main');
  const n = local.chapterNo;
  const ch = local.chapter;

  main.innerHTML = `
    <div class="card" style="height:100%;display:flex;flex-direction:column;">
      <div class="card-title" style="flex-shrink:0;">
        <div class="row" style="gap:12px;">
          <span>第 ${n} 章${ch && ch.title ? ' · ' + escapeHtml(ch.title) : ''}</span>
          <span class="view-tabs">
            <a class="view-tab" data-view="text">正文</a>
            <a class="view-tab active" data-view="storyboard">分镜</a>
          </span>
        </div>
        <span class="meta" id="sb-meta">加载中…</span>
      </div>
      <div id="sb-body" style="flex:1;overflow:auto;">
        <div class="empty">加载中…</div>
      </div>
    </div>
  `;

  main.querySelectorAll('.view-tab').forEach((el) => {
    el.onclick = () => {
      local.view = el.dataset.view;
      drawMain();
    };
  });

  // 拉取分镜数据
  let data;
  try {
    data = await api.chapters.storyboard.get(n);
  } catch (e) {
    document.getElementById('sb-body').innerHTML =
      `<div class="empty">加载失败：${escapeHtml(e.message)}</div>`;
    return;
  }

  local.storyboard = data;
  renderStoryboardBody();
}

function renderStoryboardBody() {
  const body = document.getElementById('sb-body');
  const meta = document.getElementById('sb-meta');
  const data = local.storyboard || {};
  const sb = data.storyboard;
  const shots = data.shots || [];
  const n = local.chapterNo;

  // 顶部状态
  if (!sb || shots.length === 0) {
    meta.textContent = '尚未生成';
  } else {
    const total = shots.length;
    const done = shots.filter((s) => s.status === 'done').length;
    const text_only = shots.filter((s) => s.status === 'text_only').length;
    const failed = shots.filter((s) => s.status === 'failed').length;
    const dur = sb.estimated_duration_sec || 0;
    meta.textContent = `${total} 个镜头 · 预计 ${dur} 秒`;
    if (done < total) {
      meta.textContent += ` · 出图 ${done}${text_only ? ` · 文字 ${text_only}` : ''}${failed ? ` · 失败 ${failed}` : ''}`;
    }
  }

  // 空态：还没生成
    if (!sb || shots.length === 0) {
    body.innerHTML = `
      <div class="empty" style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:16px;">
        <div>还没有分镜。选好镜头数后生成。</div>
        <div class="row" style="gap:8px;align-items:center;">
          <label class="small muted">镜头数：</label>
          <select id="sb-shot-count" class="mini-select">
            <option value="5" ${local.shotCount === 5 ? 'selected' : ''}>5 个（精简）</option>
            <option value="8" ${local.shotCount === 8 ? 'selected' : ''}>8 个（标准）</option>
            <option value="12" ${local.shotCount === 12 ? 'selected' : ''}>12 个（详细）</option>
            <option value="15" ${local.shotCount === 15 ? 'selected' : ''}>15 个（完整）</option>
          </select>
        </div>
        <button class="btn" id="btn-sb-generate">生成分镜</button>
        <div class="muted small" id="sb-estimate">预计 ¥4.8 · 2–4 分钟</div>
      </div>
    `;
    const sel = document.getElementById('sb-shot-count');
    const est = document.getElementById('sb-estimate');
    const updateEstimate = () => {
      const c = parseInt(sel.value, 10);
      local.shotCount = c;
      est.textContent = `预计 ¥${(c * 0.6).toFixed(1)} · ${Math.round(c * 10 / 60) + 1}–${Math.round(c * 20 / 60) + 2} 分钟`;
    };
    sel.onchange = updateEstimate;
    updateEstimate();
    document.getElementById('btn-sb-generate').onclick = () => startStoryboard(n, false);
    return;
  }

  // 有镜头：工具栏 + 网格
  body.innerHTML = `
    <div class="row" style="padding:12px 20px;border-bottom:1px solid var(--border);gap:8px;flex-wrap:wrap;">
      <button class="btn" id="btn-sb-regenerate">重新生成全部</button>
      <button class="btn-ghost" id="btn-sb-export-json">导出 JSON</button>
      <button class="btn-ghost" id="btn-sb-refresh">刷新</button>
    </div>
    <div class="sb-grid" id="sb-grid"></div>
  `;

  const grid = document.getElementById('sb-grid');
  grid.innerHTML = shots.map((s) => shotCard(s, n)).join('');

    document.getElementById('btn-sb-regenerate').onclick = async () => {
    const done = shots.filter((s) => s.status === 'done' && s.image_path).length;
    const failed = shots.length - done;
    if (failed === 0) {
      const ok = await confirmDialog({
        title: '全部重画？',
        message: `已有 ${done} 张成功的分镜。\n全部重画会再花 ¥${(shots.length * 0.6).toFixed(1)}，耗时 2–4 分钟。\n\n只想补失败的，点「取消」然后用下方「单张重画」。`,
        okText: '全部重画',
        cancelText: '取消',
      });
      if (ok) startStoryboard(n, true);
    } else {
      startStoryboard(n, false);
    }
  };
  document.getElementById('btn-sb-refresh').onclick = () => drawMain();
  document.getElementById('btn-sb-export-json').onclick = () => exportStoryboardJSON();

  grid.querySelectorAll('[data-retry]').forEach((el) => {
    el.onclick = () => retryShot(n, parseInt(el.dataset.retry, 10));
  });
  // 点击图片放大
  grid.querySelectorAll('[data-zoom]').forEach((el) => {
    el.onclick = () => showImageOverlay(el.dataset.zoom);
  });
  grid.querySelectorAll('[data-copy]').forEach((el) => {
    el.onclick = () => {
      const s = shots.find((x) => x.shot_id === parseInt(el.dataset.copy, 10));
      if (s && s.prompt_used) {
        navigator.clipboard.writeText(s.prompt_used).then(
          () => toast('prompt 已复制', 'success', 1200),
          () => toast('复制失败', 'error')
        );
      }
    };
  });
}

function shotCard(s, n) {
  const status = s.status || 'pending';
  const statusLabel = {
    done: '已出图',
    text_only: '仅文字',
    failed: '失败',
    pending: '待生成',
    generating: '生成中',
  }[status] || status;

  const statusClass =
    status === 'done' ? 'ok' :
    status === 'failed' ? 'blocker' :
    status === 'text_only' ? 'warning' : 'info';

    const img = s.image_url
    ? `<img src="${s.image_url}" alt="shot ${s.shot_id}" loading="lazy"
             data-zoom="${s.image_url}"
             style="width:100%;display:block;border-radius:4px;background:#0a0d12;cursor:zoom-in;"
             onerror="this.style.display='none'">`
    : `<div style="aspect-ratio:16/9;background:#0a0d12;border-radius:4px;display:flex;align-items:center;justify-content:center;color:#5A6474;font-size:12px;">${escapeHtml(statusLabel)}</div>`;

  return `
    <div class="sb-card">
      <div class="sb-card-head">
        <span class="sb-shot-id">镜头 ${s.shot_id}</span>
        <span class="badge ${statusClass}">${statusLabel}</span>
      </div>
      ${img}
      <div class="sb-card-meta">
        <div class="row-between" style="font-size:11px;color:var(--text-mute);">
          <span>${escapeHtml(s.shot_type || '—')}</span>
          <span>${s.duration_sec || 0} 秒</span>
        </div>
        ${s.action ? `<div class="sb-action">${escapeHtml(s.action.slice(0, 80))}${s.action.length > 80 ? '…' : ''}</div>` : ''}
        ${s.dialogue ? `<div class="sb-dialogue">「${escapeHtml(s.dialogue.slice(0, 60))}」</div>` : ''}
      </div>
      <div class="sb-card-actions">
        <button class="btn-ghost tiny" data-retry="${s.shot_id}">重画</button>
        ${s.prompt_used ? `<button class="btn-ghost tiny" data-copy="${s.shot_id}">复制 prompt</button>` : ''}
      </div>
    </div>
  `;
}

async function startStoryboard(n, forceRerun = false) {
  if (local.busy) {
    toast('正在执行其它任务，请等待完成再生成分镜', 'info', 2500);
    return;
  }
  local.busy = true;
  try {
    setStatus('提交分镜任务…');
    const res = await api.chapters.storyboard.generate(n, {
      shotCount: local.shotCount,
      forceRerun,
    });
    if (!res.task_id) throw new Error(res.error || '提交失败');
    showJobBar({ step: 'init', message: '分镜', progress: 0 });
    await pollJob(res.task_id, (job) => {
      updateJobBar(job);
      setStatus(`分镜 · ${job.message || ''}`);
    });
    hideJobBar();
    toast('分镜生成完成', 'success');
    await drawStoryboardMain();
    setStatus('就绪');
  } catch (e) {
    hideJobBar();
    toast('生成失败：' + e.message, 'error');
    setStatus('生成失败');
  } finally {
    local.busy = false;
  }
}

async function retryShot(n, shotId) {
  try {
    setStatus(`重画镜头 ${shotId}…`);
    const res = await api.chapters.storyboard.retry(n, shotId);
    if (!res.ok) throw new Error(res.error || '重画失败');
    toast(`镜头 ${shotId} 已重画`, 'success');
    await drawStoryboardMain();
    setStatus('就绪');
  } catch (e) {
    toast('重画失败：' + e.message, 'error');
    setStatus('就绪');
  }
}

function exportStoryboardJSON() {
  const data = local.storyboard || {};
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `storyboard-ch${local.chapterNo}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------------------------------------------------------- 右侧检查器
function drawInspector() {
  const el = document.getElementById('studio-inspector');
  const ct = local.contract;
  const ch = local.chapter;
  const issues = local.issues || [];

  if (!ct) {
    el.innerHTML = '<div class="empty">无合同，检查器无数据</div>';
    return;
  }

  const openBlockers = issues.filter((i) => i.status === 'open' && i.severity === 'blocker');
  const openWarnings = issues.filter((i) => i.status === 'open' && i.severity === 'warning');

  el.innerHTML = `
    <div class="inspector-section">
      <h4>合同</h4>
      <div class="small">
        <div>POV：${escapeHtml(ct.pov_character_id || '—')}</div>
        <div>场景：${(ct.scenes || []).length}</div>
        <div>目标：${ct.word_target || 3500} 字</div>
        <div class="mt-1 muted">${escapeHtml((ct.tone || '').slice(0, 80))}</div>
      </div>
    </div>

    ${ct.must_advance && ct.must_advance.length ? `
      <div class="inspector-section">
        <h4>必须推进</h4>
        <ul>${ct.must_advance.map((m) => `<li>${escapeHtml(m)}</li>`).join('')}</ul>
      </div>
    ` : ''}

    ${ct.plant && ct.plant.length ? `
      <div class="inspector-section">
        <h4>埋设</h4>
        <ul>${ct.plant.map((p) => `<li>
          <span class="badge primary">${escapeHtml(p.scheme || '')}</span>
          ${escapeHtml((p.evidence || '').slice(0, 60))}
        </li>`).join('')}</ul>
      </div>
    ` : ''}

    ${ct.payoff && ct.payoff.length ? `
      <div class="inspector-section">
        <h4>回收</h4>
        <ul>${ct.payoff.map((p) => `<li>
          <span class="badge primary">${escapeHtml(p.scheme || '')}</span>
          ${escapeHtml((p.note || '').slice(0, 60))}
        </li>`).join('')}</ul>
      </div>
    ` : ''}

    ${ct.forbid && ct.forbid.length ? `
      <div class="inspector-section">
        <h4>禁止</h4>
        <ul>${ct.forbid.slice(0, 6).map((f) => `<li>${escapeHtml(f)}</li>`).join('')}</ul>
      </div>
    ` : ''}

    <div class="inspector-section">
      <h4>一致性</h4>
      ${openBlockers.length ? `
        <div class="badge blocker mb-1">阻断 ${openBlockers.length}</div>
      ` : ''}
      ${openWarnings.length ? `
        <div class="badge warning mb-1">警告 ${openWarnings.length}</div>
      ` : ''}
      ${!openBlockers.length && !openWarnings.length ? `
        <div class="badge ok">暂无问题</div>
      ` : ''}
      ${issues.length ? `
        <div class="mt-2">
          <a href="#continuity/${local.chapterNo}">查看详情 →</a>
        </div>
      ` : ''}
    </div>
  `;
}

// ---------------------------------------------------------- 操作
async function makeContract(n) {
  if (local.busy) return;
  local.busy = true;
  try {
    setStatus('生成合同…');
    // 从已有 draft 或 seed 里拿
    const res = await api.chapters.contract.get(n);
    if (res.frozen) {
      toast('已存在冻结合同，无需生成', 'info');
      return;
    }
    if (res.draft) {
      toast('已存在草稿合同，去冻结合同即可', 'info');
      return;
    }
    // 简化：没有合同就报错，让用户走 seed
    toast('本合同未在 seed 中预置', 'error');
  } catch (e) {
    toast('生成失败：' + e.message, 'error');
  } finally {
    local.busy = false;
    setStatus('就绪');
  }
}

async function freezeContract(n) {
  if (!local.contract) return;
  const ok = await confirmDialog({
    title: '冻结合同',
    message: `冻结合同 v${local.contract.version}？\n\n冻结后合同不可修改。如需变更，会生成新版本。`,
    okText: '冻结',
    cancelText: '再想想',
  });
  if (!ok) return;
  try {
    setStatus('冻结合同…');
    await api.chapters.contract.freeze(n, {
      version: local.contract.version,
      hash: 'manual',
    });
    toast('合同已冻结', 'success');
    location.reload();
  } catch (e) {
    toast('冻结失败：' + e.message, 'error');
    setStatus('就绪');
  }
}

async function unfreezeContract(n) {
  const ok = await confirmDialog({
    title: '取消冻结',
    message: '退回草稿状态后可以重新编辑合同。\n\n' +
             '已生成的正文和分镜会保留；\n' +
             '重新冻结合同后，下一章会用新合同。\n\n' +
             '确定取消冻结？',
    okText: '取消冻结',
    cancelText: '再想想',
    danger: true,
  });
  if (!ok) return;
  try {
    setStatus('取消冻结…');
    await api.chapters.contract.unfreeze(n);
    toast('合同已退回草稿状态', 'success');
    location.reload();
  } catch (e) {
    toast('取消失败：' + e.message, 'error');
    setStatus('就绪');
  }
}

async function startWrite(n) {
  if (local.busy) {
    toast('正在执行其它任务，请等待完成再生成分镜', 'info', 2500);
    return;
  }
  local.busy = true;
  try {
    setStatus('提交生成任务…');
    const res = await api.chapters.write(n);
    if (!res.task_id) throw new Error(res.error || '提交失败');
    showJobBar({ step: 'init', message: '初始化', progress: 0 });
    await pollJob(res.task_id, (job) => {
      updateJobBar(job);
      setStatus(`${job.step} · ${job.message || ''}`);
    });
    hideJobBar();
    toast('生成完成，已进入待验收', 'success');
    // 重新加载
    const [chapRes, issueRes] = await Promise.all([
      api.chapters.get(n),
      api.chapters.issues(n),
    ]);
    local.chapter = chapRes.chapter;
    local.contract = chapRes.contract;
    local.issues = issueRes.issues || [];
    drawMain();
    drawInspector();
    refreshChapterList();
    setStatus('就绪');
  } catch (e) {
    hideJobBar();
    toast('生成失败：' + e.message, 'error');
    setStatus('生成失败');
  } finally {
    local.busy = false;
  }
}

async function startRecheck(n) {
  if (local.busy) {
    toast('正在执行其它任务，请等待完成再生成分镜', 'info', 2500);
    return;
  }
  local.busy = true;
  try {
    setStatus('提交审校任务…');
    const res = await api.chapters.recheck(n);
    if (!res.task_id) throw new Error(res.error || '提交失败');
    showJobBar({ step: 'init', message: '审校', progress: 0 });
    await pollJob(res.task_id, (job) => {
      updateJobBar(job);
      setStatus(`审校 · ${job.message || ''}`);
    });
    hideJobBar();
    toast('审校完成', 'success');

    const [chapRes, issueRes] = await Promise.all([
      api.chapters.get(n),
      api.chapters.issues(n),
    ]);
    local.chapter = chapRes.chapter;
    local.contract = chapRes.contract;
    local.issues = issueRes.issues || [];
    drawMain();
    drawInspector();
    refreshChapterList();
    setStatus('就绪');
  } catch (e) {
    hideJobBar();
    toast('审校失败：' + e.message, 'error');
    setStatus('审校失败');
  } finally {
    local.busy = false;
  }
}

async function startAccept(n) {
  if (local.busy) {
    toast('正在执行其它任务，请等待完成再生成分镜', 'info', 2500);
    return;
  }
  local.busy = true;
  try {
    // 先保存正文到后端
    const editor = document.getElementById('chapter-editor');
    if (editor && local.chapter) {
      const newBody = editor.value;
      if (newBody !== local.chapter.body_md) {
        try {
          setStatus('保存改动…');
          await api.chapters.save(n, newBody);
          local.chapter.body_md = newBody;
        } catch (e) {
          toast('保存失败，验收中止：' + e.message, 'error');
          local.busy = false;
          return;
        }
      }
    }
    setStatus('验收中…');
    const res = await api.chapters.accept(n);
    if (!res.task_id) throw new Error(res.error || '提交失败');
    showJobBar({ step: 'init', message: '验收', progress: 0 });
    await pollJob(res.task_id, (job) => {
      updateJobBar(job);
      setStatus(`验收 · ${job.message || ''}`);
    });
    hideJobBar();
    toast('验收完成', 'success');
    location.reload();
  } catch (e) {
    hideJobBar();
    toast('验收失败：' + e.message, 'error');
    setStatus('验收失败');
  } finally {
    local.busy = false;
  }
}

// ---------------------------------------------------------- 图片放大查看
function showImageOverlay(url) {
  const overlay = document.createElement('div');
  overlay.className = 'image-overlay';
  overlay.innerHTML = `
    <div class="image-overlay-close">✕</div>
    <img src="${url}" alt="zoom">
  `;
  document.body.appendChild(overlay);

  const close = () => {
    overlay.classList.add('closing');
    setTimeout(() => overlay.remove(), 150);
  };
  overlay.onclick = (e) => {
    // 点图片本身不关，点背景或关闭按钮才关
    if (e.target.tagName !== 'IMG') close();
  };
  const onKey = (e) => {
    if (e.key === 'Escape') {
      document.removeEventListener('keydown', onKey);
      close();
    }
  };
  document.addEventListener('keydown', onKey);
}

// ---------------------------------------------------------- 合同编辑器
function openContractEditor(contract, chapterNo) {
  if (!contract) return;

  // 从合同对象里取字段，做防御性拷贝
  const draft = {
    pov_character_id: contract.pov_character_id || '',
    word_target: contract.word_target || 3500,
    tone: contract.tone || '',
    scenes: JSON.parse(JSON.stringify(contract.scenes || [])),
    must_advance: [...(contract.must_advance || [])],
    plant: JSON.parse(JSON.stringify(contract.plant || [])),
    payoff: JSON.parse(JSON.stringify(contract.payoff || [])),
    forbid: [...(contract.forbid || [])],
    domain_inject: [...(contract.domain_inject || [])],
  };

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal" style="min-width:720px;max-width:900px;width:90vw;">
      <div class="modal-title">编辑合同 · 第 ${chapterNo} 章 · v${contract.version}</div>
        <div class="ce-body" id="ce-body"
           style="max-height:65vh;overflow-y:auto;padding-right:8px;margin-bottom:16px;">

        <div class="ce-grid-2">
          <div class="ce-row">
            <label class="ce-label">POV 角色</label>
            <input type="text" id="ce-pov" value="${escapeHtml(draft.pov_character_id)}" />
          </div>
          <div class="ce-row">
            <label class="ce-label">目标字数</label>
            <input type="number" id="ce-words" value="${draft.word_target}" min="500" max="20000" />
          </div>
        </div>

        <div class="ce-row">
          <label class="ce-label">调性 / Tone</label>
          <textarea id="ce-tone" rows="2">${escapeHtml(draft.tone)}</textarea>
        </div>

        <div class="ce-section">
          <div class="ce-section-head">
            <span>场景（scenes）</span>
            <button class="btn-ghost tiny" data-add="scenes">+ 添加</button>
          </div>
          <div id="ce-scenes"></div>
        </div>

        <div class="ce-section">
          <div class="ce-section-head">
            <span>必须推进（must_advance）</span>
            <button class="btn-ghost tiny" data-add="must_advance">+ 添加</button>
          </div>
          <div id="ce-must_advance"></div>
        </div>

        <div class="ce-section">
          <div class="ce-section-head">
            <span>埋设（plant）</span>
            <button class="btn-ghost tiny" data-add="plant">+ 添加</button>
          </div>
          <div id="ce-plant"></div>
        </div>

        <div class="ce-section">
          <div class="ce-section-head">
            <span>回收（payoff）</span>
            <button class="btn-ghost tiny" data-add="payoff">+ 添加</button>
          </div>
          <div id="ce-payoff"></div>
        </div>

        <div class="ce-section">
          <div class="ce-section-head">
            <span>禁止（forbid）</span>
            <button class="btn-ghost tiny" data-add="forbid">+ 添加</button>
          </div>
          <div id="ce-forbid"></div>
        </div>

        <div class="ce-section">
          <div class="ce-section-head">
            <span>行业注入（domain_inject）</span>
            <button class="btn-ghost tiny" data-add="domain_inject">+ 添加</button>
          </div>
          <div id="ce-domain_inject"></div>
        </div>
      </div>
      <div class="modal-actions">
        <button class="btn-ghost" data-ce-cancel>取消</button>
        <button class="btn" data-ce-save>保存草稿</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  // ============ 渲染各类列表 ============
  const renderScenes = () => {
    document.getElementById('ce-scenes').innerHTML = draft.scenes.map((s, i) => `
      <div class="ce-item ce-item-multi">
        <div class="ce-item-main">
          <input type="text" placeholder="地点（如：星途南区办公室）"
                 value="${escapeHtml(s.place || '')}"
                 data-idx="${i}" data-k="place" />
          <textarea placeholder="目标（如：接到华晟立项通知）" rows="2"
                    data-idx="${i}" data-k="goal">${escapeHtml(s.goal || '')}</textarea>
        </div>
        <button class="ce-del" data-del="scenes" data-idx="${i}">×</button>
      </div>
    `).join('') || '<div class="ce-empty">暂无场景</div>';
  };

  const renderStrList = (key, placeholder) => {
    const el = document.getElementById('ce-' + key);
    if (!el) return;
    el.innerHTML = (draft[key] || []).map((v, i) => `
      <div class="ce-item">
        <input type="text" value="${escapeHtml(v)}"
               placeholder="${escapeHtml(placeholder)}"
               data-list="${key}" data-idx="${i}" />
        <button class="ce-del" data-del="${key}" data-idx="${i}">×</button>
      </div>
    `).join('') || '<div class="ce-empty">暂无</div>';
  };

  const renderObjList = (key, fields) => {
    const el = document.getElementById('ce-' + key);
    if (!el) return;
    el.innerHTML = (draft[key] || []).map((item, i) => `
      <div class="ce-item ce-item-multi">
        <div class="ce-item-main">
          ${fields.map((f) => `
            <input type="text" value="${escapeHtml(item[f.k] || '')}"
                   placeholder="${escapeHtml(f.p)}"
                   data-obj="${key}" data-idx="${i}" data-k="${f.k}" />
          `).join('')}
        </div>
        <button class="ce-del" data-del="${key}" data-idx="${i}">×</button>
      </div>
    `).join('') || '<div class="ce-empty">暂无</div>';
  };

  const renderAll = () => {
    renderScenes();
    renderStrList('must_advance', '必须推进的一句话');
    renderObjList('plant', [
      { k: 'scheme', p: 'Scheme ID（如 S1）' },
      { k: 'evidence', p: '要埋进正文的证据' },
    ]);
    renderObjList('payoff', [
      { k: 'scheme', p: 'Scheme ID' },
      { k: 'note', p: '回收说明' },
    ]);
    renderStrList('forbid', '禁止出现的内容');
    renderStrList('domain_inject', '行业约束（术语 / 流程 / 年代）');

    // 绑定所有 input 的 oninput
    overlay.querySelectorAll('[data-k]').forEach((el) => {
      el.oninput = () => {
        const idx = parseInt(el.dataset.idx, 10);
        const k = el.dataset.k;
        if (el.dataset.list) {
          draft[k][idx] = el.value;
        } else if (el.dataset.obj) {
          draft[el.dataset.obj][idx][k] = el.value;
        } else {
          draft.scenes[idx][k] = el.value;
        }
      };
    });
    overlay.querySelectorAll('[data-list]').forEach((el) => {
      el.oninput = () => {
        const idx = parseInt(el.dataset.idx, 10);
        draft[el.dataset.list][idx] = el.value;
      };
    });
    // 删除
    overlay.querySelectorAll('[data-del]').forEach((el) => {
      el.onclick = () => {
        const key = el.dataset.del;
        const idx = parseInt(el.dataset.idx, 10);
        draft[key].splice(idx, 1);
        renderAll();
      };
    });
  };

  // + 添加按钮
  overlay.querySelectorAll('[data-add]').forEach((el) => {
    el.onclick = () => {
      const key = el.dataset.add;
      if (key === 'scenes') {
        draft.scenes.push({
          idx: draft.scenes.length + 1,
          place: '',
          goal: '',
        });
      } else if (key === 'plant') {
        draft.plant.push({ scheme: '', evidence: '' });
      } else if (key === 'payoff') {
        draft.payoff.push({ scheme: '', note: '' });
      } else {
        draft[key].push('');
      }
      renderAll();
    };
  });

  renderAll();

  // ============ 关闭 / 保存 ============
  const close = () => {
    overlay.classList.add('closing');
    setTimeout(() => overlay.remove(), 150);
  };

  overlay.querySelector('[data-ce-cancel]').onclick = close;
  overlay.onclick = (e) => { if (e.target === overlay) close(); };
  const onKey = (e) => {
    if (e.key === 'Escape') {
      document.removeEventListener('keydown', onKey);
      close();
    }
  };
  document.addEventListener('keydown', onKey);

  overlay.querySelector('[data-ce-save]').onclick = async () => {
    // 从 input 里读最新的 top-level 字段
    draft.pov_character_id = document.getElementById('ce-pov').value.trim();
    draft.word_target = parseInt(document.getElementById('ce-words').value, 10) || 3500;
    draft.tone = document.getElementById('ce-tone').value.trim();

    try {
      setStatus('保存合同…');
      await api.chapters.contract.save(chapterNo, draft);
      toast('合同已保存为草稿', 'success');
      close();
      // 重新加载本章
      const [chapRes, issueRes] = await Promise.all([
        api.chapters.get(chapterNo),
        api.chapters.issues(chapterNo),
      ]);
      local.chapter = chapRes.chapter;
      local.contract = chapRes.contract;
      local.issues = issueRes.issues || [];
      drawMain();
      drawInspector();
      setStatus('就绪');
    } catch (e) {
      toast('保存失败：' + e.message, 'error');
      setStatus('就绪');
    }
  };
}
// web/js/views/bible.js
import { api } from '../api.js';
import { escapeHtml, setStatus, toast } from '../store.js';

let state = {
  tab: 'rules',
  data: { rules: [], characters: [], locations: [] },
  dirty: false,
};

export async function renderBible(main) {
  setStatus('加载设定圣经…');
  main.innerHTML = '<div class="empty">加载中…</div>';
  try {
    const d = await api.bible.get();
    state.data = {
      rules: d.rules || [],
      characters: d.characters || [],
      locations: d.locations || [],
    };
  } catch (e) {
    main.innerHTML = `<div class="empty">加载失败：${escapeHtml(e.message)}</div>`;
    return;
  }
  draw(main);
}

function draw(main) {
  main.innerHTML = `
    <h1 class="page-title">
      设定圣经
      <div class="page-actions">
        <button class="btn-ghost" id="btn-refresh">刷新</button>
        <button class="btn ${state.dirty ? '' : 'hidden'}" id="btn-save">保存全部</button>
      </div>
    </h1>

    <div class="row mb-2" style="border-bottom:1px solid var(--border);padding-bottom:8px;gap:24px;">
      ${tab('rules', '规则', state.data.rules.length)}
      ${tab('characters', '角色', state.data.characters.length)}
      ${tab('locations', '地点', state.data.locations.length)}
    </div>

    <div id="bible-body"></div>
  `;

  document.querySelectorAll('.bible-tab').forEach((el) => {
    el.onclick = () => { state.tab = el.dataset.tab; draw(main); };
  });

  document.getElementById('btn-refresh').onclick = () => renderBible(main);
  const saveBtn = document.getElementById('btn-save');
  if (saveBtn) {
    saveBtn.onclick = () => saveAll(main);
  }

  const body = document.getElementById('bible-body');
  if (state.tab === 'rules') drawRules(body);
  else if (state.tab === 'characters') drawCharacters(body);
  else drawLocations(body);

  setStatus('就绪');
}

function tab(key, label, n) {
  const active = state.tab === key;
  return `<a class="bible-tab ${active ? '' : 'muted'}"
             data-tab="${key}"
             style="cursor:pointer;font-weight:${active ? 600 : 400};
                    color:${active ? 'var(--text)' : 'var(--text-dim)'};
                    border-bottom:2px solid ${active ? 'var(--primary)' : 'transparent'};
                    padding-bottom:6px;">
             ${label} <span class="muted small">${n}</span>
           </a>`;
}

// ---------------------------------------------------------- rules
function drawRules(body) {
  body.innerHTML = `
    <div class="card">
      <div class="card-title">
        世界规则
        <button class="btn-ghost" id="btn-add-rule">+ 新增</button>
      </div>
      <div id="rule-list"></div>
    </div>
  `;
  const list = document.getElementById('rule-list');
  const render = () => {
    list.innerHTML = state.data.rules.map((r, i) => `
      <div class="field" style="border-bottom:1px solid var(--border);padding-bottom:12px;">
        <div class="row-between mb-1">
          <div class="row">
            <span class="badge ${r.hard ? 'blocker' : 'info'}">${r.hard ? '硬' : '软'}</span>
            <input type="text" value="${escapeHtml(r.category || '')}"
                   data-idx="${i}" data-k="category"
                   style="width:120px;padding:3px 8px;background:transparent;border:1px solid var(--border);border-radius:4px;font-size:11px;" />
          </div>
          <button class="btn-ghost" data-del="${i}" style="color:var(--blocker);">删除</button>
        </div>
        <textarea data-idx="${i}" data-k="statement" rows="2">${escapeHtml(r.statement || '')}</textarea>
      </div>
    `).join('') || '<div class="empty">暂无规则</div>';

    list.querySelectorAll('input, textarea').forEach((el) => {
      el.oninput = () => {
        const i = +el.dataset.idx;
        state.data.rules[i][el.dataset.k] = el.value;
        state.dirty = true;
        const btn = document.getElementById('btn-save');
        if (btn) btn.classList.remove('hidden');
      };
    });
    list.querySelectorAll('[data-del]').forEach((el) => {
      el.onclick = () => {
        state.data.rules.splice(+el.dataset.del, 1);
        state.dirty = true;
        render();
      };
    });
  };
  render();
  document.getElementById('btn-add-rule').onclick = () => {
    state.data.rules.push({ category: '规则', statement: '', hard: 1 });
    state.dirty = true;
    render();
  };
}

// ---------------------------------------------------------- characters
function drawCharacters(body) {
  body.innerHTML = `
    <div class="card">
      <div class="card-title">
        角色卡
        <button class="btn-ghost" id="btn-add-char">+ 新增</button>
      </div>
      <div id="char-list"></div>
    </div>
  `;
  const list = document.getElementById('char-list');
  const render = () => {
    list.innerHTML = state.data.characters.map((c, i) => `
      <div class="card" style="background:var(--panel-2);margin-bottom:12px;">
        <div class="grid-2">
          <div class="field">
            <label>姓名</label>
            <input type="text" value="${escapeHtml(c.name || '')}" data-idx="${i}" data-k="name" />
          </div>
          <div class="field">
            <label>角色定位</label>
            <input type="text" value="${escapeHtml(c.role || '')}" data-idx="${i}" data-k="role"
                   placeholder="如：主角 / 反派 / 配角" />
          </div>
          <div class="field">
            <label>别名（逗号分隔）</label>
            <input type="text" value="${escapeHtml((c.aliases || []).join('，'))}"
                   data-idx="${i}" data-k="aliases" />
          </div>
          <div class="field">
            <label>声口（一句话）</label>
            <input type="text" value="${escapeHtml(c.voice || '')}" data-idx="${i}" data-k="voice"
                   placeholder="如：克制、市侩、冷硬" />
          </div>
          <div class="field" style="grid-column:1/3;">
            <label>特质（逗号分隔）</label>
            <input type="text" value="${escapeHtml((c.traits || []).join('，'))}"
                   data-idx="${i}" data-k="traits" />
          </div>
        </div>
        <button class="btn-ghost" data-del="${i}" style="color:var(--blocker);">删除此角色</button>
      </div>
    `).join('') || '<div class="empty">暂无角色</div>';

    list.querySelectorAll('input').forEach((el) => {
      el.oninput = () => {
        const i = +el.dataset.idx;
        const k = el.dataset.k;
        let v = el.value;
        if (k === 'aliases' || k === 'traits') {
          v = v.split(/[，,]/).map((s) => s.trim()).filter(Boolean);
        }
        state.data.characters[i][k] = v;
        state.dirty = true;
        const btn = document.getElementById('btn-save');
        if (btn) btn.classList.remove('hidden');
      };
    });
    list.querySelectorAll('[data-del]').forEach((el) => {
      el.onclick = () => {
        if (!confirm('删除此角色？')) return;
        state.data.characters.splice(+el.dataset.del, 1);
        state.dirty = true;
        render();
      };
    });
  };
  render();
  document.getElementById('btn-add-char').onclick = () => {
    state.data.characters.push({
      name: '新角色', role: '', aliases: [], voice: '',
      traits: [], relations: {}, abilities: [], status: 'alive',
    });
    state.dirty = true;
    render();
  };
}

// ---------------------------------------------------------- locations
function drawLocations(body) {
  body.innerHTML = `
    <div class="card">
      <div class="card-title">
        地点
        <button class="btn-ghost" id="btn-add-loc">+ 新增</button>
      </div>
      <div id="loc-list"></div>
    </div>
  `;
  const list = document.getElementById('loc-list');
  const render = () => {
    list.innerHTML = state.data.locations.map((l, i) => `
      <div class="card" style="background:var(--panel-2);margin-bottom:12px;">
        <div class="grid-2">
          <div class="field">
            <label>名称</label>
            <input type="text" value="${escapeHtml(l.name || '')}" data-idx="${i}" data-k="name" />
          </div>
          <div class="field">
            <label>区域</label>
            <input type="text" value="${escapeHtml(l.region || '')}" data-idx="${i}" data-k="region" />
          </div>
          <div class="field" style="grid-column:1/3;">
            <label>别名（逗号分隔）</label>
            <input type="text" value="${escapeHtml((l.aliases || []).join('，'))}"
                   data-idx="${i}" data-k="aliases" />
          </div>
        </div>
        <button class="btn-ghost" data-del="${i}" style="color:var(--blocker);">删除</button>
      </div>
    `).join('') || '<div class="empty">暂无地点</div>';

    list.querySelectorAll('input').forEach((el) => {
      el.oninput = () => {
        const i = +el.dataset.idx;
        const k = el.dataset.k;
        let v = el.value;
        if (k === 'aliases') v = v.split(/[，,]/).map((s) => s.trim()).filter(Boolean);
        state.data.locations[i][k] = v;
        state.dirty = true;
        const btn = document.getElementById('btn-save');
        if (btn) btn.classList.remove('hidden');
      };
    });
    list.querySelectorAll('[data-del]').forEach((el) => {
      el.onclick = () => {
        state.data.locations.splice(+el.dataset.del, 1);
        state.dirty = true;
        render();
      };
    });
  };
  render();
  document.getElementById('btn-add-loc').onclick = () => {
    state.data.locations.push({ name: '新地点', region: '', aliases: [], traits: [] });
    state.dirty = true;
    render();
  };
}

// ---------------------------------------------------------- save
async function saveAll(main) {
  try {
    await api.bible.put(state.data);
    state.dirty = false;
    toast('已保存', 'success');
    draw(main);
  } catch (e) {
    toast('保存失败：' + e.message, 'error');
  }
}
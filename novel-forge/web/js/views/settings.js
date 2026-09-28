// web/js/views/settings.js
import { api } from '../api.js';
import { escapeHtml, setStatus, toast } from '../store.js';

const ROLES = [
  { key: 'writer', label: '写手', desc: '按合同写正文' },
  { key: 'continuity', label: '审校', desc: '语义一致性检查' },
  { key: 'extractor', label: '抽取', desc: '从正文抽事实（建议用便宜模型）' },
  { key: 'arbiter', label: '裁决', desc: '对问题给处置意见' },
  { key: 'editor', label: '编辑', desc: '按裁决修订正文' },
  { key: 'curator', label: '台账', desc: '验收后更新权威状态' },
];

let local = {
  settings: {},     // role -> {account_id, model_id}
  options: null,    // /api/llm/options
  models: {},       // account_id -> models[]
};

export async function renderSettings(main) {
  setStatus('加载设置…');
  main.innerHTML = '<div class="empty">加载中…</div>';

  const [settingsRes, optionsRes] = await Promise.all([
    api.settings.llmGet().catch(() => ({ settings: {} })),
    api.llm.options('text').catch(() => ({
      source: 'none', hint: '未配置', accounts: [], configured: false,
    })),
  ]);

  local.settings = settingsRes.settings || {};
  local.options = optionsRes;

  // 预加载所有账号的模型列表
  if (optionsRes.accounts && optionsRes.accounts.length) {
    for (const acc of optionsRes.accounts) {
      try {
        const m = await api.llm.models(acc.account_id, 'text');
        local.models[acc.account_id] = m.models || [];
      } catch { local.models[acc.account_id] = []; }
    }
  }

  draw(main);
  setStatus('就绪');
}

function draw(main) {
  const o = local.options || {};
  const srcBadge = {
    yaml: '<span class="badge ok">已下发</span>',
    env: '<span class="badge warning">桌面词元</span>',
    none: '<span class="badge blocker">未配置</span>',
  }[o.source] || '';

  main.innerHTML = `
    <h1 class="page-title">
      设置
    </h1>

    <div class="card">
      <div class="card-title">
        模型
        <span class="meta">${srcBadge} ${escapeHtml(o.hint || '')}</span>
      </div>
      <div class="muted small mb-2">
        Key 只在 HelloMe「模型 API」录入并下发。本页只选账号与模型，不采集 Key。
      </div>
      ${!o.accounts || !o.accounts.length ? `
        <div class="empty">
          ${o.source === 'env'
            ? '当前使用桌面词元，无需选择。仅文本生成可用。'
            : '请到 HelloMe → 模型 API 添加账号并下发到本机'}
        </div>
      ` : `
        <div id="role-list">
          ${ROLES.map((r) => roleRow(r)).join('')}
        </div>
      `}
    </div>

    <div class="card">
      <div class="card-title">写作偏好</div>
      <div class="muted small">（暂未开放，下一版支持）</div>
    </div>
  `;

  if (o.accounts && o.accounts.length) {
    main.querySelectorAll('[data-role-account]').forEach((el) => {
      el.onchange = () => {
        const role = el.dataset.roleAccount;
        const accId = el.value ? parseInt(el.value, 10) : null;
        local.settings[role] = local.settings[role] || {};
        local.settings[role].account_id = accId;
        local.settings[role].model_id = null;
        saveSetting(role);
        draw(main);
      };
    });
    main.querySelectorAll('[data-role-model]').forEach((el) => {
      el.onchange = () => {
        const role = el.dataset.roleModel;
        local.settings[role] = local.settings[role] || {};
        local.settings[role].model_id = el.value || null;
        saveSetting(role);
      };
    });
  }
}

function roleRow(r) {
  const s = local.settings[r.key] || {};
  const accounts = local.options.accounts || [];
  const accId = s.account_id;
  const models = accId != null ? (local.models[accId] || []) : [];

  return `
    <div class="field" style="border-bottom:1px solid var(--border);padding-bottom:14px;">
      <div class="row-between mb-1">
        <div>
          <strong>${escapeHtml(r.label)}</strong>
          <span class="muted small" style="margin-left:8px;">${escapeHtml(r.desc)}</span>
        </div>
      </div>
      <div class="grid-2">
        <div>
          <label class="small muted">账号</label>
          <select data-role-account="${r.key}">
            <option value="">— 未选择 —</option>
            ${accounts.map((a) => `
              <option value="${a.account_id}" ${accId === a.account_id ? 'selected' : ''}>
                ${escapeHtml(a.account_name || a.provider_name || a.account_id)}
                · ${escapeHtml(a.provider_code || '')}
              </option>
            `).join('')}
          </select>
        </div>
        <div>
          <label class="small muted">模型</label>
          <select data-role-model="${r.key}" ${!accId ? 'disabled' : ''}>
            <option value="">— 未选择 —</option>
            ${models.map((m) => `
              <option value="${escapeHtml(m.id)}" ${s.model_id === m.id ? 'selected' : ''}>
                ${escapeHtml(m.name || m.id)}${m.type === 'multimodal' ? ' · 多模态' : ''}
              </option>
            `).join('')}
          </select>
        </div>
      </div>
    </div>
  `;
}

async function saveSetting(role) {
  try {
    await api.settings.llmPut({
      role,
      account_id: local.settings[role]?.account_id ?? null,
      model_id: local.settings[role]?.model_id ?? null,
    });
    toast(`${role} 已保存`, 'success', 1500);
  } catch (e) {
    toast('保存失败：' + e.message, 'error');
  }
}
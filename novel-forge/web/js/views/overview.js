// web/js/views/overview.js
import { api } from '../api.js';
import { store, escapeHtml, fmtDate, setStatus } from '../store.js';

const STATUS_LABEL = {
  draft: '草稿',
  reviewing: '待验收',
  blocked: '阻断',
  accepted: '已验收',
};

export async function renderOverview(main) {
  setStatus('加载总览…');
  main.innerHTML = '<div class="empty">加载中…</div>';

  const [projRes, chapRes, schemeRes, llmRes, issueAgg] = await Promise.all([
    api.project.get().catch(() => ({})),
    api.chapters.list().catch(() => ({ chapters: [] })),
    api.schemes.list().catch(() => ({ schemes: [] })),
    api.llm.options('text').catch(() => ({ source: 'none', hint: '未配置' })),
    api.chapters.list().then(async (r) => {
      const out = [];
      for (const c of (r.chapters || [])) {
        try {
          const d = await api.chapters.issues(c.chapter_no);
          const open = (d.issues || []).filter((i) => i.status === 'open');
          if (open.length) out.push({ chapter_no: c.chapter_no, issues: open });
        } catch { /* ignore */ }
      }
      return out;
    }).catch(() => []),
  ]);

  const project = projRes.project || {};
  const chapters = chapRes.chapters || [];
  const schemes = schemeRes.schemes || [];
  const llm = llmRes;

  const total = 36;
  const accepted = chapters.filter((c) => c.status === 'accepted').length;
  const reviewing = chapters.filter((c) => c.status === 'reviewing').length;
  const blocked = chapters.filter((c) => c.status === 'blocked').length;

  // 当前进度 = 已完成（非 pending）的章节中最大的章节号，没有就按第 1 章算
  const completedChapters = chapters.filter((c) => c.status && c.status !== 'pending');
  const currentChapter = completedChapters.length
    ? Math.max(...completedChapters.map((c) => c.chapter_no))
    : 1;

  // 活跃的局 = 已埋下、未收束
  const activeSchemes = schemes.filter((s) => {
    const planted = s.chapter_planted || 0;
    const resolved = s.chapter_resolved;
    return planted <= currentChapter && (resolved == null || resolved > currentChapter);
  });
  const openBlockers = issueAgg.reduce(
    (n, x) => n + x.issues.filter((i) => i.severity === 'blocker').length, 0
  );
  const openWarnings = issueAgg.reduce(
    (n, x) => n + x.issues.filter((i) => i.severity === 'warning').length, 0
  );

  const llmClass = llm.source === 'yaml' ? 'ok'
                 : llm.source === 'env' ? 'warning'
                 : 'blocker';

    main.innerHTML = `
    <h1 class="page-title">
      总览
      <div class="page-actions">
        <button class="btn" id="btn-go-studio">进入章节工作台</button>
      </div>
    </h1>

    <div class="card guide-card">
      <div class="card-title" style="margin-bottom:8px;">
        这是「织章」— 多 Agent 一致性写作引擎
      </div>
      <div class="muted small mb-2">
        内置一份三幕 36 章的商战小说示例，用来看清整套流程。
        你可以把它当模板改写，也可以直接删掉写自己的故事。
      </div>
      <div class="guide-steps">
        <a class="guide-step" href="#bible">
          <div class="step-num">1</div>
          <div class="step-body">
            <div class="step-title">看设定圣经</div>
            <div class="step-desc">世界规则 / 角色卡 / 地点 / 道具，分镜会用到</div>
          </div>
        </a>
        <a class="guide-step" href="#studio/1">
          <div class="step-num">2</div>
          <div class="step-body">
            <div class="step-title">跑通第 1 章</div>
            <div class="step-desc">冻结合同 → 生成草稿 → 处理一致性问题 → 验收</div>
          </div>
        </a>
        <a class="guide-step" href="#studio/1">
          <div class="step-num">3</div>
          <div class="step-body">
            <div class="step-title">给第 1 章配分镜</div>
            <div class="step-desc">章节工作台 → 分镜 tab → 生成 5–15 张分镜草图</div>
          </div>
        </a>
        <a class="guide-step" href="#outline">
          <div class="step-num">4</div>
          <div class="step-body">
            <div class="step-title">看整本大纲</div>
            <div class="step-desc">36 章的骨架，可以整体替换成自己的故事</div>
          </div>
        </a>
      </div>
      <div class="muted small" style="margin-top:12px;">
        数据只落本机 <code>HELLOME_SKILL_DATA_DIR</code>，不采集 Key。
        想写自己的故事：把 <code>upstream/seed/</code> 下的 8 个 JSON 替换成自己的即可。
      </div>
    </div>

    <div class="grid-3">
      <div class="card">
        <div class="card-title">项目</div>
        <div class="mb-1"><strong>${escapeHtml(project.title || '未命名作品')}</strong></div>
        <div class="muted small">类型：${escapeHtml(project.genre || '—')}</div>
        <div class="muted small">视角：${escapeHtml(project.pov_mode || 'third_limited')}</div>
        <div class="muted small">目标章节：${total}</div>
        <div class="mt-2">
          <button class="btn-ghost" id="btn-edit-project">编辑项目信息</button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">写作进度</div>
        <div style="font-size:28px;font-weight:600;">${accepted} <span class="muted" style="font-size:14px;">/ ${total}</span></div>
        <div class="progress-bar mt-2"><div class="progress-fill" style="width:${(accepted / total) * 100}%"></div></div>
        <div class="mt-2 small muted">
          待验收 ${reviewing} · 阻断 ${blocked} · 未开始 ${total - accepted - reviewing - blocked}
        </div>
      </div>

      <div class="card">
        <div class="card-title">LLM</div>
        <div class="row mb-1">
          <span class="status-dot ${llmClass}">●</span>
          <span>${escapeHtml(llm.hint || '未配置')}</span>
        </div>
        <div class="muted small">来源：${escapeHtml(llm.source || 'none')}</div>
        <div class="mt-2">
          <button class="btn-ghost" id="btn-go-settings">去设置</button>
        </div>
      </div>
    </div>

    <div class="grid-2 mt-2">
      <div class="card">
        <div class="card-title">
          未收束的局
          <span class="meta">${activeSchemes.length} 个 · 第 ${currentChapter} 章时</span>
        </div>
        ${activeSchemes.length ? `
          <ul style="margin:0;padding-left:18px;">
            ${activeSchemes.slice(0, 8).map((s) => `
              <li>
                <span class="badge primary">${escapeHtml(s.id)}</span>
                ${escapeHtml(s.name)}
                <span class="muted small">· ${escapeHtml(s.status)}</span>
              </li>
            `).join('')}
          </ul>
        ` : '<div class="empty">没有活跃中的局</div>'}
      </div>

      <div class="card">
        <div class="card-title">
          待处理问题
          <span class="meta">
            ${openBlockers ? `<span class="badge blocker">阻断 ${openBlockers}</span>` : ''}
            ${openWarnings ? `<span class="badge warning">警告 ${openWarnings}</span>` : ''}
          </span>
        </div>
        ${issueAgg.length ? `
          <ul style="margin:0;padding-left:18px;">
            ${issueAgg.slice(0, 8).map((x) => `
              <li>
                <a href="#studio/${x.chapter_no}">第 ${x.chapter_no} 章</a>
                <span class="muted small">· ${x.issues.length} 条</span>
              </li>
            `).join('')}
          </ul>
        ` : '<div class="empty">没有待处理问题</div>'}
      </div>
    </div>

    <div class="card mt-2">
      <div class="card-title">最近章节</div>
      <table style="width:100%;border-collapse:collapse;">
        <thead>
          <tr style="text-align:left;color:var(--text-dim);font-size:11px;">
            <th style="padding:6px 0;">章</th>
            <th>标题</th>
            <th>字数</th>
            <th>状态</th>
            <th>更新时间</th>
          </tr>
        </thead>
        <tbody>
          ${(() => {
            const withContent = chapters
              .filter((c) => c.updated_at && (c.word_count > 0 || c.status !== 'pending'))
              .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
              .slice(0, 8);
            if (withContent.length === 0) {
              return '<tr><td colspan="5" class="empty">还没有写过任何章节</td></tr>';
            }
            return withContent.map((c) => `
              <tr style="border-top:1px solid var(--border);">
                <td style="padding:8px 0;">${c.chapter_no}</td>
                <td><a href="#studio/${c.chapter_no}">${escapeHtml(c.title || '—')}</a></td>
                <td class="muted">${c.word_count || 0}</td>
                <td><span class="badge ${c.status === 'accepted' ? 'ok' : c.status === 'blocked' ? 'blocker' : 'info'}">${STATUS_LABEL[c.status] || c.status}</span></td>
                <td class="muted small">${fmtDate(c.updated_at)}</td>
              </tr>
            `).join('');
          })()}
        </tbody>
      </table>
    </div>
  `;

  document.getElementById('btn-go-studio').onclick = () => { location.hash = '#studio'; };
  document.getElementById('btn-go-settings').onclick = () => { location.hash = '#settings'; };
  document.getElementById('btn-edit-project').onclick = () => editProject(project);
  setStatus('就绪');
}

async function editProject(project) {
  const title = prompt('作品标题', project.title || '');
  if (title === null) return;
  const genre = prompt('类型（如：商战 / 悬疑 / 科幻）', project.genre || '');
  if (genre === null) return;
  try {
    await api.project.update({ title, genre });
    location.reload();
  } catch (e) {
    const { alertDialog } = await import('../store.js');
    await alertDialog({ title: '保存失败', message: e.message });
  }
}
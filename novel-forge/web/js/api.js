// web/js/api.js
// 所有 fetch 用相对路径，打公共口。adapter 原样转发。

async function request(method, path, body) {
  const opts = {
    method,
    headers: { 'Accept': 'application/json' },
  };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new Error(`网络错误：${e.message}`);
  }
  const ct = res.headers.get('content-type') || '';
  if (!ct.includes('application/json')) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
  }
  const data = await res.json();
  if (data && data.ok === false) {
    throw new Error(data.error || '请求失败');
  }
  return data;
}

export const api = {
  // 基础
  hello: () => request('GET', '/api/hello'),
  project: {
    get: () => request('GET', '/api/project'),
    update: (patch) => request('PUT', '/api/project', patch),
  },
  bible: {
    get: () => request('GET', '/api/bible'),
    put: (data) => request('PUT', '/api/bible', data),
  },
  outline: {
    list: () => request('GET', '/api/outline'),
  },
  chapters: {
    list: () => request('GET', '/api/chapters'),
    get: (n) => request('GET', `/api/chapters/${n}`),
    save: (n, body_md) => request('PUT', `/api/chapters/${n}`, { body_md }),
    contract: {
      get: (n) => request('GET', `/api/chapters/${n}/contract`),
      save: (n, payload) => request('POST', `/api/chapters/${n}/contract`, payload),
      freeze: (n, payload) => request('POST', `/api/chapters/${n}/contract/freeze`, payload),
      unfreeze: (n) => request('POST', `/api/chapters/${n}/contract/unfreeze`, {}),
    },
    write: (n) => request('POST', `/api/chapters/${n}/write`, {}),
    recheck: (n) => request('POST', `/api/chapters/${n}/recheck`, {}),
    storyboard: {
      generate: (n, opts = {}) => request(
        'POST',
        `/api/chapters/${n}/storyboard`,
        { shot_count: opts.shotCount || 8, force_rerun: !!opts.forceRerun }
      ),
      get: (n) => request('GET', `/api/chapters/${n}/storyboard`),
      retry: (n, shotId) => request('POST', `/api/chapters/${n}/storyboard/${shotId}/retry`, {}),
    },
    accept: (n) => request('POST', `/api/chapters/${n}/accept`, {}),
    issues: (n) => request('GET', `/api/chapters/${n}/issues`),
  },
  jobs: {
    get: (id) => request('GET', `/api/jobs/${id}`),
  },
  issues: {
    resolve: (id, by) => request('POST', `/api/issues/${id}/resolve`, { resolved_by: by || 'manual' }),
  },
  schemes: {
    list: () => request('GET', '/api/schemes'),
  },
  domain: {
    get: (year) => request('GET', `/api/domain${year ? '?year=' + year : ''}`),
  },
  llm: {
    options: (kind) => request('GET', `/api/llm/options?kind=${kind || 'text'}`),
    models: (accountId, kind) => request(
      'GET',
      `/api/llm/models?account_id=${encodeURIComponent(accountId)}&kind=${kind || 'text'}`
    ),
  },
  settings: {
    llmGet: () => request('GET', '/api/settings/llm'),
    llmPut: (payload) => request('PUT', '/api/settings/llm', payload),
  },
  export: (fmt) => request('POST', '/api/export', { format: fmt || 'md' }),
};

// 轮询任务，直到 done / failed / 超时
export async function pollJob(taskId, onTick, opts = {}) {
  const interval = opts.interval || 1500;
  const timeout = opts.timeout || 15 * 60 * 1000;
  const t0 = Date.now();
  while (true) {
    if (Date.now() - t0 > timeout) {
      throw new Error('任务超时');
    }
    const data = await api.jobs.get(taskId);
    const job = data.job || {};
    if (onTick) onTick(job);
    if (job.status === 'done') return job;
    if (job.status === 'failed') {
      throw new Error(job.error || '任务失败');
    }
    await sleep(interval);
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
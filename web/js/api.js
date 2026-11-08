// REST + WebSocket client for the BIMCheck server.

async function j(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  if (!r.ok) {
    let detail = r.statusText;
    try { const d = await r.json(); detail = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail); } catch { /* ignore */ }
    const e = new Error(detail); e.status = r.status; throw e;
  }
  return r.status === 204 ? null : r.json();
}

export const api = {
  health: () => j('GET', '/api/health'),
  samples: () => j('GET', '/api/samples'),
  projects: () => j('GET', '/api/projects'),
  createProject: name => j('POST', '/api/projects', { name }),
  project: id => j('GET', `/api/projects/${id}`),
  rename: (id, name) => j('PATCH', `/api/projects/${id}`, { name }),
  deleteProject: id => j('DELETE', `/api/projects/${id}`),
  buildingModel: id => j('GET', `/api/projects/${id}/building-model`),
  drawingModel: id => j('GET', `/api/projects/${id}/drawing-model`),
  findings: id => j('GET', `/api/projects/${id}/findings`),
  context: id => j('GET', `/api/projects/${id}/context`),
  deriveContext: id => j('GET', `/api/projects/${id}/context/derive`),
  putContext: (id, ctx) => j('PUT', `/api/projects/${id}/context`, ctx),
  putOverrides: (id, ov) => j('PUT', `/api/projects/${id}/rule-overrides`, ov),
  recheck: id => j('POST', `/api/projects/${id}/recheck`),
  decision: (id, fid, decision, note) =>
    j('PUT', `/api/projects/${id}/findings/${encodeURIComponent(fid).replace(/%3A/gi, ':')}/decision`, { decision, note }),
  rules: () => j('GET', '/api/rules'),
  articles: () => j('GET', '/api/regulation/articles'),
  article: n => j('GET', `/api/regulation/articles/${n}`),
  glbUrl: (id, v) => `/api/projects/${id}/geometry.glb?v=${v || 0}`,
  reportUrl: (id, fmt) => `/api/projects/${id}/report.${fmt}`,
};

/** Multipart upload with progress. onProgress(fraction 0..1 | 'server'). Resolves with parsed JSON. */
export function upload(url, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress?.(e.loaded / e.total); };
    xhr.upload.onload = () => onProgress?.('server');
    xhr.onerror = () => reject(new Error('network error while uploading'));
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else {
        const e = new Error((body && (typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))) || xhr.statusText || `HTTP ${xhr.status}`);
        e.status = xhr.status; reject(e);
      }
    };
    const fd = new FormData();
    fd.append('file', file, file.name);
    xhr.send(fd);
  });
}

/** Reconnecting WebSocket. handlers: {event(ev), state('open'|'closed')} */
export function connectWS(pid, handlers) {
  let ws, closed = false, delay = 500, timer;
  const open = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/projects/${pid}`);
    ws.onopen = () => { delay = 500; handlers.state?.('open'); };
    ws.onmessage = m => { try { handlers.event?.(JSON.parse(m.data)); } catch { /* pong */ } };
    ws.onclose = () => {
      handlers.state?.('closed');
      if (!closed) timer = setTimeout(open, delay = Math.min(delay * 1.7, 8000));
    };
    ws.onerror = () => ws.close();
  };
  open();
  const ping = setInterval(() => { if (ws?.readyState === 1) ws.send('ping'); }, 25000);
  return { close() { closed = true; clearInterval(ping); clearTimeout(timer); ws?.close(); } };
}

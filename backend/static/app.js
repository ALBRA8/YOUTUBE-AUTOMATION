/* ============================================================
   YOUTUBE AUTOMATION v2.0 — Dashboard JS (vanilla, sin build)
   Vista Labsia mejorada: wizard 4 pasos + editor + fábrica + $0
   ============================================================ */
'use strict';

const S = {            // estado global
  view: 'home', theme: localStorage.getItem('yta-theme') || 'dark',
  demo: false, health: {}, styles: [], settings: {}, stats: {},
  projects: [], project: null, factory: null, ideas: [], avatars: [],
  chat: [], chatBusy: false,
  wizard: null, es: null,
};

const PLATFORMS = [
  { id: 'youtube',   emoji: '▶️', name: 'YouTube' },
  { id: 'tiktok',    emoji: '🎵', name: 'TikTok' },
  { id: 'instagram', emoji: '📷', name: 'Instagram' },
  { id: 'facebook',  emoji: '👤', name: 'Facebook' },
];

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* ── API ─────────────────────────────────────────────────── */
async function api(path, opts = {}) {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

function toast(msg, kind = '') {
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  t.textContent = msg;
  $('#toasts').appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

/* ── temas / navegación ──────────────────────────────────── */
function setTheme(t) {
  S.theme = t; localStorage.setItem('yta-theme', t);
  document.documentElement.dataset.theme = t;
  $('#theme-btn').textContent = t === 'dark' ? '🌙' : '☀️';
}

function nav(view) {
  S.view = view;
  $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.view === view));
  const views = { home: renderHome, create: renderCreate, projects: renderProjects,
                  factory: renderFactory, publish: renderPublish, settings: renderSettings,
                  project: renderProject, agent: renderAgent, avatars: renderAvatars,
                  trends: renderTrends };
  (views[view] || renderHome)();
}

/* ── vista: HOME ─────────────────────────────────────────── */
function renderHome() {
  const h = new Date().getHours();
  const hi = h < 12 ? 'Buenos días' : h < 19 ? 'Buenas tardes' : 'Buenas noches';
  $('#greet').innerHTML = `${hi} 👋<small id="greet-sub">Tu fábrica de videos con IA — todo listo</small>`;
  const st = S.stats;
  const spark = Array.from({length: 7}, (_, i) => `<i style="height:${18 + Math.sin(i * 1.7) * 10 + 8}%"></i>`).join('');
  $('#view').innerHTML = `
    ${S.demo ? `<div class="demo-banner">⚠️ Modo DEMO — no detecto el backend en :8000. Arranca el servidor o los datos son de muestra.</div>` : ''}
    <div class="agent-banner" onclick="nav('agent')">
      <div class="ab-ico">🤖</div>
      <div class="ab-txt"><b>NUEVO · Agente VÓRTICE</b>
        <small>Habla con tu fábrica: «crea un video sobre el imperio romano» y listo — el motor produce todo.</small></div>
      <button class="btn primary small">Probar →</button>
    </div>
    <div class="grid-kpis">
      <div class="card kpi"><div class="num">${st.today ?? 0}</div><div class="lbl">Videos hoy</div><div class="spark">${spark}</div></div>
      <div class="card kpi"><div class="num">${st.total ?? 0}</div><div class="lbl">Proyectos totales</div></div>
      <div class="card kpi"><div class="num">${st.ready ?? 0}</div><div class="lbl">Listos</div></div>
      <div class="card kpi"><div class="num">${st.published ?? 0}</div><div class="lbl">Publicados</div></div>
      <div class="card kpi"><div class="num">${st.minutes ?? 0}′</div><div class="lbl">Minutos generados</div></div>
      <div class="card kpi"><div class="num zero">$0.00</div><div class="lbl">Coste total · Labsia cobraría €${(st.total * 0.6).toFixed(2)}</div></div>
    </div>

    <h2 class="sec">✨ Crear nuevo video</h2>
    <div class="modes">
      <div class="card mode-card" onclick="nav('create');W.mode='script';W.step=1;renderCreate()"><div class="emoji">📜</div><h3>Desde Guion</h3><p>Pega tu guion y lo convertimos en video escena por escena.</p></div>
      <div class="card mode-card" onclick="nav('create');W.mode='idea';W.step=1;renderCreate()"><div class="emoji">💡</div><h3>Desde Idea</h3><p>Una frase basta. Gemini escribe el guion viral completo.</p></div>
      <div class="card mode-card" onclick="nav('create');W.mode='url';W.step=1;renderCreate()"><span class="tag">KILLER</span><div class="emoji">🔗</div><h3>Desde URL</h3><p>Pega un link viral de TikTok/YouTube y recrea su estructura con contenido 100% original.</p></div>
      <div class="card mode-card" onclick="nav('create');W.mode='audio';W.step=1;renderCreate()"><span class="tag new2">V2</span><div class="emoji">🎙️</div><h3>Desde Audio</h3><p>Sube tu voz: la transcribimos, estructuramos y producimos.</p></div>
    </div>

    <h2 class="sec">🗂️ Proyectos recientes <a class="hint" href="#" onclick="nav('projects');return false">ver todos →</a></h2>
    <div class="proj-grid">${renderProjectCards(S.projects.slice(0, 4))}</div>`;
}

function platformIcons(list) {
  return (list || []).map(id => {
    const p = PLATFORMS.find(x => x.id === id);
    return p ? `<span class="plat-badge" title="${p.name}">${p.emoji}</span>` : '';
  }).join('');
}

function renderProjectCards(list) {
  if (!list.length) return `<div class="card empty" style="grid-column:1/-1"><div class="big">🎬</div>Aún no hay proyectos. Crea tu primer video en 2 minutos.</div>`;
  return list.map(p => {
    const badge = p.status === 'ready' ? '<span class="badge ready">LISTO</span>'
      : p.status === 'published' ? '<span class="badge published">PUBLICADO</span>'
      : p.status === 'failed' ? '<span class="badge failed">ERROR</span>'
      : ['draft','queued'].includes(p.status) ? '<span class="badge draft">BORRADOR</span>'
      : '<span class="badge working">…' + esc(p.step_label || p.status) + '</span>';
    const thumb = p.thumbnail_url ? `/api/projects/${p.id}/thumbnail?v=${p.updated_at}` : '';
    const av = S.avatars.find(a => a.id === p.avatar_id);
    return `<div class="card proj-card" onclick="openProject('${p.id}')">
      ${thumb ? `<img class="thumb" src="${thumb}" loading="lazy">` : `<div class="thumb" style="display:grid;place-items:center;font-size:34px">🎞️</div>`}
      <div class="body"><b>${esc(p.title)}</b>
        <div class="meta">${badge}<span>${esc(p.format === 'short' ? '9:16 Short' : '16:9 Largo')}</span>${platformIcons(p.platforms)}${av ? `<span class="plat-badge" title="Avatar: ${esc(av.name)}">🎭</span>` : ''}</div>
      </div></div>`;
  }).join('');
}

/* ── vista: WIZARD CREAR (4 pasos como Labsia) ───────────── */
const W = { step: 1, mode: 'idea', format: 'short', style: 'auto',
            title: '', idea: '', script: '', url: '', custom: '', voice: '', tts: '',
            avatar: '', platforms: ['youtube', 'tiktok'],
            transitions: true, styleReference: true, subtitles: 'hormozi',
            cookies: '' };

function renderCreate() {
  const modes = [
    { id: 'idea',  emoji: '💡', t: 'Desde Idea',  d: 'Una frase → guion viral completo' },
    { id: 'script',emoji: '📜', t: 'Desde Guion', d: 'Ya tienes el guion escrito' },
    { id: 'url',   emoji: '🔗', t: 'Desde URL',   d: 'Recrea un viral de TikTok/YouTube (original)' },
    { id: 'audio', emoji: '🎙️', t: 'Desde Audio', d: 'Tu propia voz como narración' },
  ];
  const stepName = ['Modo', 'Formato', 'Estilo', 'Detalles'];
  let body = '';

  if (W.step === 1) {
    body = `<div class="modes">${modes.map(m => `
      <div class="card mode-card ${W.mode === m.id ? 'sel' : ''}" style="${W.mode === m.id ? 'border-color:var(--accent2)' : ''}"
           onclick="W.mode='${m.id}';renderCreate()">
        <div class="emoji">${m.emoji}</div><h3>${m.t}</h3><p>${m.d}</p></div>`).join('')}</div>`;
  }

  if (W.step === 2) {
    body = `<div class="format-row">
      <div class="format-card ${W.format === 'short' ? 'sel' : ''}" onclick="W.format='short';renderCreate()">
        <div class="shape s916"></div><b>Short / Vertical</b><small>9:16 · 1080×1920 · YouTube Shorts, TikTok, Reels</small></div>
      <div class="format-card ${W.format === 'long' ? 'sel' : ''}" onclick="W.format='long';renderCreate()">
        <div class="shape s169"></div><b>Largo / Horizontal</b><small>16:9 · 1920×1080 · YouTube clásico</small></div>
    </div>`;
  }

  if (W.step === 3) {
    body = `<div class="field" style="max-width:480px"><label>🎨 Estilo visual de las imágenes</label>
      <select onchange="W.style=this.value;renderCreate()">
        ${S.styles.map(s => `<option value="${s.id}" ${W.style === s.id ? 'selected' : ''}>${s.emoji} ${esc(s.name)} — ${esc(s.desc)}</option>`).join('')}
      </select>
      <small style="color:var(--muted);display:block;margin-top:8px">Auto deja que la IA elija una estética coherente según el tema — es lo recomendado. Los presets solo afinan el look de las imágenes: nunca tocan tu narración ni los subtítulos.</small></div>
    ${W.style === 'custom-studio' ? `<div class="field" style="margin-top:16px"><label>Describe tu estilo (en inglés, estilo de imagen)</label>
      <input type="text" value="${esc(W.custom)}" oninput="W.custom=this.value" placeholder="dark cinematic photography, moody fog..."></div>` : ''}`;
  }

  if (W.step === 4) {
    const f = W.mode === 'idea'
      ? `<div class="field"><label>💡 Tu idea (una frase basta)</label><input type="text" value="${esc(W.idea)}" oninput="W.idea=this.value" placeholder="El imperio romano explicado en 60s"></div>`
      : W.mode === 'script'
      ? `<div class="field"><label>📜 Pega tu guion</label><textarea rows="7" oninput="W.script=this.value" placeholder="Escribe o pega tu guion aquí...">${esc(W.script)}</textarea></div>`
      : W.mode === 'url'
      ? `<div class="field"><label>🔗 URL del video viral (TikTok / YouTube)</label><input type="text" value="${esc(W.url)}" oninput="W.url=this.value" placeholder="https://www.tiktok.com/@user/video/..."><small style="color:var(--muted);display:block;margin-top:6px">Analizamos su estructura y creamos una versión 100% original. No copiamos contenido.</small></div>`
      : `<div class="field"><label>🎙️ Grabación de voz (mp3/wav/m4a)</label><input type="file" id="audio-file" accept="audio/*"></div>`;
    body = f + `
      <div class="row">
        <div class="field"><label>🎭 Avatar (personaje consistente)</label>
          <select onchange="W.avatar=this.value">
            <option value="">— sin avatar —</option>
            ${S.avatars.map(a => `<option value="${a.id}" ${W.avatar === a.id ? 'selected' : ''}>${esc(a.name)}${a.voice ? ' · ' + esc(voiceName(a.voice)) : ''}</option>`).join('')}
          </select>
          ${S.avatars.length ? '' : '<small style="color:var(--muted);display:block;margin-top:4px">Crea personajes en la pestaña 🎭 Avatares</small>'}</div>
        <div class="field"><label>Voz (opcional, la del avatar manda si no eliges)</label>
          <select onchange="W.tts=this.value">
            <option value="">edge-tts · Salomé 🇨🇴 (gratis ilimitado)</option>
            <option value="gemini" ${S.health.gemini ? '' : 'disabled'}>Gemini TTS · Fenrir 🎖️ (premium)</option>
          </select></div>
      </div>
      <div class="field"><label>📡 Plataformas destino</label>
        <div class="plats">${PLATFORMS.map(p => `
          <label class="plat-check ${W.platforms.includes(p.id) ? 'on' : ''}">
            <input type="checkbox" ${W.platforms.includes(p.id) ? 'checked' : ''}
              onchange="W.platforms = this.checked ? [...new Set([...W.platforms, '${p.id}'])] : W.platforms.filter(x => x !== '${p.id}'); this.closest('.plat-check').classList.toggle('on', this.checked)">
            ${p.emoji} ${p.name}
          </label>`).join('')}</div>
        <small style="color:var(--muted);display:block;margin-top:4px">YouTube se publica directo con tu canal (OAuth). Para TikTok/IG/FB descarga el MP4 9:16 y súbelo — te preparamos el kit en 📺 Publicar.</small>
      </div>
      <div class="field"><label>🎬 Producción</label>
        <div class="plats">
          <label class="plat-check ${W.transitions ? 'on' : ''}"><input type="checkbox" ${W.transitions ? 'checked' : ''}
            onchange="W.transitions = this.checked; this.closest('.plat-check').classList.toggle('on', this.checked)">🎞️ Transiciones suaves (xfade)</label>
          <label class="plat-check ${W.styleReference ? 'on' : ''}"><input type="checkbox" ${W.styleReference ? 'checked' : ''}
            onchange="W.styleReference = this.checked; this.closest('.plat-check').classList.toggle('on', this.checked)">🎨 Estilo consistente entre escenas</label>
        </div>
        <div style="display:flex;gap:10px;margin-top:10px;flex-wrap:wrap">
          <div style="flex:1;min-width:180px"><label style="font-size:12px;color:var(--muted)">Estilo de subtítulos</label>
            <select onchange="W.subtitles=this.value">
              <option value="hormozi" ${W.subtitles === 'hormozi' ? 'selected' : ''}>Hormozi · amarillo gigante</option>
              <option value="tiktok" ${W.subtitles === 'tiktok' ? 'selected' : ''}>TikTok · blanco clásico</option>
              <option value="karaoke" ${W.subtitles === 'karaoke' ? 'selected' : ''}>Karaoke · verde lima</option>
            </select></div>
          ${W.mode === 'url' ? `<div style="flex:1;min-width:180px"><label style="font-size:12px;color:var(--muted)">Cookies del navegador (anti-bloqueo viral)</label>
            <select onchange="W.cookies=this.value">
              <option value="" ${!W.cookies ? 'selected' : ''}>— sin cookies —</option>
              ${['chrome','firefox','edge','brave'].map(c => `<option value="${c}" ${W.cookies === c ? 'selected' : ''}>${c}</option>`).join('')}
            </select></div>` : ''}
        </div>
        <small style="color:var(--muted);display:block;margin-top:6px">El modo URL mide la originalidad del guion (solape de 5-gramas contra el viral) y reescribe solo si copia.</small>
      </div>
      <div class="field"><label>Título interno (máx 60)</label>
        <input type="text" maxlength="60" value="${esc(W.title)}" oninput="W.title=this.value" placeholder="solo referencia, lo genera la IA si lo dejas vacío"></div>`;
  }

  $('#view').innerHTML = `<div class="wizard">
    <div class="steps">${stepName.map((n, i) => `
      <div class="step ${i + 1 === W.step ? 'active' : i + 1 < W.step ? 'done' : ''}">${i + 1 < W.step ? '✓ ' : ''}${i + 1}. ${n}</div>`).join('')}</div>
    <div class="card">${body}</div>
    <div class="wizard-nav">
      <button class="btn ghost" onclick="W.step--;W.step<1?nav('home'):renderCreate()">← Atrás</button>
      <button class="btn primary" id="wiz-next">${W.step === 4 ? '🚀 Crear video' : 'Continuar →'}</button>
    </div></div>`;

  $('#wiz-next').onclick = () => {
    if (W.step === 1) { W.step = 2; renderCreate(); return; }
    if (W.step === 2) { W.step = 3; renderCreate(); return; }
    if (W.step === 3) { W.step = 4; renderCreate(); return; }
    createProject();
  };
}

async function createProject() {
  if (guardDemo()) return;
  if (W.mode === 'idea' && !W.idea.trim()) return toast('Escribe una idea primero', 'err');
  if (W.mode === 'script' && !W.script.trim()) return toast('Pega tu guion primero', 'err');
  if (W.mode === 'url' && !W.url.trim()) return toast('Pega la URL primero', 'err');

  let audioPath = null;
  if (W.mode === 'audio') {
    const file = $('#audio-file')?.files?.[0];
    if (!file) return toast('Selecciona tu archivo de audio', 'err');
    const fd = new FormData(); fd.append('file', file);
    const r = await fetch('/api/import/audio', { method: 'POST', body: fd });
    if (!r.ok) return toast('Error subiendo audio', 'err');
    audioPath = (await r.json()).path;
  }

  try {
    const body = { mode: W.mode, style: W.style, format: W.format,
                   title: W.title || null, voice: W.voice || null,
                   tts_provider: W.tts || null,
                   avatar_id: W.avatar || null,
                   platforms: W.platforms.length ? W.platforms : ['youtube'],
                   transitions: W.transitions, style_reference: W.styleReference,
                   subtitle_style: W.subtitles,
                   cookies_from_browser: W.cookies || null };
    if (W.mode === 'idea') body.idea = W.idea;
    if (W.mode === 'script') { body.script = W.script; body.title = W.title || W.script.slice(0, 50); }
    if (W.mode === 'url') body.url = W.url;
    if (W.style === 'custom-studio') body.custom_style_prompt = W.custom;
    const p = await api('/projects', { method: 'POST', body });
    if (audioPath) {
      await fetch('/api/projects/' + p.id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meta_patch: { audio_path: audioPath } }) });
    }
    toast('Proyecto creado. ¡A producir! 🎬', 'ok');
    startJob(p.id);
  } catch (e) { toast(e.message, 'err'); }
}

/* ── progreso en vivo (SSE) ──────────────────────────────── */
const STEP_LABEL = { importing: '📥 Importando material', scripting: '🧠 Escribiendo guion',
  images: '🎨 Generando imágenes', tts: '🗣️ Locución', align: '🔤 Alineación Whisper',
  render: '🎞️ Renderizando', subtitles: '💥 Subtítulos Hormozi', publishing: '📺 Publicando',
  done: '✅ Listo', failed: '❌ Error', cancelled: '🚫 Cancelado' };

function showProgress(jobId, projectId) {
  $('#overlay-root').innerHTML = `<div class="overlay"><div class="box card">
    <div class="robot">🤖</div>
    <h3 style="margin-top:10px">Fabricando tu video…</h3>
    <div class="progress-track"><div class="progress-fill" id="pfill"></div></div>
    <div id="pstep" style="font-weight:700">Preparando…</div>
    <div class="log-line" id="plog"></div>
    <div class="term" id="pterm" hidden></div>
    <div style="margin-top:18px;display:flex;gap:10px;justify-content:center">
      <button class="btn danger small" onclick="cancelJob('${jobId}')">✕ Cancelar</button>
      <button class="btn ghost small" onclick="hideProgress()">Ocultar</button>
    </div></div></div>`;

  if (S.es) S.es.close();
  S.es = new EventSource(`/api/jobs/${jobId}/events`);
  S.es.onmessage = ev => {
    const d = JSON.parse(ev.data);
    if (d.type === 'log') { termLine(d); return; }
    $('#pfill').style.width = (d.pct ?? 0) + '%';
    $('#pstep').textContent = STEP_LABEL[d.step] || d.step;
    $('#plog').textContent = d.message || '';
    if (d.type === 'done') {
      S.es.close(); hideProgress();
      toast('¡Video listo! 🎉', 'ok');
      refreshAll().then(() => openProject(d.project_id));
    }
    if (d.type === 'error') { S.es.close(); hideProgress(); toast('Error: ' + d.message, 'err'); refreshAll(); }
    if (d.type === 'cancelled') { S.es.close(); hideProgress(); toast('Cancelado'); refreshAll(); }
  };
  S.es.onerror = () => {};
}

function hideProgress() { $('#overlay-root').innerHTML = ''; if (S.es) { S.es.close(); S.es = null; } }

function termLine(d) {
  const t = $('#pterm');
  if (!t) return;
  t.hidden = false;
  const lvl = d.level === 'error' ? 'err' : d.level === 'warning' ? 'warn' : '';
  const line = document.createElement('div');
  line.className = 'term-line ' + lvl;
  line.textContent = `[${d.ts || ''}] ${d.logger || ''}: ${d.message || ''}`;
  t.appendChild(line);
  while (t.children.length > 120) t.removeChild(t.firstChild);
  t.scrollTop = t.scrollHeight;
}

async function cancelJob(jobId) {
  try { await api(`/jobs/${jobId}/cancel`, { method: 'POST' }); } catch {}
  hideProgress(); toast('Trabajo cancelado');
}

async function startJob(pid) {
  if (guardDemo()) return;
  try {
    const r = await api(`/projects/${pid}/generate`, { method: 'POST', body: {} });
    W.step = 1; showProgress(r.job_id, pid);
  } catch (e) { toast(e.message, 'err'); }
}

/* ── Flow: importar assets reales y renderizar ─────── */
function importFlow(pid) {
  const inp = document.createElement('input');
  inp.type = 'file'; inp.accept = '.zip';
  inp.onchange = async () => {
    if (!inp.files[0]) return;
    toast('Importando Escena_XX de Flow… 📦');
    const fd = new FormData(); fd.append('file', inp.files[0]);
    try {
      const res = await fetch(`/api/projects/${pid}/import-flow`, { method: 'POST', body: fd });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || 'Error al importar');
      toast(`Importadas ${d.applied}/${d.scenes_in_project} escenas ✅`, 'ok');
      openProject(pid);
    } catch (e) { toast(e.message, 'err'); }
  };
  inp.click();
}

async function renderFlow(pid) {
  try {
    const r = await api(`/projects/${pid}/render-flow`, { method: 'POST' });
    showProgress(r.job_id, pid);
  } catch (e) { toast(e.message, 'err'); }
}

async function copyFlowJson(pid) {
  try {
    const r = await fetch(`/api/projects/${pid}/export/flow.json`);
    const text = await r.text();
    await navigator.clipboard.writeText(text);
    toast('JSON copiado — pégalo en la extensión 📋', 'ok');
  } catch (e) { toast('No se pudo copiar: ' + e.message, 'err'); }
}

/* ── Guardar Guión en .txt con elección de carpeta local (Inyección 3) ── */
function _slugifyTxt(s) {
  return String(s || 'proyecto').toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 60) || 'proyecto';
}

async function downloadProjectScriptTxt(pid) {
  const p = (S.project && S.project.id === pid) ? S.project : S.projects.find(x => x.id === pid);
  if (!p) return toast('Proyecto no encontrado', 'err');
  let scenes = p.scenes || [];
  if (!scenes.length) {
    try { const d = await api(`/projects/${pid}`); scenes = d.scenes || []; } catch (_) {}
  }
  if (!scenes.length) return toast('Este proyecto aún no tiene guion — genera el video primero', 'err');

  const line = '='.repeat(70);
  const thin = '-'.repeat(70);
  let txt = `${line}\nPROYECTO: ${p.title || 'Sin Título'}\n`;
  txt += `FORMATO:  ${p.format === 'short' ? 'Short 9:16' : 'Largo 16:9'} | ESTILO: ${p.style || 'auto'} | MODO: ${p.mode || '-'}\n`;
  if (p.hook) txt += `HOOK:     ${p.hook}\n`;
  if (p.cta)  txt += `CTA:      ${p.cta}\n`;
  txt += `${line}\n\n`;

  scenes.forEach((sc, i) => {
    txt += `${thin}\nESCENA ${i + 1}: ${sc.title || ''}\n`;
    txt += `NARRACIÓN (Voz): ${sc.narration || ''}\n`;
    txt += `PROMPT IMAGEN:   ${sc.image_prompt || ''}\n\n`;
  });

  const fileName = `${_slugifyTxt(p.title)}_guion.txt`;

  // File System Access API: el usuario elige la carpeta exacta de su disco
  if (window.showSaveFilePicker) {
    try {
      const handle = await window.showSaveFilePicker({
        suggestedName: fileName,
        types: [{ description: 'Archivo de texto (Bloc de Notas)', accept: { 'text/plain': ['.txt'] } }]
      });
      const writable = await handle.createWritable();
      await writable.write(txt);
      await writable.close();
      toast('¡Guión guardado en tu carpeta! 📁', 'ok');
      return;
    } catch (err) {
      if (err && err.name === 'AbortError') return; // canceló la ventana
      console.error(err);
    }
  }

  // Fallback universal: descarga clásica a la carpeta de Descargas
  const blob = new Blob([txt], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = fileName;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
  toast('¡Guión descargado! 📄', 'ok');
}

/* ── vista: PROYECTOS ────────────────────────────────────── */
function renderProjects() {
  $('#view').innerHTML = `<h2 class="sec">🗂️ Todos los proyectos (${S.projects.length})</h2>
    <div class="proj-grid">${renderProjectCards(S.projects)}</div>`;
}

/* ── vista: DETALLE / EDITOR ─────────────────────────────── */
async function openProject(pid) {
  if (S.demo) { toast('Vista completa solo con backend — esto es la demo con datos de muestra'); return; }
  try {
    S.project = await api(`/projects/${pid}`);
    nav('project');
  } catch (e) { toast(e.message, 'err'); }
}

function renderProject() {
  const p = S.project;
  if (!p) return nav('projects');
  const scenes = p.scenes || [];
  const canPublish = p.status === 'ready';
  const av = S.avatars.find(a => a.id === p.avatar_id);
  const plats = (p.platforms && p.platforms.length ? p.platforms : ['youtube']);
  const social = plats.filter(x => x !== 'youtube');
  $('#view').innerHTML = `
    <button class="btn ghost small" onclick="nav('projects')">← Volver</button>
    <div class="editor-head" style="margin-top:16px">
      ${p.status === 'ready' ? `<video controls src="/api/projects/${p.id}/video"></video>` : ''}
      <div style="flex:1;min-width:240px">
        <h2 style="margin-bottom:6px">${esc(p.title)} ${p.status === 'published' ? '<span class="badge published">PUBLICADO</span>' : p.status === 'ready' ? '<span class="badge ready">LISTO</span>' : ''}</h2>
        <p style="color:var(--muted);font-size:13px;margin-bottom:8px">
          ${esc(p.format === 'short' ? '9:16 Short' : '16:9')} · ${esc(getStyleName(p.style))} · modo ${esc(p.mode)} · ${scenes.length} escenas
          ${av ? ` · 🎭 ${esc(av.name)}` : ''} · ${platformIcons(plats)}
          ${p.meta && p.meta.originality ? `<span class="badge ready" title="Solape de 5-gramas del guion contra la transcripción viral — bajo = original">🛡️ ${100 - Math.round((p.meta.originality.overlap || 0) * 100)}% original${p.meta.originality.retried ? ' · reescrito' : ''}</span>` : ''}
          ${p.youtube_id ? ` · <a href="https://youtube.com/watch?v=${p.youtube_id}" target="_blank">ver en YouTube ↗</a>` : ''}</p>
        <div style="display:flex;gap:9px;flex-wrap:wrap">
          ${['draft','failed'].includes(p.status) ? `<button class="btn primary" onclick="startJob('${p.id}')">▶️ Generar video</button>` : ''}
          ${p.status === 'ready' ? `<button class="btn primary" onclick="goPublish('${p.id}')">📺 Publicar en YouTube</button>` : ''}
          ${p.status === 'ready' ? `<a class="btn" href="/api/projects/${p.id}/video" download>⬇️ Descargar MP4</a>` : ''}
          <a class="btn" href="/api/projects/${p.id}/export/flow.zip" download title="ZIP método completo: PROMPT MÁSTER (imágenes base + videos en cadena), script.json de tu extensión, método ChatGPT y guion">🌊 Flow (Método Completo)</a>
          <a class="btn" href="/api/projects/${p.id}/export/flow.zip?ai=1" download title="Igual que el anterior, pero Gemini (free tier) escribe los prompts en inglés con calidad editorial — tarda ~1 min">✨ Flow +IA</a>
          <a class="btn" href="/api/projects/${p.id}/export/flow.zip?format=artesano&ai=1" download title="Modo FABRICACIÓN DE PERSONAJE (tu método palma+pino): imagen ancla + secuencia iterativa para Flow + maestro de fabricación (REGLA ABSOLUTA + PASOS) + meta-prompt para re-editar el TXT en ChatGPT. Gemini extrae héroe/materiales/emblema — tarda ~1 min">🎭 Flow Artesano</a>
          <button class="btn ghost" onclick="copyFlowJson('${p.id}')" title="Copia el JSON para pegarlo en la extensión (plan B sin autodetección)">📋 Copiar JSON</button>
          <button class="btn" onclick="importFlow('${p.id}')" title="Importa el ZIP de carpetas Escena_XX que deja tu extensión en el disco">📥 Importar Escena_XX</button>
          ${scenes.length && scenes.every(sc => sc.image_path) ? `<button class="btn primary" onclick="renderFlow('${p.id}')" title="Ensambla el MP4 final con las imágenes reales de Flow (voz + subtítulos incluidos)">🎞️ Renderizar con Flow</button>` : ''}
          <a class="btn ghost" href="/api/projects/${p.id}/subtitles.srt" download>💬 Subtítulos SRT</a>
          <button class="btn ghost" onclick="downloadProjectScriptTxt('${p.id}')" title="Guarda el guion completo (narración + prompts de imagen) en un .txt en la carpeta que elijas de tu PC">💾 Guardar Guión (.txt)</button>
          <button class="btn danger" onclick="delProject('${p.id}')">🗑️</button>
        </div>
        ${p.error ? `<p style="color:var(--err);font-size:12.5px;margin-top:10px">⚠️ ${esc(p.error)}</p>` : ''}
      </div>
    </div>
    ${p.status === 'ready' && social.length ? `
    <div class="card" style="margin-top:16px">
      <b>📡 Kit multi-plataforma</b>
      <p style="color:var(--muted);font-size:13px;margin:6px 0">Tu video es MP4 9:16 listo para subir manualmente. Descárgalo y publícalo en:</p>
      <div class="plats">${social.map(id => {
        const pl = PLATFORMS.find(x => x.id === id);
        return pl ? `<span class="plat-check on">${pl.emoji} ${pl.name}</span>` : '';
      }).join('')}</div>
    </div>` : ''}
    <h2 class="sec">🎬 Escenas <span class="hint">arrastra ⟺ para reordenar · clic en la imagen para regenerar</span></h2>
    <div class="scene-list" id="scene-list">${scenes.map(sc => sceneCard(sc)).join('') || '<div class="empty">Sin escenas todavía — genera el video primero</div>'}</div>`;

  initDrag();
}

function getStyleName(id) { return S.styles.find(s => s.id === id)?.name || id; }

function sceneCard(sc) {
  const img = sc.image_path ? `/api/scenes/${sc.id}/image?v=${sc.idx}` : '';
  return `<div class="card scene-card" draggable="true" data-id="${sc.id}">
    <span class="drag">⠿</span>
    ${img ? `<img class="img" src="${img}" onclick="regenImage('${sc.id}')" title="Clic para regenerar imagen">`
          : `<div class="img" style="display:grid;place-items:center;cursor:pointer" onclick="regenImage('${sc.id}')">🎨</div>`}
    <div class="fields">
      <span class="idx">ESCENA ${sc.idx + 1} · ${sc.duration ? sc.duration.toFixed(1) + 's' : '—'}</span>
      <input type="text" value="${esc(sc.title)}" onchange="saveScene('${sc.id}','title',this.value)">
      <textarea rows="2" onchange="saveScene('${sc.id}','narration',this.value)">${esc(sc.narration)}</textarea>
      <textarea rows="2" style="color:var(--muted)" placeholder="prompt de imagen (inglés)" onchange="saveScene('${sc.id}','image_prompt',this.value)">${esc(sc.image_prompt)}</textarea>
      <div class="tools">
        <button class="btn small ghost" onclick="regenImage('${sc.id}')">🎨 Imagen</button>
        ${sc.audio_path ? `<button class="btn small ghost" onclick="playAudio('${sc.id}',this)">🔊 Escuchar</button>` : ''}
      </div>
    </div></div>`;
}

async function saveScene(sid, field, value) {
  try { await api(`/scenes/${sid}`, { method: 'PATCH', body: { [field]: value, project_id: S.project.id } });
        toast('Escena guardada', 'ok'); } catch (e) { toast(e.message, 'err'); }
}

async function regenImage(sid) {
  toast('Regenerando imagen…');
  try { await api(`/scenes/${sid}/regenerate-image`, { method: 'POST', body: { project_id: S.project.id } });
        await openProject(S.project.id); toast('Imagen nueva lista 🎨', 'ok'); }
  catch (e) { toast(e.message, 'err'); }
}

function playAudio(sid, btn) {
  if (btn._a) { btn._a.pause(); btn._a = null; btn.textContent = '🔊 Escuchar'; return; }
  const a = new Audio(`/api/scenes/${sid}/audio`);
  a.onended = () => { btn.textContent = '🔊 Escuchar'; btn._a = null; };
  a.play(); btn._a = a; btn.textContent = '⏸ Parar';
}

function initDrag() {
  const list = $('#scene-list'); if (!list) return;
  let dragged = null;
  $$('.scene-card', list).forEach(card => {
    card.ondragstart = () => { dragged = card; card.classList.add('dragging'); };
    card.ondragend = async () => {
      card.classList.remove('dragging');
      const ids = $$('.scene-card', list).map(c => c.dataset.id);
      await api(`/projects/${S.project.id}/reorder`, { method: 'POST', body: { scene_ids: ids } });
      await openProject(S.project.id);
    };
    card.ondragover = e => {
      e.preventDefault();
      const rect = card.getBoundingClientRect();
      const after = (e.clientY - rect.top) > rect.height / 2;
      if (dragged && dragged !== card) list.insertBefore(dragged, after ? card.nextSibling : card);
    };
  });
}

async function delProject(pid) {
  if (guardDemo()) return;
  if (!confirm('¿Eliminar proyecto y sus archivos?')) return;
  try { await api(`/projects/${pid}`, { method: 'DELETE' }); await refreshAll(); nav('projects'); toast('Eliminado'); }
  catch (e) { toast(e.message, 'err'); }
}

/* ── vista: FÁBRICA ──────────────────────────────────────── */
function renderFactory() {
  const f = S.factory || {};
  const times = (f.times || []).join(', ');
  $('#view').innerHTML = `
    <h2 class="sec">🏭 Modo Fábrica <span class="hint">la ventaja que Labsia NO tiene</span></h2>
    <div class="factory-grid">
      <div class="card">
        <div class="toggle ${f.enabled ? 'on' : ''}" onclick="toggleFactory()">
          <div class="switch"></div><div><b>Producción automática</b>
          <div style="color:var(--muted);font-size:12.5px">${f.enabled ? `ACTIVO · próximas: ${(f.next_runs || []).slice(0, 2).map(r => new Date(r).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })).join(', ') || 'programando…'}` : 'Apagado — actívalo para producir solo'}</div></div>
        </div>
        <div style="height:14px"></div>
        <div class="row">
          <div class="field"><label>⏰ Horarios (separados por coma)</label>
            <input type="text" id="f-times" value="${esc(times)}" placeholder="07:00,12:30,19:00"></div>
          <div class="field"><label>🎯 Nicho / temática</label>
            <input type="text" id="f-niche" value="${esc(f.niche || '')}" placeholder="historias reales impactantes"></div>
        </div>
        <div class="row">
          <div class="field"><label>🎨 Estilo por defecto</label>
            <select id="f-style">${S.styles.map(s => `<option value="${s.id}" ${f.style === s.id ? 'selected' : ''}>${s.emoji} ${esc(s.name)}</option>`).join('')}</select></div>
          <div class="field"><label>📐 Formato</label>
            <select id="f-format"><option value="short" ${f.format === 'short' ? 'selected' : ''}>Short 9:16</option><option value="long" ${f.format === 'long' ? 'selected' : ''}>Largo 16:9</option></select></div>
        </div>
        <div class="toggle ${f.autopublish ? 'on' : ''}" onclick="this.classList.toggle('on')" id="f-ap-toggle" style="margin-bottom:14px">
          <div class="switch"></div><div><b>Autopublicar en YouTube</b><div style="color:var(--muted);font-size:12.5px">sube cada video automáticamente (privado)</div></div>
        </div>
        <div style="display:flex;gap:10px">
          <button class="btn primary" onclick="saveFactory()">💾 Guardar config</button>
          <button class="btn" onclick="runNow()">⚡ Producir uno ahora</button>
        </div>
      </div>
      <div class="card">
        <b>💡 Cola de ideas (${(f.pending_ideas || 0)})</b>
        <p style="color:var(--muted);font-size:12.5px;margin:8px 0 12px">La fábrica toma la primera idea disponible; si no hay, inventa una según el nicho.</p>
        <div style="display:flex;gap:8px;margin-bottom:14px">
          <input type="text" id="f-idea" placeholder="Nueva idea…">
          <button class="btn small" onclick="addIdea()">+</button>
        </div>
        <div id="ideas-list">${S.ideas.map((i, ix) => `<div class="idea-item"><span>${esc(i)}</span><button class="btn small danger" onclick="delIdea(${ix})">✕</button></div>`).join('') || '<p style="color:var(--muted);font-size:13px">Vacía — la IA inventará ideas del nicho.</p>'}</div>
      </div>
    </div>`;
}

async function toggleFactory() {
  if (guardDemo()) return;
  const next = !S.factory.enabled;
  try { S.factory = await api('/factory/config', { method: 'POST', body: { enabled: next } });
        toast(next ? '🏭 Fábrica ACTIVADA' : 'Fábrica apagada', 'ok'); renderFactory(); }
  catch (e) { toast(e.message, 'err'); }
}

async function saveFactory() {
  if (guardDemo()) return;
  const times = $('#f-times').value.split(',').map(s => s.trim()).filter(Boolean);
  try {
    S.factory = await api('/factory/config', { method: 'POST', body: {
      times, niche: $('#f-niche').value, style: $('#f-style').value,
      format: $('#f-format').value, autopublish: $('#f-ap-toggle').classList.contains('on') } });
    toast('Configuración guardada ✅', 'ok'); renderFactory();
  } catch (e) { toast(e.message, 'err'); }
}

async function runNow() {
  if (guardDemo()) return;
  toast('Produciendo video… 🏭');
  try { const r = await api('/factory/run-now', { method: 'POST' });
        showProgress(r.job_id, r.project_id); }
  catch (e) { toast(e.message, 'err'); }
}

async function addIdea() {
  if (guardDemo()) return;
  const v = $('#f-idea').value.trim(); if (!v) return;
  await api('/factory/ideas', { method: 'POST', body: { idea: v } });
  S.ideas = await api('/factory/ideas'); S.factory = await api('/factory'); renderFactory();
}

async function delIdea(ix) {
  const ideas = S.ideas.filter((_, i) => i !== ix);
  await fetch('/api/factory/ideas', { method: 'DELETE' });
  for (const i of ideas) await api('/factory/ideas', { method: 'POST', body: { idea: i } });
  S.ideas = await api('/factory/ideas'); S.factory = await api('/factory'); renderFactory();
}

/* ── vista: PUBLICAR ─────────────────────────────────────── */
let PUB_PID = null;
function renderPublish() {
  const ready = S.projects.filter(p => p.status === 'ready' || p.status === 'published');
  const p = PUB_PID ? ready.find(x => x.id === PUB_PID) : ready[0];
  $('#view').innerHTML = `
    <h2 class="sec">📺 Publicar en YouTube <span class="hint">OAuth de escritorio — 100% tu canal</span></h2>
    ${S.health.youtube ? '' : `<div class="demo-banner">🔑 Falta configurar YouTube: coloca <b>client_secret.json</b> en <code>backend/data/</code> y conecta tu cuenta abajo (README §Publicar).</div>`}
    <div class="factory-grid">
      <div class="card">
        <div class="field"><label>Video listo</label>
          <select id="pub-proj">${ready.map(x => `<option value="${x.id}" ${p && p.id === x.id ? 'selected' : ''}>${esc(x.title)}</option>`).join('') || '<option disabled>Sin videos listos</option>'}</select></div>
        <div class="field"><label>Título</label><input type="text" id="pub-title" value="${esc(p?.title || '')}" maxlength="100"></div>
        <div class="field"><label>Descripción</label><textarea id="pub-desc" rows="4"></textarea></div>
        <div class="field"><label>Tags (coma)</label><input type="text" id="pub-tags" placeholder="shorts, viral, historia"></div>
        <div class="row">
          <div class="field"><label>Programar (opcional, hora local)</label><input type="datetime-local" id="pub-at"></div>
          <div class="field"><label>Visibilidad</label><select id="pub-vis"><option value="1">Privado</option><option value="0">Público</option></select></div>
        </div>
        <button class="btn primary" onclick="doPublish()">🚀 Subir a YouTube</button>
      </div>
      <div class="card">
        <b>🔑 Conexión de canal</b>
        <p style="color:var(--muted);font-size:12.5px;margin:10px 0">Estado: ${S.health.youtube ? '✅ conectado con token' : '❌ sin token'}</p>
        ${S.health.youtube ? '' : `<button class="btn" onclick="ytAuth()">1. Conectar mi canal</button>`}
        <div style="height:12px"></div>
        <div class="field"><label>2. Si Google te dio un código, pégalo aquí</label>
          <input type="text" id="yt-code" placeholder="4/0AxxS..."></div>
        <button class="btn" onclick="ytExchange()">Guardar token</button>
      </div>
    </div>`;
  const sel = $('#pub-proj');
  if (sel) sel.onchange = () => { PUB_PID = sel.value; renderPublish(); };
}

async function ytAuth() {
  if (guardDemo()) return;
  try { const r = await api('/publish/auth-url');
        window.open(r.url, '_blank'); toast('Abre el enlace y pega el código aquí', 'ok'); }
  catch (e) { toast(e.message, 'err'); }
}
async function ytExchange() {
  if (guardDemo()) return;
  try { await api('/publish/exchange', { method: 'POST', body: { code: $('#yt-code').value } });
        toast('¡Canal conectado! ✅', 'ok'); await refreshAll(); renderPublish(); }
  catch (e) { toast(e.message, 'err'); }
}
async function doPublish() {
  if (guardDemo()) return;
  const pid = $('#pub-proj').value;
  const at = $('#pub-at').value;
  try {
    const r = await api(`/publish/${pid}`, { method: 'POST', body: {
      title: $('#pub-title').value, description: $('#pub-desc').value,
      tags: $('#pub-tags').value.split(',').map(t => t.trim()).filter(Boolean),
      private: $('#pub-vis').value === '1',
      publish_at: at ? new Date(at).toISOString() : null } });
    toast('¡Publicado! youtube.com/watch?v=' + r.youtube_id, 'ok');
    await refreshAll(); renderPublish();
  } catch (e) { toast(e.message, 'err'); }
}
function goPublish(pid) { PUB_PID = pid; nav('publish'); }

/* ── vista: AJUSTES (configuración de APIs desde el dashboard) ── */
function updatePills() {
  const pills = [['pill-gemini', S.health.gemini], ['pill-whisper', S.health.whisper], ['pill-yt', S.health.youtube]];
  pills.forEach(([id, on]) => { const el = $('#' + id); if (el) $('.dot', el).classList.toggle('on', !!on); });
}

async function refreshCfgStatus() {
  try {
    S.health = await api('/health');
    S.settings = await api('/settings');
    updatePills();
  } catch {}
}

async function saveCfg(patch, okMsg) {
  if (guardDemo()) return;
  try {
    const r = await api('/config', { method: 'POST', body: patch });
    toast('✅ ' + (okMsg || r.message), 'ok');
    await refreshCfgStatus();
    renderSettings();
  } catch (e) { toast('❌ ' + e.message, 'err'); }
}

async function testGemini(btn) {
  if (guardDemo()) return;
  btn.disabled = true; btn.textContent = '⏳ Probando…';
  try {
    const r = await api('/config/test-gemini', { method: 'POST', body: {} });
    if (r.ok) toast('✅ Gemini responde: ' + r.reply, 'ok');
    else toast('❌ ' + r.error, 'err');
  } catch (e) { toast('❌ ' + e.message, 'err'); }
  btn.disabled = false; btn.textContent = '🔌 Probar clave';
}

async function uploadSecret(input) {
  const f = input.files && input.files[0];
  if (!f) return;
  if (guardDemo()) return;
  const fd = new FormData(); fd.append('file', f);
  try {
    const res = await fetch('/api/config/client-secret', { method: 'POST', body: fd });
    const r = await res.json();
    if (!res.ok) throw new Error(r.detail || 'Error al subir');
    toast('✅ client_secret.json guardado — YouTube listo para conectar', 'ok');
    await refreshCfgStatus(); renderSettings();
  } catch (e) { toast('❌ ' + e.message, 'err'); }
  input.value = '';
}

function toggleKeyEye() {
  const inp = $('#cfg-key'); if (!inp) return;
  inp.type = inp.type === 'password' ? 'text' : 'password';
}

async function renderSettings() {
  $('#view').innerHTML = `<h2 class="sec">⚙️ Ajustes</h2><div class="cfg-grid"><div class="card empty" style="grid-column:1/-1">Cargando configuración…</div></div>`;
  let c = {};
  if (!S.demo) { try { c = await api('/config'); } catch {} }
  const ev = S.settings.edge_voices || [];
  const gv = S.settings.gemini_voices || [];
  const keyChip = c.gemini_key_set
    ? `<span class="cfg-status ok">✅ Configurada · ${esc(c.gemini_key_masked || '•••')}</span>`
    : `<span class="cfg-status err">❌ Sin clave — modo demo (placeholders + edge-tts)</span>`;
  const ytChip = c.youtube_token
    ? `<span class="cfg-status ok">✅ Canal conectado</span>`
    : c.youtube_configured
    ? `<span class="cfg-status ok">✅ client_secret cargado</span>`
    : `<span class="cfg-status err">❌ Sin client_secret.json</span>`;
  const whChip = c.whisper_available
    ? `<span class="cfg-status ok">✅ Instalado</span>`
    : `<span class="cfg-status err">⚠️ No instalado (tiempos estimados)</span>`;

  $('#view').innerHTML = `
    <h2 class="sec">⚙️ Ajustes</h2>
    <div class="cfg-grid">

      <div class="card">
        <b>🔑 Gemini API</b> <span style="float:right">${keyChip}</span>
        <div class="keyrow" style="margin-top:14px">
          <input type="password" id="cfg-key" autocomplete="off" spellcheck="false"
                 placeholder="${c.gemini_key_set ? 'Escribe una clave nueva para reemplazar ' + esc(c.gemini_key_masked || '') : 'Pega aquí tu clave · AIzaSy…'}">
          <button class="eye" onclick="toggleKeyEye()" title="Mostrar/ocultar">👁️</button>
        </div>
        <div class="cfg-actions">
          <button class="btn primary small" onclick="saveCfg({GEMINI_API_KEY: document.getElementById('cfg-key').value}, 'Clave guardada y activada — sin reiniciar')">💾 Guardar clave</button>
          <button class="btn small" onclick="testGemini(this)">🔌 Probar clave</button>
          ${c.gemini_key_set ? `<button class="btn danger small" onclick="if(confirm('¿Quitar la clave guardada? El sistema vuelve a modo demo.'))saveCfg({GEMINI_API_KEY: ''}, 'Clave eliminada — modo demo')">Quitar</button>` : ''}
        </div>
        <div class="hintline">Clave <b>gratis y al instante</b> en <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">aistudio.google.com/apikey</a> → «Create API key» → copia (AIzaSy…).<br>
        Activa: guiones IA, imágenes reales (Gemini 2.5 Flash Image) y voz premium. Se guarda en <code class="mini">${esc(c.env_path || 'backend/.env')}</code> y <b>aplica sin reiniciar</b>.</div>
      </div>

      <div class="card">
        <b>🗣️ Locución (TTS)</b>
        <div class="field" style="margin-top:14px"><label>Proveedor principal</label>
          <select id="cfg-tts">
            <option value="edge" ${c.tts_provider === 'edge' ? 'selected' : ''}>edge-tts · gratis e ilimitado (recomendado)</option>
            <option value="gemini" ${c.tts_provider === 'gemini' ? 'selected' : ''}>Gemini TTS · voz premium (requiere clave)</option>
          </select></div>
        <div class="field"><label>Voz edge-tts</label>
          <select id="cfg-edge-voice">${ev.map(v => `<option value="${v.id}" ${c.edge_tts_voice === v.id ? 'selected' : ''}>${esc(v.name)}</option>`).join('')}</select></div>
        <div class="field"><label>Voz Gemini</label>
          <select id="cfg-gemini-voice">${gv.map(v => `<option value="${v.id}" ${c.gemini_tts_voice === v.id ? 'selected' : ''}>${esc(v.name)}</option>`).join('')}</select></div>
        <div class="field"><label>Velocidad (ej. +8% o -10%)</label>
          <input type="text" id="cfg-rate" value="${esc(c.tts_rate || '+8%')}"></div>
        <div class="cfg-actions"><button class="btn primary small"
          onclick="saveCfg({TTS_PROVIDER: document.getElementById('cfg-tts').value, EDGE_TTS_VOICE: document.getElementById('cfg-edge-voice').value, GEMINI_TTS_VOICE: document.getElementById('cfg-gemini-voice').value, TTS_RATE: document.getElementById('cfg-rate').value}, 'Voz guardada')">💾 Guardar voz</button></div>
        <div class="hintline">Si un proveedor falla, el sistema cae automáticamente al otro. Nunca se bloquea el render.</div>
      </div>

      <div class="card">
        <b>📺 YouTube (autopublicar)</b> <span style="float:right">${ytChip}</span>
        <div class="field" style="margin-top:14px"><label>1. Sube tu client_secret.json (OAuth · Aplicación de escritorio)</label>
          <input type="file" id="cfg-secret" accept=".json" onchange="uploadSecret(this)"></div>
        <div class="cfg-actions"><button class="btn small" onclick="nav('publish')">Conectar mi canal →</button></div>
        <div class="hintline">Descárgalo de <a href="https://console.cloud.google.com" target="_blank" rel="noopener">console.cloud.google.com</a> → crea proyecto → habilita <b>YouTube Data API v3</b> → Credenciales → OAuth 2.0 → Aplicación de escritorio. Sin verificación de Google, los videos suben como <b>privados</b> (perfecto para revisar antes).</div>
      </div>

      <div class="card">
        <b>🎬 Render y subtítulos</b> <span style="float:right">${whChip}</span>
        <div class="field" style="margin-top:14px"><label>Modelo Whisper (precisión de subtítulos)</label>
          <select id="cfg-whisper" ${c.whisper_available ? '' : 'disabled'}>
            ${['tiny','base','small','medium'].map(m => `<option value="${m}" ${(c.whisper_model || 'small') === m ? 'selected' : ''}>${m} ${m === 'small' ? '· recomendado' : m === 'medium' ? '· máxima precisión' : '· más rápido'}</option>`).join('')}
          </select></div>
        <div class="field"><label>FPS del render</label>
          <input type="number" id="cfg-fps" value="${c.fps ?? 30}" min="12" max="60"></div>
        <div class="cfg-actions"><button class="btn primary small" ${c.whisper_available ? '' : 'disabled'}
          onclick="saveCfg({WHISPER_MODEL: document.getElementById('cfg-whisper').value, FPS: document.getElementById('cfg-fps').value}, 'Render guardado')">💾 Guardar render</button></div>
        <div class="hintline">${c.whisper_available ? 'Whisper activo: subtítulos con tiempos exactos por palabra.' : 'Para subtítulos exactos: <code class="mini">pip install faster-whisper</code> y reinicia. Sin él, los tiempos se estiman (funciona bien).'} FPS alto = render más lento.</div>
      </div>

      <div class="card">
        <b>🎨 Apariencia</b>
        <div class="toggle" style="margin-top:12px" onclick="setTheme(S.theme==='dark'?'light':'dark');renderSettings()">
          <div class="switch ${S.theme === 'dark' ? '' : 'on'}"></div>
          <div><b>Tema claro</b><div style="color:var(--muted);font-size:12.5px">clic para alternar</div></div>
        </div>
        <div style="height:16px"></div>
        <b>🧩 Extensión Chrome (Plan B)</b>
        <div class="idea-item" style="margin-top:10px"><span>Imágenes en cola</span><b>${c.ext_pending ?? 0}</b></div>
        <div class="cfg-actions">
          <a class="btn primary small" href="/api/extension/download" download title="Descargar extensión Chrome">⬇️ Descargar extensión (.zip)</a>
        </div>
        <p style="color:var(--muted);font-size:12.5px;margin:8px 0;line-height:1.6"><b>1.</b> Descarga y descomprime el ZIP · <b>2.</b> En Chrome entra a <code class="mini">chrome://extensions</code> → activa <b>modo desarrollador</b> → <b>Cargar descomprimida</b> → carpeta <code class="mini">extension/</code> · <b>3.</b> Genera imágenes en <a href="https://labs.google/fx" target="_blank" rel="noopener" style="color:var(--accent)">Google ImageFX</a> y pulsa ➤ Enviar. Llegarán aquí como respaldo automático cuando Gemini llegue a su cuota diaria.</p>
      </div>

      <div class="card" id="doctor-card">
        <b>🩺 Doctor del sistema</b> <span style="float:right"><button class="btn ghost small" onclick="loadDoctor()">↻ Revisar ahora</button></span>
        <div style="color:var(--muted);font-size:13px;margin-top:12px">Ejecutando 11 sondas reales (ffmpeg, disco, TTS, yt-dlp…)</div>
      </div>

    </div>`;
}

async function loadDoctor() {
  const card = document.getElementById('doctor-card');
  if (!card) return;
  try {
    const d = await api('/doctor');
    const chip = c => {
      const cls = c.ok ? 'ok' : (c.warn ? 'warn' : 'err');
      const ico = c.ok ? '✅' : (c.warn ? '⚠️' : '❌');
      return `<div class="idea-item doctor-item"><span>${ico} ${esc(c.id)}</span><b class="doc-${cls}" title="${esc(c.detail || '')}">${esc(c.detail || '').slice(0, 46)}</b></div>`;
    };
    card.innerHTML = `
      <b>🩺 Doctor del sistema</b>
      <span style="float:right;color:var(--muted);font-size:12.5px">
        ${d.summary.ok} OK · ${d.summary.warn} aviso · ${d.summary.fail} fallo</span>
      <div style="margin-top:12px">${d.checks.map(chip).join('')}</div>
      <div class="hintline">Fallo = crítico (el pipeline no puede correr). Aviso = degradación graceful $0. Cada check ejecuta un comando real ahora mismo.</div>`;
  } catch (e) {
    card.innerHTML = `<b>🩺 Doctor del sistema</b><p style="color:var(--err);margin-top:10px">❌ ${esc(e.message)}</p>`;
  }
}

/* ── vista: TENDENCIAS (research $0 pre-guion) ───────────── */
async function renderTrends() {
  $('#view').innerHTML = `
    <h2 class="sec">🔥 Tendencias <span class="hint">research real de YouTube sin API key (yt-dlp) — antes de escribir el guion</span></h2>
    <div class="card">
      <div class="keyrow">
        <input type="text" id="trend-q" placeholder="Nicho o tema: p. ej. historia del imperio romano, IA herramientas, misterios del océano…"
               onkeydown="if(event.key==='Enter')doTrends()">
        <button class="btn primary" onclick="doTrends()">🔍 Investigar</button>
      </div>
      <small style="color:var(--muted);display:block;margin-top:8px">Analiza los videos más vistos del tema: duración dulce, títulos que enganchan, keywords reales e ideas listas para producir. Si YouTube bloquea la IP, usa el selector de cookies del wizard (modo URL) o investiga desde tu IP residencial.</small>
    </div>
    <div id="trends-out" style="margin-top:16px"><div class="card empty">Pulsa Investigar para ver qué está funcionando AHORA en tu nicho</div></div>`;
}

async function doTrends() {
  const q = ($('#trend-q')?.value || '').trim();
  if (!q) return toast('Escribe un tema para investigar', 'err');
  const out = $('#trends-out');
  out.innerHTML = '<div class="card empty">🔎 Analizando el nicho con yt-dlp (tarda 10-60s)…</div>';
  try {
    const d = await api('/trends/research', { method: 'POST', body: { query: q, max_videos: 8 } });
    const r = d.research || {};
    const ins = r.insights || {};
    const fmt = n => n >= 1000 ? (n / 1000).toFixed(1).replace('.0', '') + 'K' : String(n ?? 0);
    const ideas = (d.ideas || []);
    out.innerHTML = `
      <div class="grid-kpis">
        <div class="card kpi"><div class="num">${r.count || 0}</div><div class="lbl">Videos analizados</div></div>
        <div class="card kpi"><div class="num">${fmt(ins.avg_views)}</div><div class="lbl">Vistas promedio</div></div>
        <div class="card kpi"><div class="num">${ins.median_duration_s ? Math.round(ins.median_duration_s) + 's' : '—'}</div><div class="lbl">Duración dulce (mediana)</div></div>
        <div class="card kpi"><div class="num">${(ins.keywords || []).length}</div><div class="lbl">Keywords reales</div></div>
      </div>
      <div class="card" style="margin-top:14px"><b>🏷️ Keywords del nicho</b>
        <div class="plats" style="margin-top:8px">${(ins.keywords || []).slice(0, 10).map(k => `<span class="plat-check on">${esc(k)}</span>`).join('') || '<span style="color:var(--muted)">—</span>'}</div>
        <b style="display:block;margin-top:12px">🪝 Hooks de los títulos ganadores</b>
        <div style="margin-top:6px">${(ins.hook_patterns || []).slice(0, 4).map(t => `<div class="idea-item"><span>${esc(t)}</span></div>`).join('')}</div>
      </div>
      <div class="card" style="margin-top:14px"><b>💡 Ideas listas para producir</b>
        <small style="color:var(--muted);display:block;margin:4px 0 8px">Clic en una idea para crear el video con ella</small>
        ${ideas.map(i => {
          const js = JSON.stringify(i.title || '').replace(/"/g, '&quot;');
          return `<div class="idea-item" style="cursor:pointer" onclick="W.mode='idea';W.idea=${js};nav('create')">
            <span><b>${esc(i.title || '')}</b><br><span style="color:var(--muted);font-size:12px">${esc(i.angle || '')} — ${esc(i.why || '')}</span></span>
            <b style="color:var(--accent)">→ crear</b></div>`;
        }).join('')}
      </div>`;
  } catch (e) {
    out.innerHTML = `<div class="card empty" style="color:var(--err)">❌ ${esc(e.message)}</div>`;
  }
}

/* ── vista: AGENTE (chat v2.1) ───────────────────────────── */
function renderAgent() {
  $('#greet').innerHTML = `Agente VÓRTICE 🤖<small id="greet-sub">Habla y el motor produce — sin tocar un solo botón</small>`;
  const msgs = S.chat.map((m, i) => {
    if (m.role === 'user')
      return `<div class="chat-msg user"><div class="bubble">${mmd(m.text)}</div><div class="who">Tú</div></div>`;
    let extra = '';
    if (m.project) extra += `<div class="chat-proj" onclick="openProject('${m.project.id}')">🎬 ${esc(m.project.title)} <small>ver proyecto →</small></div>`;
    if (m.projects && m.projects.length)
      extra = m.projects.map(p =>
        `<div class="chat-proj" onclick="openProject('${p.id}')">${p.status === 'ready' ? '✅' : p.status === 'failed' ? '❌' : '🎞️'} ${esc(p.title)} <small>${esc(p.status)}</small></div>`).join('');
    return `<div class="chat-msg bot"><div class="bubble">${mmd(m.text)}${extra}</div><div class="who">VÓRTICE${m.engine === 'gemini' ? ' · Gemini' : ''}</div></div>`;
  }).join('');
  const chips = ['crea un video sobre el imperio romano',
                 'muéstrame mis proyectos',
                 S.avatars[0] ? `crea un video de mystery con ${S.avatars[0].name}` : 'crea un video de misterios del océano',
                 '¿qué puedes hacer?'];
  $('#view').innerHTML = `
    <div class="chat-wrap">
      <div class="chat-scroll" id="chat-scroll">${msgs}</div>
      <div class="chat-chips">${chips.map(c => `<button class="chip" onclick="sendChat(${JSON.stringify(c).replace(/"/g, '&quot;')})">${esc(c)}</button>`).join('')}</div>
      <div class="chat-input">
        <input type="text" id="chat-text" placeholder="Pide un video, el estado, tus proyectos…"
               onkeydown="if(event.key==='Enter')sendChat()">
        <button class="btn primary" id="chat-send" onclick="sendChat()">➤</button>
      </div>
    </div>`;
  const sc = $('#chat-scroll'); sc.scrollTop = sc.scrollHeight;
  if (!S.demo) $('#chat-text').focus();
}

function mmd(text) {
  // mini-markdown: **negrita**, saltos y listas simples → HTML seguro
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/«(.+?)»/g, '«<i>$1</i>»')
    .replace(/\n/g, '<br>');
}

async function sendChat(preset) {
  const inp = $('#chat-text');
  const text = (preset !== undefined && typeof preset === 'string' ? preset : inp?.value || '').trim();
  if (!text || S.chatBusy) return;
  if (guardDemo()) return;
  S.chat.push({ role: 'user', text });
  S.chatBusy = true;
  if (inp) inp.value = '';
  renderAgent();
  try {
    const r = await api('/chat', { method: 'POST', body: { message: text,
      history: S.chat.slice(-8).map(m => ({ role: m.role, text: m.text })) } });
    const entry = { role: 'bot', text: r.reply || 'Hecho ✅', engine: r.engine,
                    project: r.project, projects: r.projects };
    S.chat.push(entry);
    S.chatBusy = false;
    renderAgent();
    refreshAll();
    if (r.action === 'create_video' && r.project && r.job_id) {
      toast('🎬 Producción lanzada por el agente', 'ok');
      showProgress(r.job_id, r.project.id);
    }
  } catch (e) {
    S.chatBusy = false;
    S.chat.push({ role: 'bot', text: '⚠️ ' + e.message });
    renderAgent();
  }
}

/* ── vista: AVATARES (v2.1.1 PRO con menús desplegables) ── */
const AV_FORM = { editing: null, fields: {} };

/* Opciones PRO — espejo de backend/services/avatar_schema.py.
   Se refresca en vivo desde /api/avatars/schema; esto es el fallback. */
const AV_OPTS_FALLBACK = {
  genero: ['Femenino', 'Masculino', 'Andrógino'],
  edad: ['18-24', '25-34', '35-44', '45-54', '55+'],
  piel: ['Clara', 'Media', 'Morena', 'Oscura'],
  ojos_color: ['Azules', 'Verdes', 'Marrones', 'Negros', 'Grises', 'Avellana'],
  ojos_forma: ['Almendrados', 'Redondos', 'Rasgados', 'Caídos'],
  cabello_color: ['Rubio', 'Castaño', 'Negro', 'Pelirrojo', 'Gris plateado', 'Degradado', 'Azul eléctrico', 'Rosa pastel'],
  cabello_largo: ['Corto', 'Mediano', 'Largo', 'Extra largo'],
  cabello_textura: ['Liso', 'Ondulado', 'Rizado', 'Afro'],
  cuerpo: ['Delgado', 'Atlético', 'Curvilíneo', 'Voluptuoso', 'Robusto'],
  ropa: ['Casual elegante', 'Streetwear', 'Formal', 'Deportivo', 'Bohemio', 'Aventurero', 'Vintage', 'Urbano oscuro'],
  maquillaje: ['Natural', 'Glam', 'Dramático', 'Artístico', 'Ninguno'],
  arquetipo: ['🔥 Rebelde', '💋 Seductora', '✨ Carismática', '💥 Explosiva', '🌙 Misteriosa', '🧠 Calculadora', '🎪 Playful', '👑 Empoderada', '🧭 Exploradora', '🔬 Científica', '🧙 Sabio Mentor', '🦸 Heroica'],
  personalidad: ['Irreverente', 'Misteriosa', 'Carismática', 'Explosiva', 'Cálida', 'Intelectual', 'Optimista', 'Sarcástica', 'Inspiradora', 'Extrovertida'],
  acento: ['Costeño', 'Bogotano', 'Paisa', 'Mexicano', 'Argentino', 'Neutro latino', 'España', 'Otro'],
  jerga: ['Regional', 'Neutro', 'Mixto'],
};
const AV_LABELS = {
  genero: 'Género', edad: 'Edad aparente', piel: 'Tono de piel',
  ojos_color: 'Color de ojos', ojos_forma: 'Forma de ojos',
  cabello_color: 'Color de cabello', cabello_largo: 'Largo de cabello',
  cabello_textura: 'Textura de cabello', cuerpo: 'Tipo de cuerpo',
  ropa: 'Estilo de ropa', maquillaje: 'Estilo de maquillaje',
  arquetipo: 'Arquetipo', personalidad: 'Personalidad predominante',
  acento: 'Acento al hablar', jerga: 'Tipo de jerga regional',
};
const AV_FIELDS = Object.keys(AV_OPTS_FALLBACK);   // 15 desplegables
const AV_FREE = ['accesorios', 'referencia', 'extras']; // texto libre
let AV_OPTS = null; // opciones vivas del backend cuando esté disponible

async function loadAvatarSchema() {
  if (AV_OPTS) return;
  try { const s = await api('/avatars/schema'); AV_OPTS = s.options || AV_OPTS_FALLBACK; }
  catch { AV_OPTS = AV_OPTS_FALLBACK; }
}

function avSelect(field, placeholder) {
  const opts = (AV_OPTS && AV_OPTS[field]) || AV_OPTS_FALLBACK[field] || [];
  const cur = AV_FORM.fields[field] || '';
  return `<select onchange="AV_FORM.fields['${field}']=this.value${field === 'acento' ? ';suggestVoiceForAccent()' : ''}">
    <option value="">${placeholder || '— sin especificar —'}</option>
    ${opts.map(o => `<option ${cur === o ? 'selected' : ''}>${esc(o)}</option>`).join('')}
  </select>`;
}
function avFree(field, placeholder) {
  return `<input type="text" value="${esc(AV_FORM.fields[field] || '')}"
    oninput="AV_FORM.fields['${field}']=this.value" placeholder="${esc(placeholder)}">`;
}
function suggestVoiceForAccent() {
  const a = AV_FORM.fields.acento, g = AV_FORM.fields.genero || 'Femenino';
  if (!a || a === 'Otro') return;
  const map = {
    'Costeño':    { 'Femenino': 'es-CO-SalomeNeural', 'Masculino': 'es-CO-GonzaloNeural' },
    'Bogotano':   { 'Femenino': 'es-CO-SalomeNeural', 'Masculino': 'es-CO-GonzaloNeural' },
    'Paisa':      { 'Femenino': 'es-CO-SalomeNeural', 'Masculino': 'es-CO-GonzaloNeural' },
    'Mexicano':   { 'Femenino': 'es-MX-DaliaNeural', 'Masculino': 'es-MX-JorgeNeural' },
    'Argentino':  { 'Femenino': 'es-AR-ElenaNeural', 'Masculino': 'es-AR-TomasNeural' },
    'Neutro latino': { 'Femenino': 'es-US-IsabellaNeural', 'Masculino': 'es-US-AlonsoNeural' },
    'España':     { 'Femenino': 'es-ES-ElviraNeural', 'Masculino': 'es-ES-AlvaroNeural' },
  };
  const vid = (map[a] || {})[g];
  if (vid && (S.settings.edge_voices || []).some(v => v.id === vid)) {
    AV_FORM.fields.voice = vid;
    const sel = document.querySelector('#av-voice-select');
    if (sel) sel.value = vid;
    toast(`🗣️ Voz sugerida por acento ${a}: ${voiceName(vid)}`, 'ok');
  }
}

function avatarChips(a) {
  const ap = a.appearance || {};
  const chips = [];
  if (ap.arquetipo) chips.push(esc(ap.arquetipo));
  if (ap.personalidad) chips.push(esc(ap.personalidad));
  if (ap.genero || ap.edad) chips.push(esc([ap.genero, ap.edad].filter(Boolean).join(' · ')));
  if (ap.piel) chips.push('piel ' + esc(ap.piel.toLowerCase()));
  if (ap.ojos_color) chips.push('ojos ' + esc(ap.ojos_color.toLowerCase()));
  const hair = [ap.cabello_largo, ap.cabello_textura, ap.cabello_color].filter(Boolean).join(' ').toLowerCase();
  if (hair) chips.push(' cabello ' + esc(hair));
  if (ap.cuerpo) chips.push(esc(ap.cuerpo.toLowerCase()));
  if (ap.ropa) chips.push(esc(ap.ropa.toLowerCase()));
  if (ap.acento) chips.push('🎙️ ' + esc(ap.acento));
  return chips.map(c => `<span class="chip">${c.trim()}</span>`).join('');
}

async function renderAvatars() {
  await loadAvatarSchema();          // opciones vivas del backend (fallback local)
  $('#greet').innerHTML = `Avatares 🎭<small id="greet-sub">Personajes consistentes: misma cara, voz y estilo en todos tus videos</small>`;
  if (AV_FORM.editing !== null) return renderAvatarForm();
  const cards = S.avatars.map(a => {
    const img = a.image_path ? `<img src="/api/avatars/${a.id}/image?v=${a.updated_at}" loading="lazy">`
      : `<div class="av-ph">${esc((a.name || 'A').slice(0, 1).toUpperCase())}</div>`;
    return `<div class="card av-card">
      <div class="av-img">${img}</div>
      <div class="av-body">
        <b>${esc(a.name)}</b>
        <small class="av-desc">${esc(a.description || 'Sin personalidad definida')}</small>
        <div class="av-chips">${avatarChips(a) || '<small class="av-look">Sin características aún</small>'}</div>
        <div class="av-meta">
          ${a.voice ? `<span class="badge draft">🗣️ ${esc(voiceName(a.voice))}</span>` : ''}
          ${a.style ? `<span class="badge draft">${esc(getStyleName(a.style))}</span>` : ''}
        </div>
        <div class="av-actions">
          <button class="btn small ghost" onclick="editAvatar('${a.id}')">✏️ Editar</button>
          <button class="btn small ghost" onclick="genAvatarImage('${a.id}', this)">🖼️ ${a.image_path ? 'Regenerar' : 'Imagen'}</button>
          <button class="btn small ghost" onclick="showAvatarPrompt('${a.id}')">📄 Prompt</button>
          <button class="btn small danger ghost" onclick="delAvatar('${a.id}')">🗑</button>
        </div>
      </div></div>`;
  }).join('');
  $('#view').innerHTML = `
    <div class="row" style="align-items:center;margin-bottom:14px">
      <h2 class="sec" style="margin:0">🎭 Tus personajes (${S.avatars.length})</h2>
      <button class="btn primary small" style="margin-left:auto" onclick="newAvatar()">➕ Nuevo avatar</button>
    </div>
    ${S.avatars.length ? `<div class="av-grid">${cards}</div>` :
      `<div class="card empty"><div class="big">🎭</div>Crea tu primer personaje: misma apariencia, voz y estilo en todos sus videos.<br><br>
       <button class="btn primary" onclick="newAvatar()">➕ Crear avatar</button></div>`}`;
}

function voiceName(id) {
  const all = [...(S.settings.edge_voices || []), ...(S.settings.gemini_voices || [])];
  return all.find(v => v.id === id)?.name || id;
}

function blankAvatarFields() {
  const f = { name: '', description: '', voice: '', style: '' };
  AV_FIELDS.forEach(k => f[k] = '');
  AV_FREE.forEach(k => f[k] = '');
  return f;
}

function newAvatar() {
  AV_FORM.editing = null;
  AV_FORM.fields = blankAvatarFields();
  renderAvatarForm();
}

function editAvatar(id) {
  const a = S.avatars.find(x => x.id === id);
  if (!a) return;
  const ap = a.appearance || {};
  AV_FORM.editing = id;
  AV_FORM.fields = blankAvatarFields();
  AV_FORM.fields.name = a.name || '';
  AV_FORM.fields.description = a.description || '';
  AV_FORM.fields.voice = a.voice || '';
  AV_FORM.fields.style = a.style || '';
  AV_FIELDS.concat(AV_FREE).forEach(k => { if (ap[k]) AV_FORM.fields[k] = ap[k]; });
  renderAvatarForm();
}

function renderAvatarForm() {
  const f = AV_FORM.fields;
  const edgeVoices = S.settings.edge_voices || [];
  const sec = (title, inner) => `
    <div class="av-sec"><div class="av-sec-title">${title}</div>${inner}</div>`;
  const grid2 = (pairs) => `<div class="row">${pairs.map(p =>
    `<div class="field"><label>${p[0]}</label>${p[1]}</div>`).join('')}</div>`;
  $('#view').innerHTML = `
    <div class="card av-form-pro" style="max-width:860px;margin:0 auto">
      <h2 class="sec" style="margin-top:0">${AV_FORM.editing ? '✏️ Editar avatar' : '🎭 Nuevo avatar PRO'}</h2>
      <div class="row">
        <div class="field" style="flex:1.2"><label>Nombre del personaje *</label>
          <input type="text" value="${esc(f.name)}" oninput="AV_FORM.fields.name=this.value" placeholder="Ej: Sofía Explora"></div>
        <div class="field"><label>${AV_LABELS.arquetipo}</label>${avSelect('arquetipo')}</div>
        <div class="field"><label>${AV_LABELS.personalidad}</label>${avSelect('personalidad')}</div>
      </div>
      <div class="field"><label>Personalidad / rol en detalle (afecta al guion)</label>
        <textarea rows="2" oninput="AV_FORM.fields.description=this.value"
          placeholder="Exploradora curiosa y enérgica que narra misterios con tono envolvente…">${esc(f.description)}</textarea></div>
      ${sec('🎨 Rostro', grid2([[AV_LABELS.piel, avSelect('piel')],
        [AV_LABELS.ojos_color, avSelect('ojos_color')], [AV_LABELS.ojos_forma, avSelect('ojos_forma')]])
        + grid2([[AV_LABELS.cabello_color, avSelect('cabello_color')],
        [AV_LABELS.cabello_largo, avSelect('cabello_largo')], [AV_LABELS.cabello_textura, avSelect('cabello_textura')]]))}
      ${sec('🧍 Cuerpo y estilo', grid2([[AV_LABELS.genero, avSelect('genero')],
        [AV_LABELS.edad, avSelect('edad')], [AV_LABELS.cuerpo, avSelect('cuerpo')]])
        + grid2([[AV_LABELS.ropa, avSelect('ropa')], [AV_LABELS.maquillaje, avSelect('maquillaje')],
        ['Accesorios distintivos', avFree('accesorios', 'Ej: aretes dorados, gafas de aviador')]])
        + grid2([['Referencia de influencer', avFree('referencia', 'Ej: Kylie Jenner, Chiara Ferragni')],
        ['Otros detalles (texto libre)', avFree('extras', 'Ej: cicatriz en la ceja, tatuaje de brújula')]]))}
      ${sec('🎙️ Voz y habla', grid2([[AV_LABELS.acento, avSelect('acento')],
        [AV_LABELS.jerga, avSelect('jerga')],
        ['Voz (edge-tts)', `<select id="av-voice-select" onchange="AV_FORM.fields.voice=this.value">
            <option value="">— sin voz fija —</option>
            ${edgeVoices.map(v => `<option value="${v.id}" ${f.voice === v.id ? 'selected' : ''}>${esc(v.name)}</option>`).join('')}
          </select>`]])
        + grid2([['Estilo visual por defecto', `<select onchange="AV_FORM.fields.style=this.value">
            <option value="">— sin estilo fijo —</option>
            ${S.styles.map(s => `<option value="${s.id}" ${f.style === s.id ? 'selected' : ''}>${s.emoji} ${esc(s.name)}</option>`).join('')}
          </select>`]]))}
      <small style="color:var(--muted);display:block;margin:4px 0 14px">💡 Cada característica se traduce a inglés y se inyecta en el retrato del avatar, en TODAS las escenas del video (consistencia del personaje) y en el guion (arquetipo, acento y jerga). Al elegir acento se sugiere una voz edge-tts acorde.</small>
      <div style="display:flex;gap:10px">
        <button class="btn primary" onclick="saveAvatar()">💾 Guardar avatar</button>
        <button class="btn ghost" onclick="AV_FORM.editing=null;renderAvatars()">Cancelar</button>
      </div>
    </div>`;
}

async function saveAvatar() {
  if (guardDemo()) return;
  const f = AV_FORM.fields;
  if (!f.name.trim()) return toast('Ponle un nombre al personaje', 'err');
  const appearance = {};
  AV_FIELDS.concat(AV_FREE).forEach(k => { const v = (f[k] || '').trim(); if (v) appearance[k] = v; });
  const body = { name: f.name.trim(), description: f.description.trim(),
                 appearance, voice: f.voice, style: f.style };
  try {
    if (AV_FORM.editing) await api(`/avatars/${AV_FORM.editing}`, { method: 'PATCH', body });
    else await api('/avatars', { method: 'POST', body });
    AV_FORM.editing = null;
    await refreshAll();
    renderAvatars();
    toast('Avatar guardado ✅', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

async function showAvatarPrompt(id) {
  let p;
  try { p = await api(`/avatars/${id}/prompt`); }
  catch (e) { return toast(e.message, 'err'); }
  const block = (title, text, hint) => `
    <div class="prompt-block">
      <div class="prompt-head"><b>${title}</b>${hint ? `<small>${hint}</small>` : ''}</div>
      <pre>${esc(text)}</pre>
      <button class="btn small ghost" onclick="copyText(this.previousElementSibling.textContent)">📋 Copiar</button>
    </div>`;
  const ov = document.createElement('div');
  ov.className = 'prompt-overlay';
  ov.onclick = e => { if (e.target === ov) ov.remove(); };
  ov.innerHTML = `<div class="prompt-modal card">
    <div class="row" style="align-items:center;margin-bottom:8px">
      <h3 style="margin:0">📄 Prompts de «${esc(p.name)}»</h3>
      <button class="btn small ghost" style="margin-left:auto" onclick="this.closest('.prompt-overlay').remove()">✕</button>
    </div>
    <small style="color:var(--muted)">Así de transparente es el motor: estos prompts exactos (generados con las características del menú desplegable) se envían a la IA.</small>
    ${block('🖼️ Prompt de retrato', p.portrait, 'para generar la cara oficial del personaje')}
    ${block('🎬 Prompt de escenas (consistencia)', p.scene, 'se añade a TODAS las escenas del video')}
    ${block('📝 Persona del guion', p.persona, 'influencia narración, acento y jerga')}
  </div>`;
  document.body.appendChild(ov);
}

function copyText(t) {
  navigator.clipboard.writeText(t.trim()).then(() => toast('Prompt copiado 📋', 'ok'))
    .catch(() => toast('No se pudo copiar', 'err'));
}

async function genAvatarImage(id, btn) {
  if (guardDemo()) return;
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Generando…'; }
  try {
    const r = await api(`/avatars/${id}/image`, { method: 'POST' });
    await refreshAll();
    renderAvatars();
    toast(r.method === 'gemini' ? 'Retrato IA generado 🎨' : 'Retrato generado (modo $0) 🎨', 'ok');
  } catch (e) { toast(e.message, 'err'); if (btn) { btn.disabled = false; btn.textContent = '🖼️ Imagen'; } }
}

async function delAvatar(id) {
  const a = S.avatars.find(x => x.id === id);
  if (!a || !confirm(`¿Eliminar el avatar «${a.name}»? Los videos ya creados no se tocan.`)) return;
  try { await api(`/avatars/${id}`, { method: 'DELETE' }); await refreshAll(); renderAvatars(); toast('Avatar eliminado'); }
  catch (e) { toast(e.message, 'err'); }
}

/* ── datos de muestra para la DEMO web sin backend ───────── */
const DEMO_STYLES = [
  {id:'graphic-novel',name:'Graphic Novel',emoji:'🖋️',desc:'Cómic negro con tinta dramática',grad:'linear-gradient(135deg,#1a1a2e,#e94560)'},
  {id:'neo-anime',name:'Neo-Anime',emoji:'🌸',desc:'Anime moderno de alta calidad',grad:'linear-gradient(135deg,#ff9a9e,#fad0c4)'},
  {id:'raw-reality',name:'Raw Reality',emoji:'📷',desc:'Fotorealismo crudo documental',grad:'linear-gradient(135deg,#485563,#29323c)'},
  {id:'pixar-3d',name:'Pixar 3D',emoji:'🎈',desc:'Animación 3D tierna y pulida',grad:'linear-gradient(135deg,#4facfe,#00f2fe)'},
  {id:'cine-blockbuster',name:'Cine Blockbuster',emoji:'🎬',desc:'Look de superproducción Hollywood',grad:'linear-gradient(135deg,#0f2027,#2c5364)'},
  {id:'epica-biblica',name:'Épica Bíblica',emoji:'📜',desc:'Historias sagradas con grandeza',grad:'linear-gradient(135deg,#c79081,#dfa579)'},
  {id:'terror-cartoon',name:'Terror Cartoon',emoji:'👻',desc:'Terror estilizado tipo Cartoon Network',grad:'linear-gradient(135deg,#42275a,#734b6d)'},
  {id:'pizarra-educativa',name:'Pizarra Educativa',emoji:'🏫',desc:'Explicaciones claras en pizarra',grad:'linear-gradient(135deg,#f5f7fa,#c3cfe2)'},
  {id:'vector-flat',name:'Vector Flat Design',emoji:'🔷',desc:'Moderno, corporativo, limpio',grad:'linear-gradient(135deg,#36d1dc,#5b86e5)'},
  {id:'retro-anime-90s',name:'Retro Anime 90s',emoji:'📺',desc:'Nostalgia VHS y celda animada',grad:'linear-gradient(135deg,#ee9ca7,#ffdde1)'},
  {id:'unreal-engine-5',name:'Unreal Engine 5',emoji:'🎮',desc:'Render hiperrealista de motor',grad:'linear-gradient(135deg,#141e30,#243b55)'},
  {id:'analog-horror',name:'Analog Horror',emoji:'📼',desc:'Terror de cintas VHS',grad:'linear-gradient(135deg,#000000,#434343)'},
  {id:'renaissance-oil',name:'Renaissance Oil',emoji:'🖼️',desc:'Óleo clásico con luz de museo',grad:'linear-gradient(135deg,#3e2723,#a1887f)'},
  {id:'retro-americana',name:'Retro Americana',emoji:'🛻',desc:'Pósters vintage años 50-70',grad:'linear-gradient(135deg,#e96443,#904e95)'},
  {id:'crude-stickman',name:'Crude Stickman',emoji:'✏️',desc:'Minimalismo viral de palitos',grad:'linear-gradient(135deg,#ffffff,#bdc3c7)'},
  {id:'cyber-glitch',name:'Cyber-Glitch',emoji:'💾',desc:'Cyberpunk con distorsión digital',grad:'linear-gradient(135deg,#fc466b,#3f5efb)'},
  {id:'acuarela-magica',name:'Acuarela Mágica',emoji:'🎨',desc:'Fantasía pintada a mano',grad:'linear-gradient(135deg,#a1c4fd,#c2e9fb)'},
  {id:'dark-fantasy',name:'Dark Fantasy',emoji:'🗡️',desc:'Grimdark épico y sombrío',grad:'linear-gradient(135deg,#232526,#414345)'},
  {id:'grand-theft',name:'Grand Theft',emoji:'🌴',desc:'Arte de portada estilo GTA',grad:'linear-gradient(135deg,#f7971e,#ffd200)'},
  {id:'custom-studio',name:'Custom Studio',emoji:'🎛️',desc:'Tu propio descriptor de estilo',grad:'linear-gradient(135deg,#8e2de2,#4a00e0)'},
  {id:'mri-brainrot',name:'MRI Brainrot',emoji:'🧠',desc:'Escaneos 3D absurdos virales',grad:'linear-gradient(135deg,#00c6ff,#0072ff)'},
  {id:'claymation',name:'Claymation',emoji:'🧸',desc:'Plastilina stop-motion artesanal',grad:'linear-gradient(135deg,#ffecd2,#fcb69f)'},
  {id:'bhangra-boo',name:'Barroqueremax',emoji:'👑',desc:'Lujo barroco maximalista',grad:'linear-gradient(135deg,#f6d365,#fda085)'},
  {id:'holo-ghost',name:'Holo-Ghost',emoji:'🛸',desc:'Hologramas espectrales futuristas',grad:'linear-gradient(135deg,#654ea3,#eaafc8)'},
  {id:'papercraft',name:'Papercraft',emoji:'📄',desc:'Dioramas de papel en capas',grad:'linear-gradient(135deg,#fbc2eb,#a6c1ee)'},
];
const DEMO_PROJECTS = [
  {id:'demo1',title:'El imperio romano en 60 segundos',status:'ready',format:'short',style:'epica-biblica',mode:'idea',updated_at:'demo',step_label:''},
  {id:'demo2',title:'3 inventos que hicieron millonarios',status:'published',format:'short',style:'vector-flat',mode:'url',updated_at:'demo',step_label:''},
  {id:'demo3',title:'El caso criminal sin resolver de 1974',status:'ready',format:'short',style:'analog-horror',mode:'idea',updated_at:'demo',step_label:''},
  {id:'demo4',title:'Por qué el océano aún es un misterio',status:'failed',format:'long',style:'unreal-engine-5',mode:'audio',updated_at:'demo',step_label:''},
];

function guardDemo() {
  if (S.demo) { toast('Acción solo disponible con el backend local — arranca el servidor :8000', 'err'); return true; }
  return false;
}

/* ── boot ────────────────────────────────────────────────── */
async function refreshAll() {
  const [stats, projects, factory, ideas] = await Promise.all([
    api('/stats'), api('/projects'), api('/factory'), api('/factory/ideas')]);
  S.stats = stats; S.projects = projects; S.factory = factory; S.ideas = ideas;
  try { S.avatars = await api('/avatars'); } catch { S.avatars = []; }
}

(async function boot() {
  setTheme(S.theme);
  $('#theme-btn').onclick = () => { setTheme(S.theme === 'dark' ? 'light' : 'dark'); if (S.view === 'settings') renderSettings(); };
  $$('.nav-item').forEach(n => n.onclick = () => nav(n.dataset.view));

  try {
    S.health = await api('/health');
    S.styles = await api('/styles');
    S.settings = await api('/settings');
    await refreshAll();
    S.settings.ext_pending = (await api('/extension/pending')).pending;
  } catch {
    S.demo = true;
    S.styles = DEMO_STYLES;
    S.stats = { today: 3, total: 27, ready: 22, published: 9, failed: 1, minutes: 84.5 };
    S.projects = DEMO_PROJECTS;
    S.factory = { enabled: true, times: ['07:00','12:30','19:00'], timezone: 'America/Bogota',
                  niche: 'historias reales impactantes', style: 'graphic-novel',
                  format: 'short', autopublish: false, pending_ideas: 2,
                  next_runs: [], running: false };
    S.ideas = ['La bailout del Titanic: lo que nadie cuenta', 'El mapa que cambió la Segunda Guerra'];
    S.settings = { gemini_key: true, whisper: true, youtube_configured: true, tts_provider: 'edge', ext_pending: 0 };
    S.health = { gemini: true, whisper: true, youtube: true };
  }

  updatePills();

  if (S.demo) {
    S.styles = S.styles.length ? S.styles : [];
    $('#greet-sub').textContent = 'MODO DEMO — inicia el servidor backend';
  }
  if (!S.chat.length) {
    S.chat = [{ role: 'bot', text: '¡Hola! Soy VÓRTICE 🤖, el agente de esta fábrica. '
      + 'Pídeme lo que quieras en lenguaje natural:\n'
      + '• «crea un video sobre el imperio romano»\n'
      + '• «muéstrame mis proyectos»\n'
      + '• «¿cómo va el video de las bermudas?»' }];
  }
  renderHome();
  // refresco suave de KPIs cada 20s
  setInterval(async () => { if (!S.demo && S.view === 'home') { try { S.stats = await api('/stats'); renderHome(); } catch {} } }, 20000);
})();

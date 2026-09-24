/* ============================================================
   YOUTUBE AUTOMATION v2.0 — Dashboard JS (vanilla, sin build)
   Vista Labsia mejorada: wizard 4 pasos + editor + fábrica + $0
   ============================================================ */
'use strict';

const S = {            // estado global
  view: 'home', theme: localStorage.getItem('yta-theme') || 'dark',
  demo: false, health: {}, styles: [], settings: {}, stats: {},
  projects: [], project: null, factory: null, ideas: [],
  wizard: null, es: null,
};

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
                  project: renderProject };
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

function renderProjectCards(list) {
  if (!list.length) return `<div class="card empty" style="grid-column:1/-1"><div class="big">🎬</div>Aún no hay proyectos. Crea tu primer video en 2 minutos.</div>`;
  return list.map(p => {
    const badge = p.status === 'ready' ? '<span class="badge ready">LISTO</span>'
      : p.status === 'published' ? '<span class="badge published">PUBLICADO</span>'
      : p.status === 'failed' ? '<span class="badge failed">ERROR</span>'
      : ['draft','queued'].includes(p.status) ? '<span class="badge draft">BORRADOR</span>'
      : '<span class="badge working">…' + esc(p.step_label || p.status) + '</span>';
    const thumb = p.thumbnail_url ? `/api/projects/${p.id}/thumbnail?v=${p.updated_at}` : '';
    return `<div class="card proj-card" onclick="openProject('${p.id}')">
      ${thumb ? `<img class="thumb" src="${thumb}" loading="lazy">` : `<div class="thumb" style="display:grid;place-items:center;font-size:34px">🎞️</div>`}
      <div class="body"><b>${esc(p.title)}</b>
        <div class="meta">${badge}<span>${esc(p.format === 'short' ? '9:16 Short' : '16:9 Largo')}</span></div>
      </div></div>`;
  }).join('');
}

/* ── vista: WIZARD CREAR (4 pasos como Labsia) ───────────── */
const W = { step: 1, mode: 'idea', format: 'short', style: 'auto',
            title: '', idea: '', script: '', url: '', custom: '', voice: '', tts: '' };

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
        <div class="field"><label>Voz (opcional, luego puedes cambiarla)</label>
          <select onchange="W.tts=this.value">
            <option value="">edge-tts · Salomé 🇨🇴 (gratis ilimitado)</option>
            <option value="gemini" ${S.health.gemini ? '' : 'disabled'}>Gemini TTS · Fenrir 🎖️ (premium)</option>
          </select></div>
        <div class="field"><label>Título interno (máx 60)</label>
          <input type="text" maxlength="60" value="${esc(W.title)}" oninput="W.title=this.value" placeholder="solo referencia, lo genera la IA si lo dejas vacío"></div>
      </div>`;
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
                   tts_provider: W.tts || null };
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
    <div style="margin-top:18px;display:flex;gap:10px;justify-content:center">
      <button class="btn danger small" onclick="cancelJob('${jobId}')">✕ Cancelar</button>
      <button class="btn ghost small" onclick="hideProgress()">Ocultar</button>
    </div></div></div>`;

  if (S.es) S.es.close();
  S.es = new EventSource(`/api/jobs/${jobId}/events`);
  S.es.onmessage = ev => {
    const d = JSON.parse(ev.data);
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
  $('#view').innerHTML = `
    <button class="btn ghost small" onclick="nav('projects')">← Volver</button>
    <div class="editor-head" style="margin-top:16px">
      ${p.status === 'ready' ? `<video controls src="/api/projects/${p.id}/video"></video>` : ''}
      <div style="flex:1;min-width:240px">
        <h2 style="margin-bottom:6px">${esc(p.title)} ${p.status === 'published' ? '<span class="badge published">PUBLICADO</span>' : p.status === 'ready' ? '<span class="badge ready">LISTO</span>' : ''}</h2>
        <p style="color:var(--muted);font-size:13px;margin-bottom:12px">
          ${esc(p.format === 'short' ? '9:16 Short' : '16:9')} · ${esc(getStyleName(p.style))} · modo ${esc(p.mode)} · ${scenes.length} escenas
          ${p.youtube_id ? ` · <a href="https://youtube.com/watch?v=${p.youtube_id}" target="_blank">ver en YouTube ↗</a>` : ''}</p>
        <div style="display:flex;gap:9px;flex-wrap:wrap">
          ${['draft','failed'].includes(p.status) ? `<button class="btn primary" onclick="startJob('${p.id}')">▶️ Generar video</button>` : ''}
          ${p.status === 'ready' ? `<button class="btn primary" onclick="goPublish('${p.id}')">📺 Publicar en YouTube</button>` : ''}
          ${p.status === 'ready' ? `<a class="btn" href="/api/projects/${p.id}/video" download>⬇️ Descargar MP4</a>` : ''}
          <a class="btn ghost" href="/api/projects/${p.id}/subtitles.srt" download>💬 Subtítulos SRT</a>
          <button class="btn danger" onclick="delProject('${p.id}')">🗑️</button>
        </div>
        ${p.error ? `<p style="color:var(--err);font-size:12.5px;margin-top:10px">⚠️ ${esc(p.error)}</p>` : ''}
      </div>
    </div>
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

/* ── vista: AJUSTES ──────────────────────────────────────── */
function renderSettings() {
  const s = S.settings;
  $('#view').innerHTML = `
    <h2 class="sec">⚙️ Ajustes</h2>
    <div class="factory-grid">
      <div class="card">
        <b>🔌 Estado del sistema</b>
        <div class="idea-item"><span>Gemini (guion + imágenes + TTS)</span><b>${s.gemini_key ? '✅' : '❌ falta GEMINI_API_KEY'}</b></div>
        <div class="idea-item"><span>Whisper (alineación de subtítulos)</span><b>${s.whisper ? '✅' : '⚠️ modo estimado'}</b></div>
        <div class="idea-item"><span>YouTube API</span><b>${s.youtube_configured ? '✅' : '❌ sin client_secret'}</b></div>
        <div class="idea-item"><span>TTS por defecto</span><b>${esc(s.tts_provider || 'edge')}</b></div>
        <div class="idea-item"><span>Imágenes en cola de la extensión</span><b>${s.ext_pending ?? 0}</b></div>
        <p style="color:var(--muted);font-size:12.5px;margin-top:14px">Las claves se configuran en el archivo <code>backend/.env</code>. Sin clave de Gemini, el sistema funciona en modo degradado (imágenes placeholder + solo edge-tts).</p>
      </div>
      <div class="card">
        <b>🎨 Apariencia</b>
        <div class="toggle" style="margin-top:12px" onclick="setTheme(S.theme==='dark'?'light':'dark');renderSettings()">
          <div class="switch ${S.theme === 'dark' ? '' : 'on'}"></div>
          <div><b>Tema claro</b><div style="color:var(--muted);font-size:12.5px">clic para alternar</div></div>
        </div>
        <div style="height:16px"></div>
        <b>🧩 Extensión Chrome (Plan B)</b>
        <p style="color:var(--muted);font-size:12.5px;margin:8px 0">Carga <code>extension/</code> en chrome://extensions (modo desarrollador). Las imágenes que captures en ImageFX llegarán aquí como respaldo cuando Gemini falle o llegue a su cuota.</p>
      </div>
    </div>`;
}

/* ── datos de muestra para la DEMO web sin backend ───────── */
const DEMO_STYLES = [
  {id:'auto',name:'Auto',emoji:'✨',desc:'La IA elige la estética según el tema (recomendado)',grad:'linear-gradient(135deg,#8e2de2,#4a00e0)'},
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
                  niche: 'historias reales impactantes', style: 'auto',
                  format: 'short', autopublish: false, pending_ideas: 2,
                  next_runs: [], running: false };
    S.ideas = ['La bailout del Titanic: lo que nadie cuenta', 'El mapa que cambió la Segunda Guerra'];
    S.settings = { gemini_key: true, whisper: true, youtube_configured: true, tts_provider: 'edge', ext_pending: 0 };
    S.health = { gemini: true, whisper: true, youtube: true };
  }

  const pills = [['pill-gemini', S.health.gemini], ['pill-whisper', S.health.whisper], ['pill-yt', S.health.youtube]];
  pills.forEach(([id, on]) => { const el = $('#' + id); if (el) $('.dot', el).classList.toggle('on', !!on); });

  if (S.demo) {
    S.styles = S.styles.length ? S.styles : [];
    $('#greet-sub').textContent = 'MODO DEMO — inicia el servidor backend';
  }
  renderHome();
  // refresco suave de KPIs cada 20s
  setInterval(async () => { if (!S.demo && S.view === 'home') { try { S.stats = await api('/stats'); renderHome(); } catch {} } }, 20000);
})();

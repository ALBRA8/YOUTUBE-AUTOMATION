/* ============================================================
   app-core.js — INT-088 · núcleo de la SPA
   Estado global (S), api(), toast(), $/esc, nav(), tema, pills,
   inicio/ajustes/tendencias/agente y el arranque (__appBoot) que
   el loader de app.js invoca cuando los 5 módulos están cargados.
   Dividido desde app.js (monolito) sin cambiar comportamiento.
   ============================================================ */
'use strict';

const S = {            // estado global
  view: 'home', theme: localStorage.getItem('yta-theme') || 'dark',
  demo: false, health: {}, styles: [], settings: {}, stats: {},
  projects: [], project: null, factory: null, ideas: [], avatars: [],
  niches: [], library: [], brandProfiles: [],
  chat: [], chatBusy: false, chatImage: null,
  cerebros: [], cerebroActivo: null,
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
  // v2.36: normaliza tipos no estándar ('error'/'success'/'info' → clases CSS existentes)
  const kMap = { error: 'err', success: 'ok', ok: 'ok', err: 'err', info: '' };
  t.className = 'toast ' + (kMap[kind] !== undefined ? kMap[kind] : kind);
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
  // INT-092 · la pestaña ✨ Crear se eliminó del menú: la creación vive SOLO
  // en Inicio (5 modalidades 1-clic → modal rápido). Cualquier navegación
  // antigua a 'create' (atajos, historial, agente) redirige limpia a Inicio.
  if (view === 'create') view = 'home';
  // v2.11.1 · entrar a Proyectos desde cualquier vista (excepto volver del detalle) = ventana de nichos
  if (view === 'projects' && S.view !== 'project') _PROJ_NICHO = null;
  S.view = view;
  $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.view === view));
  refreshSidebar();
  const views = { home: renderHome, projects: renderProjects,
                  factory: renderFactory, publish: renderPublish, settings: renderSettings,
                  project: renderProject, agent: renderAgent, avatars: renderAvatars,
                  trends: renderTrends, mcp: renderMCP, clipper: renderClipper };
  (views[view] || renderHome)();
}

/* v2.10.2: sidebar sin explorador ni CTA (petición del usuario) — la gestión
   de proyectos vive en la vista 🗂️ Proyectos (árbol de nichos).
   refreshSidebar se conserva como no-op: nav()/init() la invocan. */
function refreshSidebar() {}

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

    <h2 class="sec" style="display:flex; justify-content:space-between; align-items:center;">
      <span># ¿Cómo quieres empezar hoy?</span>
      <span class="hint" style="font-size:12px; color:var(--muted); font-weight:normal;">5 Modalidades Rápidas · 1-Clic</span>
    </h2>
    <div class="modes labsia-modes" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:14px; margin-bottom:28px;">
      <div class="card mode-card labsia-card" onclick="openQuickCreateModal('script')" style="cursor:pointer; border-radius:12px; transition:transform 0.15s, border-color 0.15s;">
        <div style="font-size:28px; margin-bottom:8px;">📄</div>
        <h3 style="font-size:16px; margin:0 0 6px 0; font-weight:700;">Desde Guion</h3>
        <p style="font-size:12px; color:var(--muted); margin:0; line-height:1.45;">Pega tu texto y genera el video escena por escena.</p>
        <span style="display:inline-block; margin-top:12px; color:var(--accent); font-weight:700; font-size:12px;">Comenzar →</span>
      </div>
      <div class="card mode-card labsia-card" onclick="openQuickCreateModal('idea')" style="cursor:pointer; border-radius:12px; transition:transform 0.15s, border-color 0.15s;">
        <div style="font-size:28px; margin-bottom:8px;">💡</div>
        <h3 style="font-size:16px; margin:0 0 6px 0; font-weight:700;">Desde Idea</h3>
        <p style="font-size:12px; color:var(--muted); margin:0; line-height:1.45;">Convierte un concepto en un guion viral completo.</p>
        <span style="display:inline-block; margin-top:12px; color:var(--accent); font-weight:700; font-size:12px;">Comenzar →</span>
      </div>
      <div class="card mode-card labsia-card" onclick="openQuickCreateModal('product')" style="cursor:pointer; border-radius:12px; transition:transform 0.15s, border-color 0.15s; position:relative;">
        <span class="tag" style="position:absolute; top:12px; right:12px; font-size:9px; padding:3px 7px; background:linear-gradient(135deg,#f59e0b,#d97706); color:#000; font-weight:800;">V4V E-COM</span>
        <div style="font-size:28px; margin-bottom:8px;">🛍️</div>
        <h3 style="font-size:16px; margin:0 0 6px 0; font-weight:700;">Desde Producto</h3>
        <p style="font-size:12px; color:var(--muted); margin:0; line-height:1.45;">Pega el link de tu tienda/Amazon y crea un anuncio UGC viral.</p>
        <span style="display:inline-block; margin-top:12px; color:var(--accent); font-weight:700; font-size:12px;">Comenzar →</span>
      </div>
      <div class="card mode-card labsia-card" onclick="openQuickCreateModal('url')" style="cursor:pointer; border-radius:12px; transition:transform 0.15s, border-color 0.15s;">
        <span class="tag" style="position:absolute; top:12px; right:12px; font-size:9px; padding:3px 7px;">KILLER</span>
        <div style="font-size:28px; margin-bottom:8px;">🔗</div>
        <h3 style="font-size:16px; margin:0 0 6px 0; font-weight:700;">Desde URL</h3>
        <p style="font-size:12px; color:var(--muted); margin:0; line-height:1.45;">Usa un artículo o video web y crea su versión original.</p>
        <span style="display:inline-block; margin-top:12px; color:var(--accent); font-weight:700; font-size:12px;">Comenzar →</span>
      </div>
      <div class="card mode-card labsia-card" onclick="openQuickCreateModal('audio')" style="cursor:pointer; border-radius:12px; transition:transform 0.15s, border-color 0.15s;">
        <div style="font-size:28px; margin-bottom:8px;">🎙️</div>
        <h3 style="font-size:16px; margin:0 0 6px 0; font-weight:700;">Desde Audio</h3>
        <p style="font-size:12px; color:var(--muted); margin:0; line-height:1.45;">Sincroniza y alinea la animación con tu propia voz.</p>
        <span style="display:inline-block; margin-top:12px; color:var(--accent); font-weight:700; font-size:12px;">Comenzar →</span>
      </div>
    </div>

    <h2 class="sec">🗂️ Proyectos recientes <a class="hint" href="#" onclick="nav('projects');return false">ver todos →</a></h2>
    <div class="proj-grid">${renderProjectCards(S.projects.slice(0, 4))}</div>`;
}

function closeOverlay() {
  $('#overlay-root').innerHTML = '';
  document.removeEventListener('keydown', nichoEscClose);
  document.removeEventListener('keydown', qcEscClose);  // INT-080: fuga de listener del Quick-Create
}

function updatePills() {
  const pills = [['pill-gemini', S.health.gemini], ['pill-whisper', S.health.whisper], ['pill-yt', S.health.youtube],
                 ['pill-flow', !!(S.mcp && S.mcp['google-flow'] && S.mcp['google-flow'].state === 'connected')],
                 ['pill-nblm', !!(S.mcp && S.mcp.notebooklm && S.mcp.notebooklm.state === 'connected')]];
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
  const hfChip = c.hf_token_set
    ? `<span class="cfg-status ok">✅ Token guardado · ${esc(c.hf_token_masked || '•••')}</span>`
    : `<span class="cfg-status err">⚠️ Sin token — los avatares salen SIN lip-sync (fail-open)</span>`;

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
        <b>👄 Lip-sync de avatares (Hugging Face)</b> <span style="float:right">${hfChip}</span>
        <div class="keyrow" style="margin-top:14px">
          <input type="password" id="cfg-hf" autocomplete="off" spellcheck="false"
                 placeholder="${c.hf_token_set ? 'Escribe un token nuevo para reemplazar ' + esc(c.hf_token_masked || '') : 'hf_… (token de lectura, gratis)'}">
          <button class="eye" onclick="const i=document.getElementById('cfg-hf');i.type=i.type==='password'?'text':'password'" title="Mostrar/ocultar">👁️</button>
        </div>
        <div class="cfg-actions">
          <button class="btn primary small" onclick="saveCfg({HF_TOKEN: document.getElementById('cfg-hf').value}, 'Token HF guardado — lip-sync activado sin reiniciar')">💾 Guardar token</button>
        </div>
        <div class="hintline">Token <b>gratis</b> en <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noopener">huggingface.co/settings/tokens</a> (permiso Read). Acepta también la licencia de <a href="https://huggingface.co/ByteDance/LatentSync" target="_blank" rel="noopener">ByteDance/LatentSync</a> con tu cuenta (botón «Agree»).
        Activa el <b>lip-sync video→video</b> (labios sincronizados con la voz) y la animación del avatar. Se guarda en <code class="mini">backend/.env</code> y <b>aplica sin reiniciar</b>. Sin token el render sigue (fail-open) pero los avatares salen con la boca estática.</div>
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
          onclick="saveCfg({TTS_PROVIDER: document.getElementById('cfg-tts').value, EDGE_TTS_VOICE: document.getElementById('cfg-edge-voice').value, GEMINI_TTS_VOICE: document.getElementById('cfg-gemini-voice').value, TTS_RATE: document.getElementById('cfg-rate').value}, 'Voz guardada')">💾 Guardar voz</button>
          <button class="btn small" onclick="openVoiceGallery({target:'global'})" title="Abrir Galería de Voces con Preescucha">🎙️ Galería de Voces</button></div>
        <div class="hintline">Si un proveedor falla, el sistema cae automáticamente al otro. Nunca se bloquea el render.</div>
      </div>

      <div class="card">
        <b>🏢 Perfil de Canal / Marca</b> <span class="badge" style="float:right;background:rgba(99,102,241,.15);color:var(--accent2);border:1px solid rgba(99,102,241,.3)">INT-042</span>
        <div style="margin-top:12px;font-size:13px;color:var(--muted);line-height:1.5">
          Configura identidades fijas para cada uno de tus canales: tono de voz, audiencia, estilo visual, voz neuronal, preset de subtítulos y directivas estrictas de guion.
        </div>
        <div class="cfg-actions" style="margin-top:14px">
          <button class="btn primary small" onclick="openBrandProfilesModal({target:'settings'})">🏢 Administrar Canales y Marcas</button>
        </div>
        <div class="hintline">Se autocompleta con 1 clic en el asistente de creación para mantener la consistencia de cada canal.</div>
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

      <div class="card" id="backups-card">
        <b>💾 Copias de seguridad</b> <span style="float:right"><button class="btn ghost small" onclick="loadBackups()">↻ Actualizar</button></span>
        <div id="backups-body" style="color:var(--muted);font-size:13px;margin-top:12px">Cargando…</div>
      </div>

    </div>`;
  if (!S.demo) loadBackups();
}

/* v2.12.2 · backups (hallazgo auditoría: la DB moría sin réplica) */
async function loadBackups() {
  const body = document.getElementById('backups-body');
  if (!body) return;
  try {
    const d = await api('/backups');
    const bks = d.backups || [];
    const ago = ts => { const m = Math.round((Date.now() / 1000 - ts) / 60);
      return m < 60 ? `hace ${m} min` : `hace ${Math.round(m / 60)} h`; };
    const rows = bks.slice(0, 6).map(b => `
      <div class="idea-item doctor-item"><span>📦 ${esc(b.name.replace('yt_automation_', '').replace('.db', ''))} <small>${(b.size / 1048576).toFixed(1)} MB</small></span>
      <span><small>${ago(b.ts)}</small> <button class="btn ghost small" onclick="restoreBackup('${esc(b.name)}')" title="Restaura esta copia (antes crea una de seguridad)">Restaurar</button></span></div>`).join('');
    body.innerHTML = `
      <div style="margin-bottom:8px">Copia automática al arrancar y cada <b>${d.interval_h} h</b> · se guardan <b>${d.keep}</b> · incluye DB + token YouTube + .env.<br>
      <small>Disaster recovery: copia <code class="mini">backend/data/backups/</code> a otro disco y pega los archivos como indica la cabecera de <code class="mini">services/backup.py</code>.</small></div>
      ${rows || '<div style="color:var(--muted)">Aún no hay backups</div>'}
      <div class="cfg-actions" style="margin-top:10px">
        <button class="btn primary small" onclick="createBackup()">💾 Crear backup ahora</button>
      </div>`;
  } catch (e) { body.innerHTML = '⚠️ ' + e.message; }
}

async function createBackup() {
  try {
    const r = await api('/backups', { method: 'POST' });
    toast(r.message || 'Backup creado', 'ok');
    loadBackups();
  } catch (e) { toast('⚠️ ' + e.message); }
}

async function restoreBackup(name) {
  if (!confirm(`¿Restaurar «${name}»?\nSe sustituye la base de datos ACTUAL (antes se crea una copia de seguridad automática).`)) return;
  try {
    const r = await api('/backups/restore', { method: 'POST', body: { name } });
    toast(r.message || 'Restaurado', 'ok');
    setTimeout(() => location.reload(), 1600);
  } catch (e) { toast('⚠️ ' + e.message); }
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
          return `<div class="idea-item" style="cursor:pointer" onclick="openQuickCreateModal('idea',${js})">
            <span><b>${esc(i.title || '')}</b><br><span style="color:var(--muted);font-size:12px">${esc(i.angle || '')} — ${esc(i.why || '')}</span></span>
            <b style="color:var(--accent)">→ crear</b></div>`;
        }).join('')}
      </div>`;
  } catch (e) {
    out.innerHTML = `<div class="card empty" style="color:var(--err)">❌ ${esc(e.message)}</div>`;
  }
}

/* ── vista: AGENTE (Agente General · INT-028 absorbe VÓRTICE — entiende la fábrica y ejecuta) ── */
const engineTag = e => !e || e === 'local' ? ''
  : e === 'confirm' ? ' · ejecutado ✓'
  : e === 'gemini' ? ' · Gemini'
  : ' · ' + String(e).replace(/^nvidia:/, '').split('/').pop();

function renderAgent() {
  $('#greet').innerHTML = `Agente General 🤖<small id="greet-sub">Entiende tu fábrica: pregunta, crea nichos, lanza videos, limpia fallidos</small>`;
  const msgs = S.chat.map((m, i) => {
    if (m.role === 'user')
      return `<div class="chat-msg user"><div class="bubble">${m.img ? `<img class="chat-img" src="${m.img}" alt="adjunto">` : ''}${mmd(m.text)}</div><div class="who">Tú</div></div>`;
    let extra = '';
    if (m.project) extra += `<div class="chat-proj" onclick="openProject('${m.project.id}')">🎬 ${esc(m.project.title)} <small>ver proyecto →</small></div>`;
    if (m.projects && m.projects.length)
      extra = m.projects.map(p =>
        `<div class="chat-proj" onclick="openProject('${p.id}')">${p.status === 'ready' ? '✅' : p.status === 'failed' ? '❌' : '🎞️'} ${esc(p.title)} <small>${esc(p.status)}</small></div>`).join('');
    const confirmUI = m.pending && !m.confirmDone
      ? `<div class="chat-confirm"><button class="btn small danger" onclick="resolveConfirm(${i},true)">✓ Sí, hacerlo</button>
         <button class="btn small ghost" onclick="resolveConfirm(${i},false)">✕ Cancelar</button></div>` : '';
    return `<div class="chat-msg bot"><div class="bubble">${mmd(m.text)}${confirmUI}${extra}</div><div class="who">AGENTE${engineTag(m.engine)}</div></div>`;
  }).join('') + (S.chatBusy
    ? `<div class="chat-msg bot"><div class="bubble typing">El agente está pensando<span class="dots">…</span></div></div>` : '');
  const chips = ['¿Qué puedes hacer?',
                 'Resume el estado de mis proyectos',
                 '¿Qué nichos tengo?',
                 'Crea un nicho de deportes extremos',
                 'Borra los proyectos fallidos'];
  // v2.12.1 · barra de CEREBROS (multi-modelo NVIDIA con estado vivo)
  const act = S.cerebros.find(c => c.alias === S.cerebroActivo);
  const cerebroBar = S.cerebros.length ? `
    <div class="cerebro-bar">
      <span class="cb-label">🧠 Cerebro:</span>
      ${S.cerebros.map(c => `
        <button class="cb-chip ${c.active ? 'active' : ''}" onclick="pickCerebro('${c.alias}')"
                title="${esc(c.desc)}${c.error ? ' — ' + esc(c.error) : ''}">
          ${c.emoji} ${esc(c.name)}<i class="cb-dot ${c.status}"></i>${c.status === 'ok' ? `<small>${c.latency}s</small>` : ''}${c.vision ? '<small>👁️</small>' : ''}
        </button>`).join('')}
    </div>` : '';
  const imgPreview = S.chatImage
    ? `<div class="chat-imgprev"><img src="${S.chatImage}" alt="preview">
       <button class="modal-x" onclick="quitChatImg()" title="Quitar imagen">✕</button>
       <small class="cb-label">imagen adjunta — pídeme que la analice</small></div>` : '';
  $('#view').innerHTML = `
    <div class="chat-wrap">
      <div class="chat-scroll" id="chat-scroll">${msgs}</div>
      <div class="chat-chips">${chips.map(c => `<button class="chip" onclick="sendChat(${JSON.stringify(c).replace(/"/g, '&quot;')})">${esc(c)}</button>`).join('')}</div>
      ${cerebroBar}
      ${imgPreview}
      <div class="chat-input">
        ${act && act.vision ? `<button class="cb-clip" onclick="$('#chat-file').click()" title="Adjuntar imagen (este cerebro ve 👁️)">📎</button>` : ''}
        <input type="text" id="chat-text" placeholder="Pregunta o pide: crear nicho, lanzar video, borrar fallidos…"
               onkeydown="if(event.key==='Enter')sendChat()">
        <button class="btn primary" id="chat-send" onclick="sendChat()">➤</button>
      </div>
      <input type="file" id="chat-file" accept="image/png,image/jpeg,image/webp" style="display:none" onchange="onChatFile(this)">
    </div>`;
  const sc = $('#chat-scroll'); sc.scrollTop = sc.scrollHeight;
  if (!S.demo && !S.chatBusy) $('#chat-text').focus();
}

/* v2.12.1 · cambiar de cerebro (persistente en el backend) */
async function pickCerebro(alias) {
  try {
    const r = await api('/cerebros', { method: 'POST', body: { alias } });
    toast(r.message || 'Cerebro cambiado', 'ok');
    const cb = await api('/cerebros');
    S.cerebros = cb.cerebros || []; S.cerebroActivo = cb.activo;
    renderAgent();
  } catch (e) { toast('⚠️ ' + e.message); }
}

/* v2.12.1 · adjuntar imagen para cerebros con visión */
function onChatFile(input) {
  const f = input.files && input.files[0];
  input.value = '';
  if (!f) return;
  if (f.size > 4 * 1024 * 1024) { toast('⚠️ Imagen demasiado grande (máx 4MB)'); return; }
  const rd = new FileReader();
  rd.onload = () => { S.chatImage = String(rd.result); renderAgent(); };
  rd.readAsDataURL(f);
}
function quitChatImg() { S.chatImage = null; renderAgent(); }

function mmd(text) {
  // mini-markdown: **negrita**, saltos y listas simples → HTML seguro
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/«(.+?)»/g, '«<i>$1</i>»')
    .replace(/\n/g, '<br>');
}

async function sendChat(preset, confirmPayload) {
  const inp = $('#chat-text');
  const text = (typeof preset === 'string' ? preset : inp?.value || '').trim();
  if (S.chatBusy) return;
  if (guardDemo()) return;
  if (!confirmPayload && !text) return;
  if (!confirmPayload) {
    S.chat.push({ role: 'user', text, img: S.chatImage || undefined });
    if (inp) inp.value = '';
  }
  S.chatBusy = true;
  renderAgent();
  try {
    const body = confirmPayload
      ? { confirm: confirmPayload }
      : { message: text, history: S.chat.slice(-8).map(m => ({ role: m.role, text: m.text })),
          cerebro: S.cerebroActivo || undefined, image: S.chatImage || undefined };
    const r = await api('/chat', { method: 'POST', body });
    if (r.needs_confirm && r.pending) {
      S.chat.push({ role: 'bot', text: r.reply || '¿Confirmas?', engine: r.engine,
                    pending: r.pending });
    } else {
      S.chat.push({ role: 'bot', text: r.reply || 'Hecho ✅', engine: r.engine,
                    project: r.project, projects: r.projects });
    }
    S.chatImage = null;
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

/* v2.12 · confirmación de acciones destructivas del agente */
async function resolveConfirm(i, ok) {
  const m = S.chat[i];
  if (!m || !m.pending || m.confirmDone) return;
  m.confirmDone = true;
  if (!ok) {
    S.chat.push({ role: 'bot', text: 'Cancelado ✋ No toqué nada.' });
    renderAgent();
    return;
  }
  await sendChat(undefined, m.pending);
}

/* ── vista: AVATARES (v2.1.1 PRO con menús desplegables) ── */
function copyText(t) {
  navigator.clipboard.writeText(t.trim()).then(() => toast('Prompt copiado 📋', 'ok'))
    .catch(() => toast('No se pudo copiar', 'err'));
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
  try { S.niches = await api('/niches'); } catch { S.niches = []; }
  try { S.brandProfiles = (await api('/brand-profiles')).profiles || []; } catch { S.brandProfiles = S.brandProfiles || []; }
  try { S.library = await api('/library'); } catch { S.library = []; }
  try { const cb = await api('/cerebros'); S.cerebros = cb.cerebros || []; S.cerebroActivo = cb.activo; } catch { /* sin clave NVIDIA */ }
  refreshSidebar();
}

window.__appBoot = async function boot() {
  await (window.__authReady || Promise.resolve());  // login con clave maestra (auth.js)
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
  // INT-092: el selector de plantillas genéricas se purgó de la UI — sin
  // precarga de catálogo; POST /api/templates sigue vivo para el backend.

  if (S.demo) {
    S.styles = S.styles.length ? S.styles : [];
    $('#greet-sub').textContent = 'MODO DEMO — inicia el servidor backend';
  }
  if (!S.chat.length) {
    S.chat = [{ role: 'bot', text: '¡Hola! Soy el Agente General 🤖, el cerebro de esta fábrica. '
      + 'Pídeme lo que quieras en lenguaje natural:\n'
      + '• «crea un video sobre el imperio romano»\n'
      + '• «muéstrame mis proyectos»\n'
      + '• «¿cómo va el video de las bermudas?»' }];
  }
  renderHome();
  // refresco suave de KPIs cada 20s
  setInterval(async () => { if (!S.demo && S.view === 'home') { try { S.stats = await api('/stats'); renderHome(); } catch {} } }, 20000);
  // refresco del explorador de proyectos del sidebar cada 15s (estados en vivo)
  setInterval(async () => {
    if (S.demo || document.hidden) return;
    try { S.projects = await api('/projects'); refreshSidebar(); } catch {}
  }, 15000);
};

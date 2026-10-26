/* ============================================================
   YOUTUBE AUTOMATION v2.0 — Dashboard JS (vanilla, sin build)
   Vista Labsia mejorada: wizard 4 pasos + editor + fábrica + $0
   ============================================================ */
'use strict';

const S = {            // estado global
  view: 'home', theme: localStorage.getItem('yta-theme') || 'dark',
  demo: false, health: {}, styles: [], settings: {}, stats: {},
  projects: [], project: null, factory: null, ideas: [], avatars: [],
  niches: [], library: [],
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
  // v2.11.1 · entrar a Proyectos desde cualquier vista (excepto volver del detalle) = ventana de nichos
  if (view === 'projects' && S.view !== 'project') _PROJ_NICHO = null;
  S.view = view;
  $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.view === view));
  refreshSidebar();
  const views = { home: renderHome, create: renderCreate, projects: renderProjects,
                  factory: renderFactory, publish: renderPublish, settings: renderSettings,
                  project: renderProject, agent: renderAgent, avatars: renderAvatars,
                  trends: renderTrends, mcp: renderMCP, clipper: renderClipper };
  (views[view] || renderHome)();
}

/* ── v2.7 · sidebar modular: CTA nicho + explorador con scroll ── */
function openNicheCreator() {
  nav('create'); W.mode = 'nicho'; W.step = 2; renderCreate();
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
    <div class="agent-banner" onclick="nav('agent')">
      <div class="ab-ico">🤖</div>
      <div class="ab-txt"><b>Agente General</b>
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

    <h2 class="sec" style="display:flex; justify-content:space-between; align-items:center;">
      <span># ¿Cómo quieres empezar hoy?</span>
      <span class="hint" style="font-size:12px; color:var(--muted); font-weight:normal;">4 Modalidades Rápidas · 1-Clic</span>
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

/* ── MODAL DE CREACIÓN RÁPIDA 1-CLIC (Estilo LabsIA · $0.00) ── */
const QC_STATE = {
  mode: 'idea',
  format: 'short',
  pacing: 'normal',
  style: 'auto',
  subtitles: 'shorts',
  voice: '',
  title: '',
  text: '',
  url: '',
  audioFile: null
};

function openQuickCreateModal(mode) {
  QC_STATE.mode = mode || 'idea';
  QC_STATE.text = '';
  QC_STATE.url = '';
  QC_STATE.audioFile = null;

  renderQuickCreateModal();
  document.addEventListener('keydown', qcEscClose);
}

function qcEscClose(e) {
  if (e.key === 'Escape') closeOverlay();
}

function renderQuickCreateModal() {
  const m = QC_STATE.mode;
  const modes = [
    { id: 'script', emoji: '📜', name: 'Desde Guion' },
    { id: 'idea', emoji: '💡', name: 'Desde Idea' },
    { id: 'product', emoji: '🛍️', name: 'Desde Producto (UGC Ad)' },
    { id: 'url', emoji: '🔗', name: 'Desde URL' },
    { id: 'audio', emoji: '🎙️', name: 'Desde Audio' },
  ];

  const tabButtons = modes.map(item => `
    <button type="button" class="qc-tab ${m === item.id ? 'active' : ''}" onclick="qcSwitchMode('${item.id}')">
      <span>${item.emoji}</span> <span>${item.name}</span>
    </button>
  `).join('');

  let inputField = '';
  if (m === 'script') {
    inputField = `
      <div class="field" style="margin-bottom:14px;">
        <label style="font-size:13px; font-weight:700; margin-bottom:6px; display:block;">📜 Pega tu guion completo</label>
        <textarea id="qc-input-text" rows="6" placeholder="Escribe o pega aquí tu guion escena por escena..." style="width:100%; border-radius:10px; padding:12px; font-size:13.5px; line-height:1.5;">${esc(QC_STATE.text)}</textarea>
      </div>`;
  } else if (m === 'idea') {
    inputField = `
      <div class="field" style="margin-bottom:14px;">
        <label style="font-size:13px; font-weight:700; margin-bottom:6px; display:block;">💡 Tu idea o concepto viral (1 frase)</label>
        <input type="text" id="qc-input-text" placeholder="Ej: 5 errores mortales al invertir tu primer sueldo" value="${esc(QC_STATE.text)}" style="width:100%; border-radius:10px; padding:12px; font-size:13.5px;">
        <small style="color:var(--muted); display:block; margin-top:5px;">La IA estructurará el gancho viral, escenas y llamada a la acción.</small>
      </div>`;
    } else if (m === 'product') {
    inputField = `
      <div class="field" style="margin-bottom:14px;">
        <label style="font-size:13px; font-weight:700; margin-bottom:6px; display:block;">🛍️ URL de tienda (Shopify, Amazon, MercadoLibre) o Nombre del Producto</label>
        <input type="text" id="qc-input-text" placeholder="https://mitienda.com/products/zapato-pro o 'Cafetera Espresso Portatil OutIn'" value="${esc(QC_STATE.text)}" style="width:100%; border-radius:10px; padding:12px; font-size:13.5px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px;">
          <small style="color:var(--muted);">Fórmula UGC inspirada en v4v.ai: extrae beneficios y redacta guion de alta conversión.</small>
          <select id="qc-ugc-angle" style="padding:4px 8px; font-size:11.5px; border-radius:6px;" onchange="QC_STATE.ugcAngle=this.value">
            <option value="3_reasons" ${(QC_STATE.ugcAngle==='3_reasons'||!QC_STATE.ugcAngle)?'selected':''}>⭐ 3 Razones para comprar</option>
            <option value="problem_solution" ${QC_STATE.ugcAngle==='problem_solution'?'selected':''}>💡 Problema vs Solución</option>
            <option value="dont_buy_before" ${QC_STATE.ugcAngle==='dont_buy_before'?'selected':''}>⚠️ No compres antes de ver esto</option>
            <option value="honest_review" ${QC_STATE.ugcAngle==='honest_review'?'selected':''}>📦 Review Honesta / Unboxing</option>
          </select>
        </div>
        <div style="display:flex; gap:10px; margin-top:12px; flex-wrap:wrap; background:rgba(255,255,255,0.02); padding:10px; border-radius:10px; border:1px solid var(--border);">
          <div style="flex:1; min-width:180px;">
            <label style="font-size:11.5px; font-weight:700; color:var(--muted); margin-bottom:4px; display:block;">🏷️ Sticker de Conversión (INT-055)</label>
            <select id="qc-badge-type" style="width:100%; padding:6px 10px; font-size:12px; border-radius:6px;" onchange="QC_STATE.badgeType=this.value">
              <option value="rating" selected>⭐ Rating 4.9★ (+14k Reviews)</option>
              <option value="discount">🔥 -50% OFF Flash Sale</option>
              <option value="shipping">🚚 Envío Gratis 24/48h</option>
              <option value="guarantee">🛡️ Garantía Total 30 Días</option>
              <option value="none">Sin sticker</option>
            </select>
          </div>
          <div style="flex:1; min-width:180px;">
            <label style="font-size:11.5px; font-weight:700; color:var(--muted); margin-bottom:4px; display:block;">🎬 Set de Estudio 9:16 (INT-056 AI Cutout)</label>
            <select id="qc-studio-style" style="width:100%; padding:6px 10px; font-size:12px; border-radius:6px;" onchange="QC_STATE.studioStyle=this.value">
              <option value="luxury_dark" selected>🌌 Luxury Dark Pedestal</option>
              <option value="pastel_clean">🤍 Clean Minimalist Studio</option>
              <option value="neon_cyber">⚡ Neon Cyber Light</option>
            </select>
          </div>
        </div>

        <div style="margin-top:14px; padding:12px; border-radius:10px; background:rgba(99,102,241,0.06); border:1px dashed rgba(99,102,241,0.35);">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:20px;">🎭</span>
              <div>
                <strong style="font-size:13px; color:#fff;">Hooks Multi-Ángulo (Arcads / CreateUGC)</strong>
                <p style="font-size:11px; color:var(--muted); margin:0;">Genera 5 variantes de ganchos psicológicos con predicción de retención (Stop-Rate).</p>
              </div>
            </div>
            <button type="button" class="btn" style="padding:6px 14px; font-size:11.5px; background:linear-gradient(135deg,#6366f1,#8b5cf6); color:#fff; font-weight:700; border-radius:8px; border:none; cursor:pointer;" onclick="generateQCHooks()">
              ⚡ Generar Hooks A/B
            </button>
          </div>
          <div id="qc-hooks-container" style="margin-top:12px; display:none;"></div>
        </div>
      </div>`;
  } else if (m === 'url') {
    inputField = `
      <div class="field" style="margin-bottom:14px;">
        <label style="font-size:13px; font-weight:700; margin-bottom:6px; display:block;">🔗 URL de TikTok o YouTube para recrear</label>
        <input type="text" id="qc-input-text" placeholder="https://www.tiktok.com/@usuario/video/..." value="${esc(QC_STATE.url)}" style="width:100%; border-radius:10px; padding:12px; font-size:13.5px;">
        <small style="color:var(--muted); display:block; margin-top:5px;">Analizamos la estructura y creamos una versión 100% original.</small>
      </div>`;
  } else if (m === 'audio') {
    inputField = `
      <div class="field" style="margin-bottom:14px;">
        <label style="font-size:13px; font-weight:700; margin-bottom:6px; display:block;">🎙️ Selecciona tu archivo de audio (MP3/WAV/M4A)</label>
        <input type="file" id="qc-input-file" accept="audio/*" style="width:100%; padding:10px; border-radius:10px; background:rgba(255,255,255,0.03); border:1px dashed var(--border);">
        <small style="color:var(--muted); display:block; margin-top:5px;">Sincronizaremos los subtítulos dinámicos y escenas con tu propia voz.</small>
      </div>`;
  }

  const stylesOptions = (S.styles || []).map(s => `
    <option value="${s.id}" ${QC_STATE.style === s.id ? 'selected' : ''}>${s.emoji || '🎨'} ${esc(s.name)}</option>
  `).join('');

  $('#overlay-root').innerHTML = `
    <div class="overlay" onclick="if(event.target===this)closeOverlay()">
      <div class="qc-box card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size:22px;">⚡</span>
            <h3 style="margin:0; font-size:18px; font-weight:800;">Crear Video en 1-Clic</h3>
            <span class="badge" style="background:rgba(16,185,129,0.15); color:var(--accent); font-weight:700;">$0.00 Ilimitado</span>
          </div>
          <button class="modal-x" onclick="closeOverlay()" style="background:transparent; border:none; color:var(--muted); font-size:20px; cursor:pointer;">✕</button>
        </div>

        <div class="qc-tabs">${tabButtons}</div>

        ${inputField}

        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-bottom:16px; background:rgba(255,255,255,0.02); padding:14px; border-radius:12px; border:1px solid var(--border);">
          <div class="field" style="margin:0;">
            <label style="font-size:11.5px; font-weight:700; color:var(--muted); margin-bottom:4px; display:block;">Formato</label>
            <div style="display:flex; gap:6px;">
              <button type="button" class="btn small ${QC_STATE.format === 'short' ? 'primary' : 'ghost'}" onclick="QC_STATE.format='short';renderQuickCreateModal()" style="flex:1; padding:6px 8px; font-size:11px;">📱 9:16 Short</button>
              <button type="button" class="btn small ${QC_STATE.format === 'long' ? 'primary' : 'ghost'}" onclick="QC_STATE.format='long';renderQuickCreateModal()" style="flex:1; padding:6px 8px; font-size:11px;">🖥️ 16:9 Largo</button>
            </div>
          </div>

          <div class="field" style="margin:0;">
            <label style="font-size:11.5px; font-weight:700; color:var(--muted); margin-bottom:4px; display:block;">Ritmo de cortes</label>
            <div style="display:flex; gap:4px;">
              <button type="button" class="btn small ${QC_STATE.pacing === 'fast' ? 'primary' : 'ghost'}" onclick="QC_STATE.pacing='fast';renderQuickCreateModal()" style="flex:1; padding:6px 4px; font-size:10.5px;" title="Cortes dinámicos cada ~2.5s">⚡ Rápido</button>
              <button type="button" class="btn small ${(QC_STATE.pacing === 'normal' || !QC_STATE.pacing) ? 'primary' : 'ghost'}" onclick="QC_STATE.pacing='normal';renderQuickCreateModal()" style="flex:1; padding:6px 4px; font-size:10.5px;" title="Cortes fluidos cada ~4.0s">⏱️ Normal</button>
              <button type="button" class="btn small ${QC_STATE.pacing === 'slow' ? 'primary' : 'ghost'}" onclick="QC_STATE.pacing='slow';renderQuickCreateModal()" style="flex:1; padding:6px 4px; font-size:10.5px;" title="Cortes pausados cada ~6.0s">🧘 Pausado</button>
            </div>
          </div>

          <div class="field" style="margin:0;">
            <label style="font-size:11.5px; font-weight:700; color:var(--muted); margin-bottom:4px; display:block;">Estilo visual</label>
            <select style="width:100%; padding:6px 8px; font-size:12px; border-radius:6px;" onchange="QC_STATE.style=this.value">
              ${stylesOptions}
            </select>
          </div>

          <div class="field" style="margin:0;">
            <label style="font-size:11.5px; font-weight:700; color:var(--muted); margin-bottom:4px; display:block;">Subtítulos</label>
            <select style="width:100%; padding:6px 8px; font-size:12px; border-radius:6px;" onchange="QC_STATE.subtitles=this.value">
              <option value="shorts" ${QC_STATE.subtitles === 'shorts' ? 'selected' : ''}>📱 Shorts · Montserrat</option>
              <option value="hormozi" ${QC_STATE.subtitles === 'hormozi' ? 'selected' : ''}>⚡ Hormozi · Amarillo</option>
              <option value="mrbeast" ${QC_STATE.subtitles === 'mrbeast' ? 'selected' : ''}>🔴 MrBeast · Impacto</option>
              <option value="karaoke" ${QC_STATE.subtitles === 'karaoke' ? 'selected' : ''}>🎤 Karaoke ASS · Verde Lima</option>
              <option value="minimal" ${QC_STATE.subtitles === 'minimal' ? 'selected' : ''}>🎬 Cinema · Minimal</option>
              <option value="neon" ${QC_STATE.subtitles === 'neon' ? 'selected' : ''}>🟢 Neon Cyber</option>
            </select>
          </div>

          <!-- INT-058: Presentador Flotante Circular (HeyGen Style) -->
          <div class="field" style="margin:0;">
            <label style="font-size:11.5px; font-weight:700; color:var(--muted); margin-bottom:4px; display:block;">🔘 Avatar Flotante PiP (HeyGen)</label>
            <div style="display:flex; gap:6px;">
              <select style="flex:1; padding:6px 8px; font-size:12px; border-radius:6px;" onchange="QC_STATE.avatar=this.value">
                <option value="">— Sin avatar —</option>
                ${(S.avatars || []).map(a => `<option value="${a.id}" ${QC_STATE.avatar === a.id ? 'selected' : ''}>${esc(a.name)}</option>`).join('')}
              </select>
              <select style="width:90px; padding:6px 8px; font-size:11.5px; border-radius:6px;" onchange="QC_STATE.pipBorder=this.value" title="Color del borde circular">
                <option value="cyan" ${(QC_STATE.pipBorder==='cyan'||!QC_STATE.pipBorder)?'selected':''}>🔵 Cyan</option>
                <option value="gold" ${QC_STATE.pipBorder==='gold'?'selected':''}>🟡 Oro</option>
                <option value="emerald" ${QC_STATE.pipBorder==='emerald'?'selected':''}>🟢 Verde</option>
                <option value="purple" ${QC_STATE.pipBorder==='purple'?'selected':''}>🟣 Morado</option>
                <option value="white" ${QC_STATE.pipBorder==='white'?'selected':''}>⚪ Blanco</option>
              </select>
            </div>
          </div>
        </div>

        <div style="display:flex; gap:10px; align-items:center;">
          <button type="button" class="btn primary" id="qc-submit-btn" onclick="executeQuickCreate()" style="flex:1; padding:12px 18px; font-size:14px; font-weight:800; border-radius:10px; background:linear-gradient(135deg, #10b981, #059669); box-shadow:0 4px 14px rgba(16,185,129,0.35);">
            🚀 Fabricar Video Ahora ($0.00)
          </button>
          <button type="button" class="btn ghost" onclick="openWizardFromQC()" style="padding:12px 14px; font-size:12.5px;" title="Abrir asistente paso a paso avanzado">
            Asistente Completo →
          </button>
        </div>
      </div>
    </div>`;

  setTimeout(() => {
    const el = $('#qc-input-text') || $('#qc-input-file');
    if (el) el.focus();
  }, 60);
}

function qcSwitchMode(newMode) {
  const cur = $('#qc-input-text');
  if (cur && cur.value) QC_STATE.text = cur.value;
  QC_STATE.mode = newMode;
  renderQuickCreateModal();
}

function openWizardFromQC() {
  const inp = $('#qc-input-text');
  if (inp && inp.value) {
    if (QC_STATE.mode === 'script') W.script = inp.value;
    else if (QC_STATE.mode === 'idea') W.idea = inp.value;
    else if (QC_STATE.mode === 'url') W.url = inp.value;
  }
  W.mode = QC_STATE.mode;
  W.format = QC_STATE.format;
  W.style = QC_STATE.style;
  W.pacing = QC_STATE.pacing;
  W.subtitles = QC_STATE.subtitles;
  W.step = 4;
  closeOverlay();
  nav('create');
}

async function executeQuickCreate() {
  if (guardDemo()) return;
  const m = QC_STATE.mode;
  const textInput = $('#qc-input-text');
  const val = textInput ? textInput.value.trim() : '';

  if (m === 'script' && !val) {
    toast('Pega tu guion antes de generar', 'err');
    if (textInput) textInput.focus();
    return;
  }
  if (m === 'idea' && !val) {
    toast('Escribe una idea o frase antes de generar', 'err');
    if (textInput) textInput.focus();
    return;
  }
  if (m === 'product' && !val) {
    toast('Pega la URL o nombre del producto antes de generar', 'err');
    if (textInput) textInput.focus();
    return;
  }
  if (m === 'url' && !val) {
    toast('Pega la URL de TikTok o YouTube antes de generar', 'err');
    if (textInput) textInput.focus();
    return;
  }

  let audioPath = null;
  if (m === 'audio') {
    const file = $('#qc-input-file')?.files?.[0];
    if (!file) return toast('Selecciona tu archivo de audio primero', 'err');
    const fd = new FormData();
    fd.append('file', file);
    try {
      toast('Subiendo archivo de voz...');
      const r = await fetch('/api/import/audio', { method: 'POST', body: fd });
      if (!r.ok) throw new Error('Error al subir audio');
      audioPath = (await r.json()).path;
    } catch (err) {
      return toast('Error subiendo audio: ' + err.message, 'err');
    }
  }

  const btn = $('#qc-submit-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Creando proyecto...'; }

  try {
    const body = {
      mode: m,
      style: QC_STATE.style === 'custom-studio' ? 'cinematic' : QC_STATE.style,
      format: QC_STATE.format,
      pacing: QC_STATE.pacing || 'normal',
      subtitle_style: QC_STATE.subtitles || 'shorts',
      platforms: ['youtube', 'tiktok'],
      transitions: true,
      style_reference: true,
      auto_start: true
    };
    if (m === 'idea') body.idea = val;
    if (m === 'script') { body.script = val; body.title = val.slice(0, 48); }
    if (m === 'url') body.url = val;
    if (m === 'product') {
      body.url = val;
      body.angle = QC_STATE.ugcAngle || '3_reasons';
      body.ecommerce_badge = QC_STATE.badgeType || 'rating';
      body.studio_style = QC_STATE.studioStyle || 'luxury_dark';
    }
    if (QC_STATE.avatar) {
      body.avatar_id = QC_STATE.avatar;
      body.circle_avatar_pip = {
        border_color: QC_STATE.pipBorder || 'cyan',
        position: 'bottom_right'
      };
    }

    const p = await api('/projects', { method: 'POST', body });
    if (audioPath) {
      await fetch('/api/projects/' + p.id, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meta_patch: { audio_path: audioPath } })
      });
    }

    closeOverlay();
    toast('¡Fabricación iniciada! 🚀 El motor IA está creando tu video', 'ok');
    startJob(p.id);
  } catch (err) {
    toast('Error: ' + err.message, 'err');
    if (btn) { btn.disabled = false; btn.textContent = '🚀 Fabricar Video Ahora ($0.00)'; }
  }
}

window.openQuickCreateModal = openQuickCreateModal;
window.startDirectCreation = openQuickCreateModal;
window.qcSwitchMode = qcSwitchMode;
window.executeQuickCreate = executeQuickCreate;
window.openWizardFromQC = openWizardFromQC;


/* ── vista: WIZARD CREAR (4 pasos como Labsia) ───────────── */
const W = { step: 1, mode: 'idea', format: 'short', style: 'auto',
            title: '', idea: '', script: '', url: '', custom: '', voice: '', tts: '',
            avatar: '', platforms: ['youtube', 'tiktok'],
            transitions: true, styleReference: true, subtitles: 'shorts', brandProfile: '',
            cookies: '', nicho: '', nichoAdjust: '', pacing: 'normal' };

function renderCreate() {
  const modes = [
    { id: 'nicho', emoji: '🗂️', t: 'Desde Nicho', d: 'Elige un nicho con su plantilla y el video se fabrica SOLO' },
    { id: 'idea',  emoji: '💡', t: 'Desde Idea',  d: 'Una frase → guion viral completo' },
    { id: 'script',emoji: '📜', t: 'Desde Guion', d: 'Ya tienes el guion escrito' },
    { id: 'url',   emoji: '🔗', t: 'Desde URL',   d: 'Recrea un viral de TikTok/YouTube (original)' },
    { id: 'audio', emoji: '🎙️', t: 'Desde Audio', d: 'Tu propia voz como narración' },
  ];
  const isNicho = W.mode === 'nicho';
  const stepName = isNicho ? ['Modo', 'Nicho'] : ['Modo', 'Formato', 'Estilo', 'Detalles'];
  let body = '';

  if (W.step === 1) {
    body = `<div class="modes">${modes.map(m => `
      <div class="card mode-card ${W.mode === m.id ? 'sel' : ''}" style="${W.mode === m.id ? 'border-color:var(--accent2)' : ''}"
           onclick="W.mode='${m.id}';renderCreate()">
        <div class="emoji">${m.emoji}</div><h3>${m.t}</h3><p>${m.d}</p></div>`).join('')}</div>`;
  }

  if (W.step === 2 && isNicho) {
    body = `
      <p style="color:var(--muted);font-size:13px;line-height:1.55;margin-bottom:14px">
        Cada nicho trae su <b>plantilla predeterminada</b> (prompt, estilo, formato y voz).
        Al pulsar <b>🚀 Generar video completo</b> el motor hace TODO solo:
        <b>guion → imágenes → animación → video</b>, y lo guarda en
        <b>biblioteca/tu_nicho/Nombre-del-video.mp4</b> junto a tus otros proyectos del nicho.</p>
      <div class="modes">${(S.niches || []).map(t => `
        <div class="card mode-card ${W.nicho === t.id ? 'sel' : ''}" onclick="W.nicho='${t.id}';renderCreate()">
          <div class="emoji">${t.emoji || '📁'}</div><h3>${esc(t.name)}</h3>
          <p>${esc(t.description || '')}</p>
          <small style="color:var(--accent2);display:block;margin-top:6px">📁 biblioteca/${esc(t.folder || '—')} · ${t.projects || 0} proyectos</small>
        </div>`).join('')}</div>
      ${W.nicho ? `
        <div class="field" style="margin-top:16px"><label>✏️ Ajuste opcional sobre la plantilla del nicho</label>
          <input type="text" value="${esc(W.nichoAdjust)}" oninput="W.nichoAdjust=this.value"
            placeholder="vacío = solo la plantilla con un ángulo aleatorio (anti-repetición)"></div>` : ''}
      <details style="margin-top:14px">
        <summary style="cursor:pointer;font-weight:700;font-size:13px">➕ Nuevo nicho / 🗑️ administrar plantillas</summary>
        <div style="margin-top:12px">${renderNichesAdmin()}</div>
      </details>`;
  } else if (W.step === 2) {
    body = `<div class="format-row">
      <div class="format-card ${W.format === 'short' ? 'sel' : ''}" onclick="W.format='short';renderCreate()">
        <div class="shape s916"></div><b>Short / Vertical</b><small>9:16 · 1080×1920 · YouTube Shorts, TikTok, Reels</small></div>
      <div class="format-card ${W.format === 'long' ? 'sel' : ''}" onclick="W.format='long';renderCreate()">
        <div class="shape s169"></div><b>Largo / Horizontal</b><small>16:9 · 1920×1080 · YouTube clásico</small></div>
    </div>`;
  }

  if (W.step === 3) {
    body = `
      <div style="margin-bottom:16px;">
        <h3 style="font-size:18px; font-weight:700; margin:0 0 4px 0;">🎨 Estilo visual</h3>
        <p style="color:var(--muted); font-size:13px; margin:0;">El estilo define los colores, filtros y energía visual de cada escena de tu video.</p>
      </div>
      <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(210px, 1fr)); gap:12px; max-height:490px; overflow-y:auto; padding-right:6px; margin-bottom:16px;">
        ${S.styles.map(s => `
          <div class="card" onclick="W.style='${s.id}';renderCreate()" style="cursor:pointer; padding:14px; border-radius:12px; border:2px solid ${W.style === s.id ? 'var(--accent)' : 'rgba(255,255,255,0.08)'}; background:${W.style === s.id ? 'rgba(16,185,129,0.09)' : 'rgba(255,255,255,0.02)'}; transition:all 0.15s; position:relative;">
            <div style="width:100%; height:75px; border-radius:8px; background:${s.grad || 'linear-gradient(135deg,#1f2937,#374151)'}; display:flex; align-items:center; justify-content:center; font-size:32px; margin-bottom:10px; box-shadow:inset 0 0 20px rgba(0,0,0,0.5);">
              ${s.emoji || '🎨'}
            </div>
            <b style="display:block; font-size:13.5px; margin-bottom:4px; font-weight:700;">${esc(s.name)}</b>
            <p style="font-size:11.5px; color:var(--muted); line-height:1.4; margin:0;">${esc(s.desc || '')}</p>
            ${W.style === s.id ? `<span style="position:absolute; top:8px; right:8px; background:var(--accent); color:#000; border-radius:50%; width:18px; height:18px; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:bold;">✓</span>` : ''}
          </div>`).join('')}
      </div>
      ${W.style === 'custom-studio' ? `<div class="field" style="margin-top:16px"><label>Describe tu estilo (en inglés, estilo de imagen)</label>
        <input type="text" value="${esc(W.custom)}" oninput="W.custom=this.value" placeholder="dark cinematic photography, moody fog..."></div>` : ''}`;
  }

  if (W.step === 4) {
    const formatPills = `
      <div style="display:flex; gap:10px; margin-bottom:16px; flex-wrap:wrap; align-items:center; background:rgba(255,255,255,0.03); padding:10px 14px; border-radius:10px; border:1px solid var(--border);">
        <span style="font-size:12.5px; font-weight:700; color:var(--muted);">Formato:</span>
        <button type="button" class="btn small ${W.format === 'short' ? 'btn-primary' : 'ghost'}" onclick="W.format='short';renderCreate()" style="padding:4px 10px; font-size:11.5px;">📱 9:16 Short (Recomendado)</button>
        <button type="button" class="btn small ${W.format === 'long' ? 'btn-primary' : 'ghost'}" onclick="W.format='long';renderCreate()" style="padding:4px 10px; font-size:11.5px;">🖥️ 16:9 Largo</button>
        <span style="font-size:12.5px; font-weight:700; color:var(--muted); margin-left:12px;">Estilo visual:</span>
        <select style="padding:4px 8px; font-size:11.5px; max-width:210px; border-radius:6px;" onchange="W.style=this.value">
          ${S.styles.map(s => `<option value="${s.id}" ${W.style === s.id ? 'selected' : ''}>${s.emoji} ${esc(s.name)}</option>`).join('')}
        </select>
      </div>`;

    const f = W.mode === 'idea'
      ? `<div class="field"><label>💡 Tu idea (una frase basta)</label><input type="text" value="${esc(W.idea)}" oninput="W.idea=this.value" placeholder="El imperio romano explicado en 60s"></div>`
      : W.mode === 'script'
      ? `<div class="field"><label>📜 Pega tu guion</label><textarea rows="7" oninput="W.script=this.value" placeholder="Escribe o pega tu guion aquí...">${esc(W.script)}</textarea></div>`
      : W.mode === 'url'
      ? `<div class="field"><label>🔗 URL del video viral (TikTok / YouTube)</label><input type="text" value="${esc(W.url)}" oninput="W.url=this.value" placeholder="https://www.tiktok.com/@user/video/..."><small style="color:var(--muted);display:block;margin-top:6px">Analizamos su estructura y creamos una versión 100% original. No copiamos contenido.</small></div>`
      : `<div class="field"><label>🎙️ Grabación de voz (mp3/wav/m4a)</label><input type="file" id="audio-file" accept="audio/*"></div>`;
    body = formatPills + f + `
      <div class="field" style="margin-bottom:20px; background:rgba(255,255,255,0.02); padding:14px; border-radius:12px; border:1px solid var(--border);">
        <label style="font-size:13px; font-weight:700; margin-bottom:8px; display:block;">⏱️ Ritmo de cortes visuales</label>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:10px;">
          <div class="card" onclick="W.pacing='fast';renderCreate()" style="cursor:pointer; padding:10px 12px; text-align:center; border-radius:10px; border:2px solid ${W.pacing==='fast' ? 'var(--accent)' : 'rgba(255,255,255,0.08)'}; background:${W.pacing==='fast' ? 'rgba(16,185,129,0.1)' : 'transparent'};">
            <b style="display:block; font-size:13px;">⚡ Rápido</b>
            <span style="color:var(--muted); font-size:11px; display:block;">~2.5s / imagen</span>
            <small style="color:var(--accent); font-size:9.5px; font-weight:700;">TikTok / Shorts Viral</small>
          </div>
          <div class="card" onclick="W.pacing='normal';renderCreate()" style="cursor:pointer; padding:10px 12px; text-align:center; border-radius:10px; border:2px solid ${(W.pacing==='normal'||!W.pacing) ? 'var(--accent)' : 'rgba(255,255,255,0.08)'}; background:${(W.pacing==='normal'||!W.pacing) ? 'rgba(16,185,129,0.1)' : 'transparent'};">
            <b style="display:block; font-size:13px;">⏱️ Normal</b>
            <span style="color:var(--muted); font-size:11px; display:block;">~4.0s / imagen</span>
            <small style="color:var(--muted); font-size:9.5px;">Recomendado</small>
          </div>
          <div class="card" onclick="W.pacing='slow';renderCreate()" style="cursor:pointer; padding:10px 12px; text-align:center; border-radius:10px; border:2px solid ${W.pacing==='slow' ? 'var(--accent)' : 'rgba(255,255,255,0.08)'}; background:${W.pacing==='slow' ? 'rgba(16,185,129,0.1)' : 'transparent'};">
            <b style="display:block; font-size:13px;">🧘 Pausado</b>
            <span style="color:var(--muted); font-size:11px; display:block;">~6.0s / imagen</span>
            <small style="color:var(--muted); font-size:9.5px;">Documental / Historia</small>
          </div>
        </div>
        <div style="margin-top:8px; font-size:11px; color:var(--muted); display:flex; justify-content:space-between;">
          <span>El ritmo controla cuándo cambia el plano visual sin alterar la voz.</span>
          <span style="color:var(--accent); font-weight:700;">$0.00 Ilimitado</span>
        </div>
      </div>
      <div class="row">
        <div class="field"><label>🎭 Avatar (personaje consistente)</label>
          <select onchange="W.avatar=this.value">
            <option value="">— sin avatar —</option>
            ${S.avatars.map(a => `<option value="${a.id}" ${W.avatar === a.id ? 'selected' : ''}>${esc(a.name)}${a.voice ? ' · ' + esc(voiceName(a.voice)) : ''}</option>`).join('')}
          </select>
          ${S.avatars.length ? '' : '<small style="color:var(--muted);display:block;margin-top:4px">Crea personajes en la pestaña 🎭 Avatares</small>'}</div>
        <div class="field"><label>Voz (opcional, la del avatar manda si no eliges)</label>
          <div style="display:flex;gap:6px">
            <select id="wiz-voice-select" onchange="W.voice=this.value" style="flex:1">
              <option value="">edge-tts · Salomé 🇨🇴 (gratis ilimitado)</option>
              <option value="gemini" ${S.health.gemini ? '' : 'disabled'}>Gemini TTS · Fenrir 🎖️ (premium)</option>
            </select>
            <button type="button" class="btn small ghost" onclick="openVoiceGallery({target:'wizard'})" title="Explorar y escuchar voces">🎧 Galería</button>
          </div></div>
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
            <div style="display:flex;gap:6px">
              <select id="wiz-sub-select" onchange="W.subtitles=this.value" style="flex:1">
                <option value="shorts" ${W.subtitles === 'shorts' ? 'selected' : ''}>📱 Shorts · Montserrat dinámico</option>
                <option value="hormozi" ${W.subtitles === 'hormozi' ? 'selected' : ''}>⚡ Hormozi · Amarillo gigante</option>
                <option value="mrbeast" ${W.subtitles === 'mrbeast' ? 'selected' : ''}>🔴 MrBeast · Impacto mayúsculas</option>
                <option value="neon" ${W.subtitles === 'neon' ? 'selected' : ''}>🟢 Neon Cyber · Resplandor</option>
                <option value="tiktok" ${W.subtitles === 'tiktok' ? 'selected' : ''}>💬 TikTok · Blanco clásico</option>
                <option value="boxed" ${W.subtitles === 'boxed' ? 'selected' : ''}>📦 Boxed UGC · Fondo caja</option>
                <option value="minimal" ${W.subtitles === 'minimal' ? 'selected' : ''}>🎬 Cinema · Minimal elegante</option>
                <option value="karaoke" ${W.subtitles === 'karaoke' ? 'selected' : ''}>🎤 Karaoke · Verde lima</option>
              </select>
              <button type="button" class="btn small ghost" onclick="openSubtitleSwitcher({target:'wizard'})" title="Ver catálogo visual de subtítulos">🎨 Presets</button>
            </div></div>
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
    ${renderWizardBrandProfileBar()}
    <div class="steps">${stepName.map((n, i) => `
      <div class="step ${i + 1 === W.step ? 'active' : i + 1 < W.step ? 'done' : ''}">${i + 1 < W.step ? '✓ ' : ''}${i + 1}. ${n}</div>`).join('')}</div>
    <div class="card">${body}</div>
    <div class="wizard-nav">
      <button class="btn ghost" onclick="W.step--;W.step<1?nav('home'):renderCreate()">← Atrás</button>
      <button class="btn primary" id="wiz-next">${W.step === 4 || (W.mode === 'nicho' && W.step === 2) ? '🚀 Generar video completo' : 'Continuar →'}</button>
    </div></div>`;

  $('#wiz-next').onclick = () => {
    if (W.step === 1) { W.step = 2; renderCreate(); return; }
    if (W.step === 2) {
      if (isNicho) { createProject(); return; }   // un clic: plantilla → pipeline
      W.step = 3; renderCreate(); return;
    }
    if (W.step === 3) { W.step = 4; renderCreate(); return; }
    createProject();
  };
}

/* ── admin de plantillas de nicho ────────────────────── */
function renderNichesAdmin() {
  return `
    <div class="row">
      <div class="field"><label>Nombre del nicho</label><input type="text" id="nt-name" placeholder="Finanzas personales"></div>
      <div class="field" style="max-width:110px"><label>Emoji</label><input type="text" id="nt-emoji" value="📁"></div>
    </div>
    <div class="field"><label>Descripción corta</label><input type="text" id="nt-desc" placeholder="Ahorro, deudas e inversión explicados simple"></div>
    <div class="field"><label>Plantilla de prompt (predeterminada del nicho)</label>
      <textarea id="nt-prompt" rows="3" placeholder="Escribe un video corto de finanzas: un hábito o error real de dinero..."></textarea></div>
    <button class="btn small primary" onclick="saveNicheTemplate()">💾 Guardar nicho</button>
    <div class="card" style="margin-top:10px">${(S.niches || []).map(t => `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid rgba(128,128,128,.15)">
        <span>${t.emoji || '📁'} ${esc(t.name)} <small style="color:var(--muted)">· ${t.projects || 0} proyectos</small></span>
        <button class="btn small danger" onclick="delNicheTemplate('${t.id}')">🗑️</button>
      </div>`).join('')}</div>`;
}

async function saveNicheTemplate() {
  if (guardDemo()) return;
  try {
    await api('/niches/templates', { method: 'POST', body: {
      name: $('#nt-name').value, emoji: $('#nt-emoji').value,
      description: $('#nt-desc').value, prompt: $('#nt-prompt').value }});
    S.niches = await api('/niches');
    toast('Nicho guardado ✅', 'ok');
    refreshNichesUI();
  } catch (e) { toast(e.message, 'err'); }
}

async function delNicheTemplate(tid) {
  if (guardDemo()) return;
  try {
    await api('/niches/templates/' + tid, { method: 'DELETE' });
    S.niches = await api('/niches');
    if (W.nicho === tid) W.nicho = '';
    toast('Plantilla eliminada');
    refreshNichesUI();
  } catch (e) { toast(e.message, 'err'); }
}

/* v2.12 · borrar nicho directamente desde su tarjeta en Proyectos.
   Plantilla → DELETE; nicho libre → sus videos pasan a «Sin nicho». */
async function delNichoCard(i) {
  const key = _NICHO_KEYS[i];
  const meta = (_NICHO_META || {})[key];
  if (guardDemo() || !meta) return;
  try {
    if (meta.tplId) {
      if (!confirm(`¿Borrar el nicho «${key}»?\nLa plantilla desaparece de Proyectos (tus videos no se tocan).`)) return;
      await api('/niches/templates/' + meta.tplId, { method: 'DELETE' });
      S.niches = await api('/niches');
      if (W.nicho === meta.tplId) W.nicho = '';
    } else {
      if (!confirm(`«${key}» es un nicho libre (sin plantilla).\nSus ${meta.ids.length} video(s) quedarán «Sin nicho». ¿Continuar?`)) return;
      for (const pid of meta.ids)
        await api('/projects/' + pid, { method: 'PATCH', body: { niche: '' } });
    }
    toast('Nicho eliminado', 'ok');
    if (S.view === 'projects') renderProjects();
  } catch (e) { toast(e.message, 'err'); }
}

async function createProject() {
  if (guardDemo()) return;
  if (W.mode === 'nicho') {
    if (!W.nicho) return toast('Elige un nicho primero', 'err');
    try {
      const p = await api('/projects', { method: 'POST', body: {
        mode: 'nicho', niche_template: W.nicho, idea: W.nichoAdjust || null,
        auto_start: true,
        platforms: W.platforms.length ? W.platforms : ['youtube'],
        transitions: W.transitions, style_reference: W.styleReference }});
      toast('Video en fabricación desde el nicho 🚀', 'ok');
      W.step = 1; W.nichoAdjust = '';
      showProgress(p.job_id, p.id);
    } catch (e) { toast(e.message, 'err'); }
    return;
  }
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
    const body = { mode: W.mode, style: W.style, format: W.format, pacing: W.pacing || 'normal',
                   title: W.title || null, voice: W.voice || null,
                   tts_provider: W.tts || null,
                   avatar_id: W.avatar || null,
                   platforms: W.platforms.length ? W.platforms : ['youtube'],
                   transitions: W.transitions, style_reference: W.styleReference,
                   subtitle_style: W.subtitles,
                   cookies_from_browser: W.cookies || null,
                   brand_profile_id: W.brandProfile || null };
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

/* ── vista: PROYECTOS — ventanas PROYECTOS ▸ NICHO ▸ videos (v2.11.1) ── */
let _PROJ_NICHO = null;   // null = ventana de nichos · key = ventana de videos del nicho
let _NICHO_KEYS = [];     // claves de carpetas en el orden renderizado (índices estables para onclick)
let _NICHO_META = {};     // v2.12: {clave: {tplId, ids[]}} para borrar nichos desde la tarjeta
let _NICHO_TPL_ID = '';   // id de plantilla del nicho abierto (preselección de "＋ Nuevo video")

function openNichoWindow(i) {
  const key = _NICHO_KEYS[i];
  if (key == null) return;
  _PROJ_NICHO = key;
  renderProjects();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function closeNichoWindow() {
  _PROJ_NICHO = null;
  renderProjects();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* v2.11.2 · "＋ Nuevo video" desde la ventana de un nicho →
   asistente Crear en modo nicho con ESTE nicho ya elegido */
function newVideoInNicho() {
  nav('create'); W.mode = 'nicho'; W.step = 2;
  W.nicho = _NICHO_TPL_ID || '';
  renderCreate();
}

/* v2.11.3 · modal de nichos: compacto y con cierre (✕, clic fuera, Esc) */
function openNichesAdmin() {
  $('#overlay-root').innerHTML = `<div class="overlay nicho-overlay" onclick="if(event.target===this)closeOverlay()"><div class="box card nicho-box">
    <div class="nicho-modal-head">
      <h3>🗂️ Nuevo nicho</h3>
      <button class="modal-x" onclick="closeOverlay()" title="Cerrar">✕</button>
    </div>
    ${renderNichesAdmin()}
  </div></div>`;
  document.addEventListener('keydown', nichoEscClose);
}

function nichoEscClose(e) { if (e.key === 'Escape') closeOverlay(); }

function closeOverlay() {
  $('#overlay-root').innerHTML = '';
  document.removeEventListener('keydown', nichoEscClose);
}

/* refresca lo que esté visible tras guardar/borrar un nicho */
function refreshNichesUI() {
  if (document.getElementById('nt-name')) openNichesAdmin(); // modal abierto → repíntalo
  if (S.view === 'projects') renderProjects();
  else if (S.view === 'create') renderCreate();
}

function renderProjects() {
  const lib = S.library || [];
  const cats = S.niches || [];

  // agrupar por nicho (label de plantilla o texto libre); sin nicho → grupo propio
  const grupos = new Map();
  for (const p of S.projects) {
    const k = (p.niche || '').trim() || '__sin_nicho__';
    if (!grupos.has(k)) grupos.set(k, []);
    grupos.get(k).push(p);
  }

  // carpetas: catálogo de nichos SIEMPRE visible + nichos libres + «Sin nicho» al final
  const carpetas = [];
  for (const t of cats)
    carpetas.push({ key: t.name || t.id, emoji: t.emoji || '📁', name: t.name || t.id,
                    proys: grupos.get(t.name || t.id) || [] });
  for (const [k, proys] of grupos) {
    if (k === '__sin_nicho__' || carpetas.some(c => c.key === k)) continue;
    carpetas.push({ key: k, emoji: '📁', name: k, proys });
  }
  carpetas.sort((a, b) => a.name.localeCompare(b.name, 'es', { sensitivity: 'base' })); // nicho a → z
  if (grupos.has('__sin_nicho__'))
    carpetas.push({ key: '__sin_nicho__', emoji: '🗃️', name: 'Sin nicho',
                    proys: grupos.get('__sin_nicho__') });
  _NICHO_KEYS = carpetas.map(c => c.key);

  const fmtDate = s => { try {
    return new Date(s).toLocaleDateString('es', { day: '2-digit', month: 'short' });
  } catch (e) { return ''; } };
  const stLabel = p => p.status === 'ready' ? 'Listo' : p.status === 'published' ? 'Publicado'
    : p.status === 'failed' ? 'Error' : p.status === 'draft' ? 'Borrador'
    : (p.step_label || p.status || '…');
  const stCls = p => p.status === 'ready' ? 'ok' : p.status === 'published' ? 'gold'
    : p.status === 'failed' ? 'err' : 'work';

  const head = btn => `
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <h2 class="sec" style="margin:0">🗂️ Proyectos</h2>
      ${btn}
    </div>`;

  /* ── ventana 2 · videos del nicho, ordenados por nombre, en tarjetas ── */
  if (_PROJ_NICHO) {
    const c = carpetas.find(x => x.key === _PROJ_NICHO);
    if (!c) { _PROJ_NICHO = null; return renderProjects(); }
    const vids = [...c.proys].sort((a, b) =>
      String(a.title || '').localeCompare(String(b.title || ''), 'es', { sensitivity: 'base' }));
    // "＋ Nuevo video" dentro del nicho → asistente Crear con este nicho preseleccionado
    const tpl = (cats.find(t => (t.name || t.id) === c.key));
    _NICHO_TPL_ID = tpl ? tpl.id : '';
    const cards = vids.map(p => `
      <div class="vid-card win" onclick="openProject('${p.id}')" title="${esc(p.title)}">
        <div class="vc-cover">
          <span class="vc-ph">🎬</span>
          ${p.cover_url ? `<img src="${p.cover_url}" alt="" loading="lazy" onerror="this.remove()">` : ''}
          <span class="vc-fmt">${p.format === 'short' ? '9:16' : '16:9'}</span>
          <span class="vc-st ${stCls(p)}">${esc(stLabel(p))}</span>
        </div>
        <div class="vc-body">
          <div class="vc-name">${esc(p.title)}</div>
          <div class="vc-chips"><span>🎬 ${p.scenes_count ?? 0} escena${p.scenes_count === 1 ? '' : 's'}</span>${p.updated_at ? `<span>·</span><span>${fmtDate(p.updated_at)}</span>` : ''}</div>
          <div class="vc-actions">
            <button class="btn small primary" onclick="event.stopPropagation();openProject('${p.id}')">▶ Abrir</button>
            <button class="btn small ghost vc-del" onclick="event.stopPropagation();delProject('${p.id}')" title="Borrar video">🗑️</button>
          </div>
        </div>
      </div>`).join('');
    $('#view').innerHTML = `
      ${head('<button class="btn primary small" onclick="newVideoInNicho()">＋ Nuevo video</button>')}
      <div class="crumb"><a href="#" onclick="closeNichoWindow();return false">PROYECTOS</a> <b>▸</b> NICHO <b>▸</b> <span class="crumb-here">${esc(c.name)}</span></div>
      <div class="win">
        <div class="nicho-window-head">
          <button class="btn ghost small" onclick="closeNichoWindow()">← Todos los nichos</button>
          <span class="nicho-win-title">${c.emoji} ${esc(c.name)}</span>
          <span class="f-count">${c.proys.length} video${c.proys.length === 1 ? '' : 's'}</span>
        </div>
        ${vids.length ? `<div class="vid-grid">${cards}</div>`
          : `<div class="card empty"><div class="big">${c.emoji}</div>Carpeta vacía — crea un video de este nicho desde <b>✨ Crear</b>.</div>`}
      </div>`;
    return;
  }

  /* ── ventana 1 · nichos ordenados A→Z, con borrado directo ── */
  // metadatos por tarjeta para el borrado (plantilla o nicho libre)
  _NICHO_META = {};
  carpetas.forEach((c, i) => {
    const t = cats.find(t => (t.name || t.id) === c.key);
    _NICHO_META[c.key] = { i, tplId: t ? t.id : '', ids: c.proys.map(p => p.id) };
  });
  const nichoCards = carpetas.map((c, i) => `
    <div class="nicho-card win" onclick="openNichoWindow(${i})" title="Abrir ${esc(c.name)}">
      <span class="nc-emoji">${c.emoji}</span>
      <span class="nc-info">
        <span class="nc-name">${esc(c.name)}</span>
        <span class="nc-sub">NICHO \\ ${esc(c.name)}</span>
      </span>
      <span class="nc-right">
        <span class="f-count">${c.proys.length} video${c.proys.length === 1 ? '' : 's'}</span>
        ${c.key !== '__sin_nicho__' ? `<button class="nc-del" onclick="event.stopPropagation();delNichoCard(${i})" title="Borrar nicho">🗑️</button>` : ''}
        <span class="nc-chev">▶</span>
      </span>
    </div>`).join('');

  $('#view').innerHTML = `
    ${head('<button class="btn primary small" onclick="openNichesAdmin()">＋ Nuevo nicho</button>')}
    <div class="crumb">PROYECTOS <b>▸</b> NICHO</div>
    <div class="nicho-grid">${nichoCards || `<div class="card empty"><div class="big">🎬</div>Aún no hay nichos ni proyectos. Crea tu primer nicho con el botón <b>＋ Nuevo nicho</b>.</div>`}</div>
    ${lib.length ? `<h2 class="sec">📚 Biblioteca en disco <span class="hint">PROYECTOS\\NICHO\\nicho\\video.mp4</span></h2>
      ${lib.map(g => `
        <div class="card" style="margin-bottom:12px">
          <b>📁 ${esc(g.niche)}</b> <small style="color:var(--muted)">· ${g.files.length} video(s)</small>
          <div style="margin-top:8px">${g.files.map(f => `
            <div class="idea-item"><span>🎬 ${esc(f.name.replace(/\.mp4$/, ''))}</span>
            <small style="color:var(--muted)">${(f.size / 1e6).toFixed(1)} MB</small></div>`).join('')}
          </div>
        </div>`).join('')}` : ''}`;
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
          <button class="btn ghost" onclick="openSubtitleSwitcher({target:'project', project_id: '${p.id}'})" title="Cambiar preset visual de subtítulos">🎨 Subtítulos: <b style="margin-left:4px">${esc(((p.meta||{}).subtitle_style || 'shorts').toUpperCase())}</b></button>
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
    <div class="card hook-ab-container" style="margin-top:16px;border:1px solid rgba(255,255,255,0.12);background:var(--bg2,#18181b)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px">
        <div>
          <b style="font-size:15px;display:flex;align-items:center;gap:6px">🎯 Ganchos Virales A/B <span style="font-size:11px;font-weight:400;color:var(--muted);background:rgba(255,255,255,0.06);padding:2px 8px;border-radius:10px">Primeros 3 segundos</span></b>
          <p style="font-size:12px;color:var(--muted);margin-top:2px">Elige qué gancho psicológico abre tu video en la Escena 1 para retener a la audiencia.</p>
        </div>
        <button class="btn small" onclick="regenProjectHooks('${p.id}')" title="Generar 3 variantes nuevas con IA">⚡ Probar otros 3 Hooks</button>
      </div>
      ${renderHookCards(p)}
    </div>
    <h2 class="sec">🎬 Escenas <span class="hint">arrastra ⟺ para reordenar · clic en la imagen para regenerar</span></h2>
    <div class="scene-list" id="scene-list">${scenes.map(sc => sceneCard(sc)).join('') || '<div class="empty">Sin escenas todavía — genera el video primero</div>'}</div>`;

  initDrag();
}

function getStyleName(id) { return S.styles.find(s => s.id === id)?.name || id; }

function sceneCard(sc) {
  const img = sc.image_path ? `/api/scenes/${sc.id}/image?project_id=${S.project.id}&v=${sc.idx}` : '';
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
        <button class="btn small ghost" onclick="regenFlowScene('${sc.id}')" title="Regenerar solo esta toma quirúrgicamente con Google Flow">🔄 Toma Flow</button>
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

async function regenFlowScene(sid) {
  toast('Regenerando toma quirúrgica con Google Flow… 🎬');
  try {
    const res = await api(`/scenes/${sid}/regenerate-flow`, { method: 'POST', body: { project_id: S.project.id } });
    await openProject(S.project.id);
    toast(`Toma regenerada exitosamente (${res.method || 'Flow'}) 🎬`, 'ok');
  } catch (e) {
    toast('Error al regenerar toma: ' + e.message, 'err');
  }
}

function playAudio(sid, btn) {
  if (btn._a) { btn._a.pause(); btn._a = null; btn.textContent = '🔊 Escuchar'; return; }
  const a = new Audio(`/api/scenes/${sid}/audio?project_id=${S.project.id}`);
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
          return `<div class="idea-item" style="cursor:pointer" onclick="W.mode='idea';W.idea=${js};nav('create')">
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
const AV_FORM = { editing: null, fields: {} };

/* Opciones PRO — espejo de backend/services/avatar_schema.py.
   Se refresca en vivo desde /api/avatars/schema; esto es el fallback. */
const AV_OPTS_FALLBACK = {
  genero: ['Femenino', 'Masculino', 'Andrógino'],
  edad: ['18-24', '25-34', '35-44', '45-54', '55+'],
  piel: ['Clara', 'Media', 'Morena', 'Oscura'],
  ojos_color: ['Azules', 'Verdes', 'Marrones', 'Negros', 'Grises', 'Avellana'],
  ojos_forma: ['Almendrados', 'Redondos', 'Rasgados', 'Caídos'],
  rostro: ['Ovalado', 'Redondo', 'Cuadrado', 'Corazón', 'Alargado'],
  cabello_color: ['Rubio', 'Castaño', 'Negro', 'Pelirrojo', 'Gris plateado', 'Degradado', 'Azul eléctrico', 'Rosa pastel'],
  cabello_largo: ['Corto', 'Mediano', 'Largo', 'Extra largo'],
  cabello_textura: ['Liso', 'Ondulado', 'Rizado', 'Afro'],
  mechas: ['Balayage', 'Mechas claras', 'Mechas de color', 'Rayos de sol'],
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
  rostro: 'Forma del rostro',
  cabello_color: 'Color de cabello', cabello_largo: 'Largo de cabello',
  cabello_textura: 'Textura de cabello', mechas: 'Mechas / reflejos',
  cuerpo: 'Tipo de cuerpo',
  ropa: 'Estilo de ropa', maquillaje: 'Estilo de maquillaje',
  arquetipo: 'Arquetipo', personalidad: 'Personalidad predominante',
  acento: 'Acento al hablar', jerga: 'Tipo de jerga regional',
};
const AV_FIELDS = Object.keys(AV_OPTS_FALLBACK);   // 17 desplegables
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
  if (ap.rostro) chips.push('rostro ' + esc(ap.rostro.toLowerCase()));
  if (ap.ojos_color) chips.push('ojos ' + esc(ap.ojos_color.toLowerCase()));
  const hair = [ap.cabello_largo, ap.cabello_textura, ap.cabello_color, ap.mechas].filter(Boolean).join(' ').toLowerCase();
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
        + grid2([[AV_LABELS.rostro, avSelect('rostro')],
        [AV_LABELS.cabello_color, avSelect('cabello_color')],
        [AV_LABELS.cabello_largo, avSelect('cabello_largo')]])
        + grid2([[AV_LABELS.cabello_textura, avSelect('cabello_textura')],
        [AV_LABELS.mechas, avSelect('mechas')]]))}
      ${sec('🧍 Cuerpo y estilo', grid2([[AV_LABELS.genero, avSelect('genero')],
        [AV_LABELS.edad, avSelect('edad')], [AV_LABELS.cuerpo, avSelect('cuerpo')]])
        + grid2([[AV_LABELS.ropa, avSelect('ropa')], [AV_LABELS.maquillaje, avSelect('maquillaje')],
        ['Accesorios distintivos', avFree('accesorios', 'Ej: aretes dorados, gafas de aviador')]])
        + grid2([['Referencia de influencer', avFree('referencia', 'Ej: Kylie Jenner, Chiara Ferragni')],
        ['Otros detalles (texto libre)', avFree('extras', 'Ej: cicatriz en la ceja, tatuaje de brújula')]]))}
      ${sec('🎙️ Voz y habla', grid2([[AV_LABELS.acento, avSelect('acento')],
        [AV_LABELS.jerga, avSelect('jerga')],
        ['Voz (edge-tts)', `<div style="display:flex;gap:6px"><select id="av-voice-select" onchange="AV_FORM.fields.voice=this.value" style="flex:1">
            <option value="">— sin voz fija —</option>
            ${edgeVoices.map(v => `<option value="${v.id}" ${f.voice === v.id ? 'selected' : ''}>${esc(v.name)}</option>`).join('')}
          </select><button type="button" class="btn small ghost" onclick="openVoiceGallery({target:'avatar'})" title="Escuchar y probar voces">🎧 Galería</button></div>`]])
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
  try { S.niches = await api('/niches'); } catch { S.niches = []; }
  try { S.library = await api('/library'); } catch { S.library = []; }
  try { const cb = await api('/cerebros'); S.cerebros = cb.cerebros || []; S.cerebroActivo = cb.activo; } catch { /* sin clave NVIDIA */ }
  refreshSidebar();
}

(async function boot() {
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
})();

/* ══════════════════════════════════════════════════════════════════
   INT-022 · MCP CONNECTION MANAGER — panel ↔ GoogleFlowMCP / NotebookLM
   Badges: gris=desconectado · amarillo=conectando · verde=conectado y
   autenticado · rojo=error de sesión/técnico. Acciones: conectar/
   desconectar por servicio, Test Pipeline (dry-run §mandato) y registro
   dinámico del notebookId (payload → localStorage → .env fallback).
   ══════════════════════════════════════════════════════════════════ */
const NID_KEY = 'yta-nblm-nid';

function mcpBadgeHTML(state) {
  const map = {
    disconnected:  ['DESCONECTADO', 'mcp-b-gray'],
    connecting:    ['CONECTANDO…', 'mcp-b-yellow'],
    connected:     ['CONECTADO · AUTENTICADO', 'mcp-b-green'],
    auth_required: ['ERROR DE SESIÓN GOOGLE', 'mcp-b-red'],
    error:         ['ERROR TÉCNICO', 'mcp-b-red'],
  };
  const [txt, cls] = map[state] || map.disconnected;
  return `<span class="mcp-badge ${cls}">${txt}</span>`;
}

function mcpSvcHTML(svc, label, hint) {
  const isNblm = svc === 'notebooklm';
  // INT-025 · dropdown dinámico en lugar del input crudo: se autorellena al
  // conectar notebooklm (mcpListNotebooks silent) o con «🔄 Listar».
  const nidBlock = isNblm ? `<div class="mcp-row">
      <label for="nblm-nid-sel">Notebook activo</label>
      <select id="nblm-nid-sel" onchange="mcpPickNotebook(this.value)">
        <option value="">— conecta NotebookLM para listar los tuyos —</option>
        <option value="__manual__">✍️ Pegar ID manual…</option>
      </select>
      <input id="nblm-nid" type="text" placeholder="ej. 9a1b2c3d… (vacío = auto-descubrir en [0/3])"
             value="${esc(localStorage.getItem(NID_KEY) || '')}" oninput="mcpSaveId()"
             style="display:none; margin-top:6px">
    </div>
    <div class="mcp-row btns">
      <button class="btn ghost" id="nblm-list-btn" onclick="mcpListNotebooks()">🔄 Listar / refrescar notebooks</button>
    </div>` : '';
  return `<div class="mcp-svc">
    <div class="mcp-svc-head">
      <h3>${label}</h3>
      <span id="mcp-${svc}-badge">${mcpBadgeHTML('disconnected')}</span>
    </div>
    <p class="hintline">${hint}</p>
    ${nidBlock}
    <div class="mcp-row btns">
      <button class="btn" id="mcp-${svc}-connect" onclick="mcpConnect('${svc}')">🔌 Conectar</button>
      <button class="btn ghost" id="mcp-${svc}-disc" onclick="mcpDisconnect('${svc}')">⏏️ Desconectar</button>
      <button class="btn ghost" onclick="mcpTest('${svc}')">🧪 Probar</button>
    </div>
    <div id="mcp-${svc}-zone"></div>
  </div>`;
}

function renderMCP() {
  $('#view').innerHTML = `
  <div class="card">
    <h2 class="sec">🔌 MCP Connection Manager <span class="hint">servidores MCP stdio gestionados por el backend</span></h2>
    ${mcpGsessHTML()}
    ${mcpSvcHTML('google-flow', '🎬 Google Flow MCP',
      'Servidor tools/GoogleFlowMCP (Node). Con el login unificado se engancha POR CDP al Chrome del perfil ' +
      'compartido (<code>GOOGLE_PROFILE_GLOBAL</code>, puerto <code>FLOW_CDP_PORT</code>) y hereda la sesión — ' +
      'sin login separado. Sin el login global, usa su Chrome dedicado de siempre. Requiere ' +
      '<code>FLOW_MCP_ENABLED=1</code> en backend/.env.')}
    ${mcpSvcHTML('notebooklm', '📚 NotebookLM MCP',
      'Servidor <code>notebooklm-mcp</code> (uv tool install "notebooklm-py[browser]"). Autenticación: ' +
      '«🔑 Login Google» + «📥 Capturar sesión» (arriba) escribe el <code>storage_state.json</code> desde el ' +
      'MISMO login — o <code>notebooklm login</code> clásico. El notebook se elige del DROPDOWN (se rellena ' +
      'solo al conectar); si lo dejas vacío, el pre-flight [0/3] intenta auto-descubrirlo y, si no puede, ' +
      'aborta con <code>PRE_FLIGHT_MISSING_NOTEBOOK_ID</code>.')}
    <div class="mcp-svc" id="pipe-card">
      <div class="mcp-svc-head">
        <h3>🚀 Pipeline completo (NotebookLM → Agente → Flow)</h3>
        <span id="pipe-stage-badge"></span>
      </div>
      <p class="hintline">INT-023/024 · [1/3] lee el contexto del notebook activo → [2/3] genera el blueprint con el motor de guion de siempre (sin tocarlo) → [3/3] despacha cada escena a Google Flow con el MISMO personaje de referencia → [4/4] opcional: 🎞️ harvest + manifest + ensambla el MP4 final con FFmpeg (duration-sync, música ducked -20dB, captions .srt). Pre-flight: si un MCP no está autenticado, aborta sin gastar tokens.</p>
      <div class="mcp-row">
        <label for="pipe-idea">Idea del video</label>
        <input id="pipe-idea" type="text" maxlength="500"
               placeholder="ej. el tema del notebook activo (la bíblia de investigación llega de NotebookLM)">
      </div>
      <div class="mcp-row">
        <label for="pipe-fmt">Formato</label>
        <select id="pipe-fmt">
          <option value="short">short (9:16)</option>
          <option value="long">long (16:9)</option>
        </select>
      </div>
      <div class="mcp-row btns">
        <button class="btn" id="pipe-run-btn" onclick="pipeRun()">🚀 Run Full Pipeline (NotebookLM → Agent → Flow)</button>
        <button class="btn ghost" id="pipe-retry-btn" onclick="pipeRetry()" style="display:none">🔁 Reintentar escenas fallidas</button>
        <button class="btn ghost" id="pipe-render-btn" onclick="pipeRender()" style="display:none">🎞️ Render Final MP4</button>
        <a class="btn ghost" id="pipe-dl-link" style="display:none" href="#" download>⬇️ Descargar MP4</a>
        <button class="btn ghost" onclick="pipeRefresh()">🔄 Actualizar</button>
      </div>
      <div class="mcp-row" id="pipe-force-wrap" style="display:none">
        <label class="hintline"><input type="checkbox" id="pipe-force-ph"> forzar placeholders en escenas fallidas (clip de color con su narración — el testeo nunca se deadlocka)</label>
      </div>
      <div id="pipe-progress"></div>
      <pre class="mcp-log" id="pipe-log" style="display:none"></pre>
    </div>
    <div class="mcp-row btns" style="margin-top:14px">
      <button class="btn" onclick="mcpTest('')">🧪 Test Pipeline (ambos)</button>
      <button class="btn ghost" onclick="mcpRefresh()">🔄 Refrescar estado</button>
    </div>
    <pre class="mcp-log" id="mcp-log">Estado en vivo…</pre>
  </div>`;
  mcpRefresh();
  gsessRefresh(true);   // INT-025 · estado de la sesión unificada sin ruido
}

function mcpSaveId() { const el = $('#nblm-nid'); if (el) localStorage.setItem(NID_KEY, el.value.trim()); }
function mcpNid() { const el = $('#nblm-nid'); return el ? el.value.trim() : (localStorage.getItem(NID_KEY) || ''); }

/* ══ INT-025 · SESIÓN GOOGLE UNIFICADA (google_profile_global) ══════════
   Un login manual humano → ambos MCP:
   · 🔑 Login Google: Chrome REAL con user-data-dir compartido + CDP en
     FLOW_CDP_PORT → GoogleFlowMCP hace connectOverCDP a ESE Chrome.
   · 📥 Capturar sesión: cookies .google.com del mismo Chrome →
     storage_state.json de notebooklm-py (NOTEBOOKLM_HOME/PROFILE).       */
function mcpGsessHTML() {
  return `<div class="mcp-svc" id="gsess-card">
    <div class="mcp-svc-head">
      <h3>🔑 Sesión Google unificada</h3>
      <span id="gsess-badge"><span class="mcp-badge mcp-b-gray">SIN VERIFICAR</span></span>
    </div>
    <p class="hintline">UN solo login manual: se abre tu Chrome con un perfil compartido
      (<code>google_profile_global</code>) en el puerto CDP de Flow — Flow lo reutiliza y NotebookLM recibe
      sus cookies con «📥 Capturar sesión». Nada de scripts .bat, terminales ni logins separados.</p>
    <div class="mcp-row btns" style="display:flex; flex-wrap:wrap; gap:8px; align-items:center;">
      <button class="btn btn-primary" id="gsess-all-btn" onclick="gsessConnectAll()" style="font-weight:700; background:linear-gradient(135deg,#10b981,#059669); color:#fff; border:none; padding:8px 16px; box-shadow:0 2px 8px rgba(16,185,129,0.35);" title="Acción automática: abre Chrome interactivo con tu sesión, conecta Flow y NotebookLM y pone ambos badges en verde">🚀 Iniciar Chrome y Conectar Todo (1 Clic)</button>
      <button class="btn" id="gsess-clean-btn" onclick="gsessCleanLogin()" title="Abre una ventana visible de Chrome para iniciar sesión si tus cookies han expirado">🌐 Abrir Ventana de Chrome</button>
      <button class="btn ghost" id="gsess-capture-btn" onclick="gsessCapture()" title="Captura las cookies de Chrome para NotebookLM">📥 Capturar sesión → NotebookLM</button>
      <button class="btn ghost" onclick="gsessRepairProfile()" title="Sanea el perfil de Chrome (elimina procesos colgados y repara bloqueos)">🔧 Reparar Perfil</button>
      <button class="btn ghost" onclick="gsessRefresh()">🔄 Refrescar estado</button>
    </div>
    <p class="hintline" id="gsess-hint">💡 <b>Recomendado:</b> Pulsa <b>«🚀 Iniciar Chrome y Conectar Todo»</b>. Se abrirá una ventana de Chrome con tu sesión y se vincularán Google Flow y NotebookLM en verde automáticamente.</p>
    <div id="gsess-zone"><p class="hintline">Estado: sin verificar — pulsa «🔄 Refrescar estado» o «🔑 Vincular Sesión Google (Login Único)».</p></div>
  </div>`;
}

async function gsessConnectAll() {
  const btn = $('#gsess-all-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Conectando todo…'; }
  try {
    toast('Iniciando Chrome y conectando Google Flow + NotebookLM…');
    const res = await api('/mcp/connect-all-google', { method: 'POST', body: {} });
    if (res.ok) {
      toast('¡Google Flow y NotebookLM conectados exitosamente! 🚀 Ambos servicios están en VERDE.', 'ok');
    } else {
      let msg = 'Chrome iniciado en puerto 9333. ';
      if (res.flow && res.flow.state === 'connected') msg += 'Flow: ✅ Conectado. ';
      else if (res.flow && res.flow.state === 'auth_required') msg += 'Flow: 🔑 Sesión pendiente en la ventana de Chrome. ';
      if (res.notebooklm && res.notebooklm.state === 'connected') msg += 'NotebookLM: ✅ Conectado. ';
      toast(msg, 'info');
    }
    await gsessRefresh(true);
    await mcpRefresh(true);
    if (res.notebooklm && res.notebooklm.state === 'connected') {
      mcpListNotebooks({ silent: true });
    }
  } catch (e) {
    toast('Error al conectar Google: ' + e.message, 'err');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🚀 Iniciar Chrome y Conectar Todo (1 Clic)'; }
  }
}

async function gsessCleanLogin() {
  const btn = $('#gsess-clean-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Abriendo Chrome…'; }
  try {
    await api('/mcp/launch-clean-login', { method: 'POST', body: {} });
    toast('Se abrió Chrome en modo seguro 🌐. Inicia sesión en Google con tu cuenta, verifica Flow/NotebookLM, CIERRA esa ventana de Chrome y pulsa «2. 🔌 Conectar Chrome (CDP 9333)».');
  } catch (e) {
    toast('Error al abrir Chrome: ' + e.message, 'err');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '1. 🔑 Abrir Login Seguro Google'; }
  }
}

async function gsessLogin() {
  const btn = $('#gsess-login-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Abriendo navegador…'; }
  try {
    const js = await api('/mcp/launch-auth-browser', { method: 'POST', body: {} });
    const pages = (js.pages || []).length;
    toast(js.already_up
      ? 'El Chrome del perfil unificado ya está activo ✅ — inicia sesión en su ventana'
      : 'Navegador abierto con el perfil unificado 🌐 (' + pages + ' pestañas: Flow + NotebookLM) — inicia sesión UNA vez');
    await gsessRefresh();
    await mcpRefresh(true);   // badges MCP al día (verde cuando la sesión valide)
  } catch (e) { toast('Vincular Sesión Google: ' + e.message, 'err'); }
  finally { if (btn) { btn.disabled = false; btn.textContent = '🔑 Vincular Sesión Google (Login Único)'; } }
}

async function gsessCapture() {
  const btn = $('#gsess-capture-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Capturando…'; }
  try {
    const js = await api('/mcp/capture-google-session', { method: 'POST', body: {} });
    toast('Sesión capturada ✅ ' + js.cookies + ' cookies de Google → storage_state de NotebookLM');
    await gsessRefresh();
    // repuebla el dropdown del notebook con la sesión recién capturada
    if (S.mcp && (S.mcp.notebooklm || {}).state === 'connected')
      mcpListNotebooks({ silent: true });
  } catch (e) { toast('Capturar sesión: ' + e.message, 'err'); }
  finally { if (btn) { btn.disabled = false; btn.textContent = '📥 Capturar sesión → NotebookLM'; } }
}

async function gsessRepairProfile() {
  try {
    const res = await api('/mcp/repair-profile', { method: 'POST', body: {} });
    const acts = (res.actions || []).length ? res.actions.join(', ') : 'perfil en estado óptimo';
    toast('Perfil saneado ✅: ' + acts, 'ok');
  } catch (e) { toast('Reparar perfil: ' + e.message, 'err'); }
}

function gsessApply(js) {
  const badge = $('#gsess-badge'), zone = $('#gsess-zone');
  if (!zone) return;
  const up = !!js.chrome_up;
  const st = js.notebooklm_storage || {};
  if (badge) badge.innerHTML = up
    ? '<span class="mcp-badge mcp-b-green">CHROME ACTIVO</span>'
    : '<span class="mcp-badge mcp-b-gray">CHROME APAGADO</span>';
  let h = `<p class="hintline">Chrome CDP (puerto ${js.cdp_port}): ${up ? '✅ arriba — Flow compartirá ESTE Chrome' : '❌ abajo — pulsa «🔑 Login Google»'}` +
    (js.shared_with_flow ? ' · <b>perfil compartido con Flow</b> (mismo puerto CDP)' : ' · ⚠ puerto distinto de FLOW_CDP_PORT') + `</p>`;
  h += `<p class="hintline">storage NotebookLM: ${st.exists
    ? '✅ capturado → <code>' + esc(st.active.split(/[\\\\/]/).pop()) + '</code> (' + (st.size_bytes || 0) + ' bytes)'
    : '❌ sin storage_state — haz login y «📥 Capturar sesión»'}</p>`;
  if (js.profile_dir) h += `<p class="hintline">Perfil global: <code>${esc(js.profile_dir)}</code></p>`;
  zone.innerHTML = h;
}

async function gsessRefresh(silent) {
  try {
    const js = await api('/mcp/login-google');
    gsessApply(js);
    return js;
  } catch (e) { if (!silent) toast('Estado sesión: ' + e.message, 'err'); return null; }
}

/* Dropdown de notebooks (INT-025): puebla SIEMPRE el select visible; el
   input #nblm-nid queda como soporte manual (pipeRun sigue leyéndolo). */
function mcpPopulateNotebooks(nbs) {
  const sel = $('#nblm-nid-sel');
  if (!sel) return;
  const cur = mcpNid();
  const opts = ['<option value="">— elige notebook —</option>']
    .concat((nbs || []).map(n =>
      `<option value="${esc(n.id)}">${esc((n.title || '(sin título)') + ' · ' + n.id.slice(0, 8) + '…')}</option>`))
    .concat(['<option value="__manual__">✍️ Pegar ID manual…</option>']);
  sel.innerHTML = opts.join('');
  const hit = (nbs || []).find(n => n.id === cur);
  if (cur && hit) { sel.value = cur; const ip = $('#nblm-nid'); if (ip) ip.style.display = 'none'; }
  else if (cur) { sel.value = '__manual__'; const ip = $('#nblm-nid'); if (ip) ip.style.display = ''; }
}

async function mcpListNotebooks(opts) {
  const silent = !!(opts && opts.silent);
  const btn = $('#nblm-list-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Listando…'; }
  try {
    const js = await api('/mcp/list-notebooks', { method: 'POST', body: {} });
    const nbs = js.notebooks || [];
    if (!nbs.length) {
      if (!silent) toast('La cuenta no devolvió notebooks (¿lista vacía o sin sesión?)', 'err');
      return;
    }
    mcpPopulateNotebooks(nbs);
    if (!silent) toast(nbs.length + ' notebooks listados — elige uno del dropdown');
  } catch (e) {
    if (!silent) toast('Listar notebooks: ' + e.message, 'err');
  }
  finally { if (btn) { btn.disabled = false; btn.textContent = '🔄 Listar / refrescar notebooks'; } }
}

function mcpPickNotebook(id) {
  const el = $('#nblm-nid'), sel = $('#nblm-nid-sel');
  if (id === '__manual__') {
    if (el) { el.style.display = ''; el.focus(); }
    return;
  }
  if (!id) return;
  if (el) { el.value = id; el.style.display = 'none'; mcpSaveId(); }
  if (sel) sel.value = id;
  toast('Notebook fijado ✅ ' + id.slice(0, 8) + '… — ya puedes lanzar el pipeline');
}

function mcpZoneHTML(st) {
  let h = '';
  if (st.auth_detail) h += `<p class="hintline">🔐 ${esc(st.auth_detail)}</p>`;
  if (st.last_error) h += `<p class="hintline" style="color:var(--err)">⚠ ${esc(st.last_error)}</p>`;
  if (st.server_info && st.server_info.name)
    h += `<p class="hintline">Servidor: <b>${esc(st.server_info.name)}</b> v${esc(st.server_info.version || '?')}` +
         (st.pid ? ` · PID ${st.pid} · ${st.uptime_s || 0}s` : '') + `</p>`;
  if (st.tools && st.tools.length)
    h += `<details class="mcp-tools"><summary>🔧 ${st.tools.length} tools expuestas</summary><ul>` +
         st.tools.map(t => `<li><b>${esc(t.name)}</b>${t.description ? ' — ' + esc(t.description) : ''}</li>`).join('') +
         `</ul></details>`;
  if (st.hint) h += `<p class="hintline" style="color:var(--warn)">ℹ ${esc(st.hint)}</p>`;
  if (st.browser_up !== undefined)
    h += `<p class="hintline">Chrome CDP (${st.cdp_port || ''}): ${st.browser_up ? '✅ arriba' : '❌ no responde — abre el Chrome dedicado'}</p>`;
  if (st.notebook_id_valid !== undefined && st.notebook_id)
    h += `<p class="hintline">notebookId «${esc(st.notebook_id)}»: ${st.notebook_id_valid ? '✅ válido' : '❌ inválido'}</p>`;
  if (st.stderr_tail && st.stderr_tail.length)
    h += `<pre class="mcp-log">${esc(st.stderr_tail.join('\n'))}</pre>`;
  return h || '<p class="hintline">Sin información adicional.</p>';
}

function mcpApplyStatus(services) {
  S.mcp = services || {};
  ['google-flow', 'notebooklm'].forEach(svc => {
    const st = S.mcp[svc] || {};
    const badge = $('#mcp-' + svc + '-badge');
    if (badge) badge.innerHTML = mcpBadgeHTML(st.state || 'disconnected');
    const zone = $('#mcp-' + svc + '-zone');
    if (zone) zone.innerHTML = mcpZoneHTML(st);
    const btnC = $('#mcp-' + svc + '-connect'), btnD = $('#mcp-' + svc + '-disc');
    if (btnC) { btnC.disabled = st.state === 'connecting'; btnC.textContent = st.state === 'connecting' ? '⏳ Conectando…' : '🔌 Conectar'; }
    if (btnD) btnD.disabled = st.state === 'connecting' || st.state === 'disconnected';
  });
  updatePills();
}

async function mcpRefresh(silent) {
  try {
    const js = await api('/mcp/status');
    mcpApplyStatus(js.services || {});
    const log = $('#mcp-log');
    if (log) log.textContent = Object.entries(js.services || {})
      .map(([k, v]) => `[${k}] ${v.state}${v.auth && v.auth !== 'unknown' ? ' · auth=' + v.auth : ''}`).join('\n');
  } catch (e) { if (!silent) toast('MCP status: ' + e.message, 'err'); }
}

async function mcpConnect(svc) {
  const body = { service: svc };
  if (svc === 'notebooklm' && mcpNid()) body.notebook_id = mcpNid();
  const b = $('#mcp-' + svc + '-badge'); if (b) b.innerHTML = mcpBadgeHTML('connecting');
  try {
    const st = await api('/mcp/connect', { method: 'POST', body });
    if (st.state === 'auth_required') toast('Sesión Google no válida — badge rojo con detalle', 'err');
    else toast((svc === 'google-flow' ? 'Google Flow' : 'NotebookLM') + ' conectado ✅');
    // INT-025 · al conectar NotebookLM: auto-listar y rellenar el dropdown
    // de notebooks (nombres amigables, 1 click) sin preguntar nada.
    if (svc === 'notebooklm' && st.state === 'connected')
      mcpListNotebooks({ silent: true });
  } catch (e) { toast('Conexión: ' + e.message, 'err'); }
  mcpRefresh(true);
}

async function mcpDisconnect(svc) {
  try { await api('/mcp/disconnect', { method: 'POST', body: { service: svc } }); toast('Desconectado'); }
  catch (e) { toast('Desconexión: ' + e.message, 'err'); }
  mcpRefresh(true);
}

async function mcpTest(svc) {
  const body = { service: svc };
  if (mcpNid()) body.notebook_id = mcpNid();
  toast('Test Pipeline en marcha…');
  try {
    const js = await api('/mcp/test-pipeline', { method: 'POST', body });
    const log = $('#mcp-log');
    if (log) {
      log.textContent = Object.entries(js).filter(([k]) => k !== 'ok')
        .map(([k, v]) => `[${k}] ${typeof v === 'object' ? JSON.stringify(v, null, 1) : v}`).join('\n');
    }
    toast(js.ok ? 'Test Pipeline OK ✅' : 'Test con problemas — mira el log', js.ok ? '' : 'err');
  } catch (e) { toast('Test Pipeline: ' + e.message, 'err'); }
  mcpRefresh(true);
}

// estado silencioso al arrancar (pills del topbar sin spam de errores)
(async () => { try { await mcpRefresh(true); } catch {} })();

/* ══════════════════════════════════════════════════════════════════
   INT-023 · PIPELINE ORCHESTRATOR — NotebookLM → Agente → Flow
   Progreso en vivo por polling ligero de /api/pipeline/status:
   [1/3] Reading NotebookLM → [2/3] Generating Blueprint →
   [3/3] Dispatching Scenes to Flow (X/Y). Falla una escena →
   retry-scenes SOLO re-despacha las fallidas (Stage 1/2 intactos).
   ══════════════════════════════════════════════════════════════════ */
let pipeTimer = null;
const PIPE_STAGES = {
  queued:          ['EN COLA…', 'mcp-b-yellow'],
  preflight:       ['PRE-FLIGHT…', 'mcp-b-yellow'],
  stage1_context:  ['[1/3] READING NOTEBOOKLM…', 'mcp-b-yellow'],
  stage2_blueprint:['[2/3] GENERATING BLUEPRINT…', 'mcp-b-yellow'],
  stage3_dispatch: ['[3/3] DISPATCHING TO FLOW…', 'mcp-b-yellow'],
  stage4_render:   ['[4/4] ASSEMBLING (FFMPEG)…', 'mcp-b-yellow'],
  done:            ['COMPLETADO', 'mcp-b-green'],
  error:           ['ERROR', 'mcp-b-red'],
};

function pipeActive(run) {
  return !!run && ['queued', 'preflight', 'stage1_context',
                   'stage2_blueprint', 'stage3_dispatch',
                   'stage4_render'].includes(run.stage);
}

function pipeBadgeHTML(run) {
  if (!run) return '<span class="mcp-badge mcp-b-gray">SIN CORRIDAS</span>';
  const [txt, cls] = PIPE_STAGES[run.stage] || PIPE_STAGES.queued;
  return `<span class="mcp-badge ${cls}">${txt}</span>`;
}

function pipeStepsHTML(run) {
  const total = (run.scenes || []).length;
  const done = (run.scenes || []).filter(s => s.status === 'done').length;
  const failed = (run.scenes || []).filter(s => s.status === 'failed').length;
  const processed = done + failed;
  let h = '<div class="pipe-steps">';
  (run.steps || []).forEach(st => {
    const mark = st.state === 'ok' ? '✅' : st.state === 'running' ? '⏳'
               : st.state === 'failed' ? '❌' : '·';
    let label = esc(st.label);
    if (st.stage === 'stage3_dispatch' && total) {
      label = `[3/3] Dispatching Scenes to Flow (${processed}/${total})…`;
    }
    h += `<div class="pipe-step"><span class="st">${mark}</span><span>${label}` +
         (st.detail ? ` <span class="hintline">— ${esc(st.detail)}</span>` : '') +
         `</span></div>`;
  });
  h += '</div>';
  if (total) {
    h += '<div class="pipe-chips">';
    run.scenes.forEach(s => {
      const cls = s.status === 'done' ? 'done' : s.status === 'failed' ? 'failed'
                : s.status === 'dispatched' ? 'dispatched' : '';
      const tip = s.detail ? ` title="${esc(s.detail)}"` : (s.video_file ? ` title="${esc(s.video_file)}"` : '');
      const mark = s.status === 'done' ? '✓' : s.status === 'failed' ? '✗'
                 : s.status === 'dispatched' ? '…' : '·';
      const regenBtn = run.run_id && !pipeActive(run) ? ` <a href="javascript:void(0)" onclick="event.stopPropagation();pipeRetryScene('${run.run_id}','${s.scene_id}')" title="Regenerar solo la toma ${esc(s.scene_id)} con Google Flow" style="text-decoration:none;font-weight:bold;padding:0 3px;opacity:0.85">🔄</a>` : '';
      h += `<span class="pipe-chip ${cls}"${tip}>${mark} ${esc(s.scene_id)} ${esc((s.title || '').slice(0, 24))}${regenBtn}</span>`;
    });
    h += '</div>';
  }
  // INT-024 · Stage 4: estado del ensamblador FFmpeg (run.render del backend)
  const render = run.render || {};
  if (render.status && render.status !== 'idle') {
    if (render.status === 'running') {
      h += `<p class="pipe-detail">🎞️ [4/4] ${esc(render.stage || '…')} — ${render.progress_pct || 0}% ` +
           (render.detail ? `— ${esc(render.detail)}` : '') + `</p>`;
    } else if (render.status === 'done') {
      h += `<p class="pipe-detail">${render.dry_run ? '🧪 Dry-run: plan en <code>render_plan.json</code>' : '✅ Render final listo'} ` +
           (render.output ? `→ <code>${esc(render.output)}</code>` : '') +
           (render.detail ? ` <span class="hintline">(${esc(render.detail)})</span>` : '') + `</p>`;
    } else if (render.status === 'error') {
      h += `<p class="pipe-detail">❌ [${esc(render.error_code || '')}] ${esc(render.error_detail || '')}</p>`;
    }
  }
  if (run.error_detail) {
    h += `<p class="pipe-detail">⚠ [${esc(run.error_code || '')}] ${esc(run.error_detail)}</p>`;
  }
  return h;
}

function pipeApply(run) {
  const badge = $('#pipe-stage-badge');
  if (badge) badge.innerHTML = pipeBadgeHTML(run);
  const zone = $('#pipe-progress');
  if (zone) zone.innerHTML = run ? pipeStepsHTML(run) : '';
  const log = $('#pipe-log');
  if (log) {
    if (run && (run.error_detail || run.context_chars)) {
      log.style.display = '';
      log.textContent = JSON.stringify({
        run_id: run.run_id, stage: run.stage, idea: run.idea,
        notebook_id: run.notebook_id, context_chars: run.context_chars,
        blueprint_title: run.blueprint_title,
        failed_scene_ids: run.failed_scene_ids,
        error: run.error_detail || undefined,
      }, null, 1);
    } else log.style.display = 'none';
  }
  const rbtn = $('#pipe-retry-btn');
  if (rbtn) rbtn.style.display = (run && run.failed_scene_ids && run.failed_scene_ids.length && !pipeActive(run)) ? '' : 'none';
  const rbtn2 = $('#pipe-run-btn');
  if (rbtn2) rbtn2.disabled = pipeActive(run);
  // INT-024 · botón de render final + flag de placeholders + descarga MP4
  const render = (run && run.render) || {};
  const rbtnR = $('#pipe-render-btn');
  const forceWrap = $('#pipe-force-wrap');
  const dl = $('#pipe-dl-link');
  const canRender = !!run && !pipeActive(run) && run.stage === 'done'
    && ((run.done_count || 0) > 0 || (run.failed_scene_ids || []).length > 0);
  if (rbtnR) {
    rbtnR.style.display = canRender ? '' : 'none';
    rbtnR.disabled = render.status === 'running';
  }
  if (forceWrap) forceWrap.style.display = (canRender && (run.failed_scene_ids || []).length) ? '' : 'none';
  if (dl) {
    const ok = render.status === 'done' && render.output && !render.dry_run;
    dl.style.display = ok ? '' : 'none';
    if (ok) dl.href = '/api/pipeline/render/file?run_id=' + encodeURIComponent(run.run_id);
  }
  if (run && !pipeActive(run) && !document.hidden) mcpRefresh(true);
  return pipeActive(run);
}

async function pipeRefresh(silent) {
  try {
    const run = await api('/pipeline/status');
    S.pipeRun = run;
    S.pipeRunId = run.run_id;
    return pipeApply(run);
  } catch (e) {
    if (!silent) toast('Pipeline: ' + e.message, 'err');
    S.pipeRun = null;
    if (typeof pipeApply === 'function') pipeApply(null);
    return false;
  }
}

function pipePollStart() {
  if (pipeTimer) return;
  pipeTimer = setInterval(async () => {
    if (document.hidden) return;
    const active = await pipeRefresh(true);
    if (!active && pipeTimer) { clearInterval(pipeTimer); pipeTimer = null; }
  }, 2000);
}

async function pipeRun() {
  const idea = ($('#pipe-idea') || {}).value || '';
  const nid = mcpNid();  // lectura EXPLÍCITA del «Notebook ID activo» del panel MCP
  const body = { idea: idea.trim(), format: ($('#pipe-fmt') || {}).value || 'short' };
  if (nid) body.notebook_id = nid;
  if (!body.idea) { toast('Escribe la idea del video primero', 'err'); return; }
  if (!nid) toast('notebook_id vacío: [0/3] intentará auto-descubrirlo (list tool); si no hay, aborta con PRE_FLIGHT_MISSING_NOTEBOOK_ID');
  try {
    const js = await api('/pipeline/run', { method: 'POST', body });
    S.pipeRunId = js.run_id;
    toast('Pipeline lanzado 🚀 [1/3] Reading NotebookLM…');
    await pipeRefresh(true);
    pipePollStart();
  } catch (e) { toast('Run Full Pipeline: ' + e.message, 'err'); }
}

async function pipeRetry() {
  const rid = S.pipeRunId || (S.pipeRun || {}).run_id;
  if (!rid) { toast('No hay corrida que reintentar', 'err'); return; }
  try {
    const run = await api('/pipeline/retry-scenes', { method: 'POST', body: { run_id: rid } });
    S.pipeRun = run;
    pipeApply(run);
    pipePollStart();
    toast('Re-despachando solo las escenas fallidas 🔁');
  } catch (e) { toast('Retry escenas: ' + e.message, 'err'); }
}

async function pipeRetryScene(runId, sceneId) {
  if (!runId || !sceneId) return;
  toast(`Re-despachando toma ${sceneId} a Google Flow… 🔄`);
  try {
    const run = await api('/pipeline/retry-scenes', {
      method: 'POST',
      body: { run_id: runId, scene_ids: [sceneId], force: true }
    });
    S.pipeRun = run;
    pipeApply(run);
    pipePollStart();
    toast(`Toma ${sceneId} en regeneración quirúrgica 🎬`, 'ok');
  } catch (e) {
    toast(`Error al regenerar toma ${sceneId}: ` + e.message, 'err');
  }
}

// INT-024 · Stage 4: ensambla el MP4 final con FFmpeg (harvest + manifest + render)
async function pipeRender() {
  const rid = S.pipeRunId || (S.pipeRun || {}).run_id;
  if (!rid) { toast('No hay corrida que renderizar', 'err'); return; }
  const force = (($('#pipe-force-ph') || {}).checked) || false;
  try {
    await api('/pipeline/render', { method: 'POST',
      body: { run_id: rid, force_placeholder_on_failed: force } });
    toast('Stage 4 lanzado 🎞️ [4/4] Assembling (FFmpeg)…');
    await pipeRefresh(true);
    pipePollStart();
  } catch (e) { toast('Render Final MP4: ' + e.message, 'err'); }
}

// reanudar el seguimiento si el backend conserva una corrida activa (recarga de página)
(async () => { const act = await pipeRefresh(true); if (act) pipePollStart(); })();


/* ── 🎯 Generador A/B de Hooks Virales (ClonaKit / Anai Feature) ───────── */
function renderHookCards(p) {
  const meta = p.meta || {};
  let hooks = meta.hook_variants || [];
  const selectedId = meta.selected_hook_id || 'A';
  if (!hooks.length) {
    if (p.hook) {
      hooks = [
        { id: 'A', type: 'Curiosidad', label: 'Gancho Actual', hook: p.hook, visual_cue: 'Toma de impacto inicial', estimated_retention: '94%' },
        { id: 'B', type: 'Contradicción', label: 'Mito Común', hook: 'Todo lo que creías saber sobre este tema es mentira.', visual_cue: 'Gesto de advertencia en primer plano', estimated_retention: '92%' },
        { id: 'C', type: 'Dato Chocante', label: 'Impacto Inmediato', hook: 'Solo el 1% de las personas conoce este dato.', visual_cue: 'Zoom rápido vertiginoso con destello', estimated_retention: '96%' }
      ];
    } else {
      return `<div style="padding:12px;text-align:center;color:var(--muted);font-size:13px">
        No hay variantes A/B generadas todavía.
        <button class="btn small primary" style="margin-left:10px" onclick="regenProjectHooks('${p.id}')">🎯 Generar Hooks A/B Ahora</button>
      </div>`;
    }
  }
  const badgeColors = {
    'Curiosidad': 'background:rgba(168,85,247,0.15);color:#c084fc;border:1px solid rgba(168,85,247,0.3)',
    'Contradicción': 'background:rgba(249,115,22,0.15);color:#fb923c;border:1px solid rgba(249,115,22,0.3)',
    'Dato Chocante': 'background:rgba(239,68,68,0.15);color:#f87171;border:1px solid rgba(239,68,68,0.3)',
  };
  return `<div class="hook-grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px">
    ${hooks.map(h => {
      const isSel = (h.id === selectedId) || (p.hook && p.hook === h.hook);
      const bColor = badgeColors[h.type] || 'background:rgba(59,130,246,0.15);color:#60a5fa;border:1px solid rgba(59,130,246,0.3)';
      const safeHook = esc(h.hook).replace(/'/g, "&#39;");
      return `
        <div class="card hook-card ${isSel ? 'active-hook' : ''}" 
             style="cursor:pointer;position:relative;border:1.5px solid ${isSel ? 'var(--accent2,#10b981)' : 'rgba(255,255,255,0.08)'};background:${isSel ? 'rgba(16,185,129,0.08)' : 'rgba(0,0,0,0.2)'};padding:14px;border-radius:10px;transition:all 0.2s ease"
             onclick="selectProjectHook('${p.id}', '${esc(h.id)}', '${safeHook}')">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span style="font-size:11px;font-weight:700;padding:2px 8px;border-radius:6px;${bColor}">Variante ${esc(h.id)} · ${esc(h.type || h.label || 'Hook')}</span>
            <span style="font-size:11px;color:#10b981;font-weight:700;background:rgba(16,185,129,0.12);padding:2px 6px;border-radius:6px">⚡ ${esc(h.estimated_retention || '94%')}</span>
          </div>
          <div style="font-size:13.5px;font-weight:600;line-height:1.4;margin-bottom:8px;color:var(--text,#fff)">«${esc(h.hook)}»</div>
          <div style="font-size:11.5px;color:var(--muted,#9ca3af);display:flex;align-items:center;gap:4px">
            <span>🎬</span> <em>${esc(h.visual_cue || 'Toma dinámica')}</em>
          </div>
          <div style="margin-top:10px;text-align:right">
            ${isSel ? '<span style="font-size:11px;color:#10b981;font-weight:700">✓ ACTIVO EN ESCENA 1</span>' 
                    : '<span style="font-size:11px;color:var(--muted);text-decoration:underline">Elegir este hook →</span>'}
          </div>
        </div>
      `;
    }).join('')}
  </div>`;
}

async function selectProjectHook(pid, hookId, hookText) {
  try {
    const unescaped = hookText.replace(/&#39;/g, "'");
    const res = await api(`/projects/${pid}/select-hook`, {
      method: 'POST',
      body: { hook_id: hookId, hook_text: unescaped }
    });
    if (S.project && S.project.id === pid) {
      S.project.meta = S.project.meta || {};
      S.project.meta.selected_hook_id = hookId;
      S.project.meta.hook = unescaped;
      S.project.hook = unescaped;
      if (S.project.scenes && S.project.scenes.length) {
        S.project.scenes[0].narration = unescaped;
      }
      renderProject();
    }
    toast(`Variante ${hookId} aplicada a la Escena 1`, 'ok');
  } catch (err) {
    toast(err.message, 'err');
  }
}

async function regenProjectHooks(pid) {
  try {
    const p = S.project;
    toast('Generando 3 ganchos virales A/B…', 'info');
    const res = await api('/pipeline/generate-hooks', {
      method: 'POST',
      body: { topic: p.title || 'video', count: 3 }
    });
    if (res && res.hooks) {
      if (S.project && S.project.id === pid) {
        S.project.meta = S.project.meta || {};
        S.project.meta.hook_variants = res.hooks;
        renderProject();
      }
      toast('3 nuevos ganchos virales listos', 'ok');
    }
  } catch (err) {
    toast(err.message, 'err');
  }
}



/* ══════════════════════════════════════════════════════════════════
   INT-040 · Galería de Voces con Preescucha Interactiva
   ══════════════════════════════════════════════════════════════════ */
let VG_STATE = {
  voices: [],
  filterCountry: 'all',
  filterGender: 'all',
  search: '',
  target: 'global',
  currentAudio: null,
  playingVoiceId: null,
  loadingVoiceId: null,
};

async function openVoiceGallery(opts = {}) {
  VG_STATE.target = opts.target || 'global';
  if (!VG_STATE.voices.length) {
    try {
      const res = await api('/voices');
      VG_STATE.voices = res.voices || [];
      S.allVoices = VG_STATE.voices;
    } catch (e) {
      toast('Error cargando catálogo de voces: ' + e.message, 'err');
      return;
    }
  }

  const countries = ['all', ...new Set(VG_STATE.voices.map(v => v.country))];
  const countryChips = countries.map(c => {
    const label = c === 'all' ? '🌐 Todos' : c;
    return `<span class="vg-chip ${VG_STATE.filterCountry === c ? 'active' : ''}" onclick="vgSetCountry('${c}')">${esc(label)}</span>`;
  }).join('');

  const genders = [
    { id: 'all', label: 'Todos' },
    { id: 'Femenina', label: '👩 Femenina' },
    { id: 'Masculina', label: '👨 Masculina' }
  ];
  const genderChips = genders.map(g => {
    return `<span class="vg-chip ${VG_STATE.filterGender === g.id ? 'active' : ''}" onclick="vgSetGender('${g.id}')">${g.label}</span>`;
  }).join('');

  $('#overlay-root').innerHTML = `
    <div class="overlay voice-gallery-overlay" onclick="if(event.target===this)closeVoiceGallery()">
      <div class="box card">
        <div class="vg-header">
          <div>
            <h3>🎙️ Galería de Voces Neuronales</h3>
            <p>Escucha y prueba cada voz en audio real antes de generar tu video.</p>
          </div>
          <button class="modal-x" onclick="closeVoiceGallery()" title="Cerrar">✕</button>
        </div>
        <div class="vg-search-row">
          <input type="text" class="vg-search-input" id="vg-search"
            value="${esc(VG_STATE.search)}"
            placeholder="🔍 Buscar por nombre, país, tono o estilo..."
            oninput="vgSearch(this.value)">
        </div>
        <div class="vg-filters" id="vg-country-filters">${countryChips}</div>
        <div class="vg-filters" id="vg-gender-filters">${genderChips}</div>
        <div class="vg-grid" id="vg-grid"></div>
      </div>
    </div>`;

  document.addEventListener('keydown', vgEscClose);
  renderVoiceGrid();
}

function vgEscClose(e) {
  if (e.key === 'Escape') closeVoiceGallery();
}

function closeVoiceGallery() {
  if (VG_STATE.currentAudio) {
    VG_STATE.currentAudio.pause();
    VG_STATE.currentAudio = null;
  }
  VG_STATE.playingVoiceId = null;
  VG_STATE.loadingVoiceId = null;
  document.removeEventListener('keydown', vgEscClose);
  closeOverlay();
}

function vgSetCountry(c) {
  VG_STATE.filterCountry = c;
  const chips = document.querySelectorAll('#vg-country-filters .vg-chip');
  chips.forEach(el => el.classList.toggle('active', el.textContent.includes(c === 'all' ? 'Todos' : c)));
  renderVoiceGrid();
}

function vgSetGender(g) {
  VG_STATE.filterGender = g;
  const chips = document.querySelectorAll('#vg-gender-filters .vg-chip');
  chips.forEach(el => el.classList.toggle('active', el.textContent.includes(g === 'all' ? 'Todos' : g)));
  renderVoiceGrid();
}

function vgSearch(val) {
  VG_STATE.search = val.trim().toLowerCase();
  renderVoiceGrid();
}

function renderVoiceGrid() {
  const container = $('#vg-grid');
  if (!container) return;
  const q = VG_STATE.search;
  const c = VG_STATE.filterCountry;
  const g = VG_STATE.filterGender;

  let list = VG_STATE.voices.filter(v => {
    if (c !== 'all' && v.country !== c) return false;
    if (g !== 'all' && v.gender !== g) return false;
    if (q) {
      const match = v.name.toLowerCase().includes(q) ||
        v.country.toLowerCase().includes(q) ||
        v.tone.toLowerCase().includes(q) ||
        v.description.toLowerCase().includes(q) ||
        (v.tags || []).some(t => t.toLowerCase().includes(q));
      if (!match) return false;
    }
    return true;
  });

  if (!list.length) {
    container.innerHTML = `<div class="card empty" style="grid-column:1/-1;text-align:center;padding:24px">No se encontraron voces con los filtros seleccionados</div>`;
    return;
  }

  container.innerHTML = list.map(v => {
    const isPlaying = VG_STATE.playingVoiceId === v.id;
    const isLoading = VG_STATE.loadingVoiceId === v.id;
    return `
      <div class="vg-card ${isPlaying ? 'active-preview' : ''}" id="vgc-${v.id}">
        <div class="vg-card-top">
          <span class="vg-name">${v.flag || '🗣️'} ${esc(v.name)}</span>
          <span class="vg-badge ${v.provider}">${v.provider === 'edge' ? 'Gratis $0' : 'Gemini'}</span>
        </div>
        <div class="vg-tone">${esc(v.tone)} · ${esc(v.country)}</div>
        <div class="vg-desc">${esc(v.description)}</div>
        <div class="vg-tags">
          ${(v.tags || []).map(t => `<span class="vg-tag">${esc(t)}</span>`).join('')}
        </div>
        <div class="vg-actions">
          <button class="btn small ${isPlaying ? 'primary' : 'ghost'} vg-play-btn" onclick="previewVoice('${v.id}')">
            ${isLoading ? '⏳ Cargando…' : isPlaying ? '⏸️ Pausar' : '▶️ Escuchar'}
          </button>
          <button class="btn small primary vg-select-btn" onclick="selectVoiceFromGallery('${v.id}')">
            ✓ Elegir
          </button>
        </div>
      </div>`;
  }).join('');
}

async function previewVoice(voiceId) {
  if (VG_STATE.playingVoiceId === voiceId && VG_STATE.currentAudio) {
    VG_STATE.currentAudio.pause();
    VG_STATE.currentAudio = null;
    VG_STATE.playingVoiceId = null;
    renderVoiceGrid();
    return;
  }

  if (VG_STATE.currentAudio) {
    VG_STATE.currentAudio.pause();
    VG_STATE.currentAudio = null;
    VG_STATE.playingVoiceId = null;
  }

  VG_STATE.loadingVoiceId = voiceId;
  renderVoiceGrid();

  try {
    const res = await api('/voices/preview', { method: 'POST', body: { voice_id: voiceId } });
    VG_STATE.loadingVoiceId = null;
    const audio = new Audio(res.audio_url);
    VG_STATE.currentAudio = audio;
    VG_STATE.playingVoiceId = voiceId;
    renderVoiceGrid();

    audio.onended = () => {
      VG_STATE.playingVoiceId = null;
      VG_STATE.currentAudio = null;
      renderVoiceGrid();
    };
    audio.onerror = () => {
      toast('Error al reproducir audio de la voz', 'err');
      VG_STATE.playingVoiceId = null;
      VG_STATE.currentAudio = null;
      renderVoiceGrid();
    };
    await audio.play();
  } catch (err) {
    VG_STATE.loadingVoiceId = null;
    VG_STATE.playingVoiceId = null;
    renderVoiceGrid();
    toast('Error generando preescucha: ' + err.message, 'err');
  }
}

async function selectVoiceFromGallery(voiceId) {
  const v = VG_STATE.voices.find(x => x.id === voiceId);
  if (!v) return;

  if (VG_STATE.target === 'brand_form') {
    const inp = $('#bpf-voice');
    if (inp) inp.value = voiceId;
    const ttsSel = $('#bpf-tts');
    if (ttsSel) ttsSel.value = v.provider === 'gemini' ? 'gemini' : 'edge-tts';
    closeVoiceGallery();
    toast(`Voz asignada al canal: ${v.flag} ${v.name}`, 'ok');
    return;
  }

  if (VG_STATE.target === 'wizard') {
    W.voice = voiceId;
    W.tts = v.provider;
    const sel = $('#wiz-voice-select');
    if (sel) sel.value = voiceId;
    closeVoiceGallery();
    toast(`Voz seleccionada: ${v.flag} ${v.name}`, 'ok');
    return;
  }

  if (VG_STATE.target === 'avatar') {
    AV_FORM.fields.voice = voiceId;
    const sel = document.querySelector('#av-voice-select');
    if (sel) sel.value = voiceId;
    closeVoiceGallery();
    toast(`Voz asignada al avatar: ${v.flag} ${v.name}`, 'ok');
    return;
  }

  // Global settings
  try {
    await api('/voices/select', { method: 'POST', body: { voice_id: voiceId } });
    closeVoiceGallery();
    toast(`Voz predeterminada guardada: ${v.flag} ${v.name} (${v.provider})`, 'ok');
    if (S.view === 'settings') renderSettings();
  } catch (err) {
    toast('Error guardando voz: ' + err.message, 'err');
  }
}



/* ══════════════════════════════════════════════════════════════════
   INT-041 · Presets Visuales de Subtítulos (Shorts Style Switcher)
   ══════════════════════════════════════════════════════════════════ */
let SS_STATE = {
  presets: [],
  selectedId: 'shorts',
  sampleText: 'ESTO CAMBIA TODO',
  target: 'global',
  projectId: null,
};

async function openSubtitleSwitcher(opts = {}) {
  SS_STATE.target = opts.target || 'global';
  SS_STATE.projectId = opts.project_id || null;

  if (opts.current_style) {
    SS_STATE.selectedId = opts.current_style;
  } else if (opts.project_id && S.project && S.project.id === opts.project_id) {
    SS_STATE.selectedId = (S.project.meta || {}).subtitle_style || 'shorts';
  } else if (opts.target === 'wizard') {
    SS_STATE.selectedId = W.subtitles || 'shorts';
  }

  if (!SS_STATE.presets.length) {
    try {
      const res = await api('/subtitles/presets');
      SS_STATE.presets = res.presets || [];
    } catch (e) {
      toast('Error cargando catálogo de subtítulos: ' + e.message, 'err');
      return;
    }
  }

  $('#overlay-root').innerHTML = `
    <div class="overlay subs-switcher-overlay" onclick="if(event.target===this)closeSubtitleSwitcher()">
      <div class="box card">
        <div class="ss-header">
          <div>
            <h3>🎨 Presets Visuales de Subtítulos (Shorts Style Switcher)</h3>
            <p>Elige el estilo tipográfico de alta retención para tus subtítulos dinámicos.</p>
          </div>
          <button class="modal-x" onclick="closeSubtitleSwitcher()" title="Cerrar">✕</button>
        </div>

        <div class="ss-preview-stage" id="ss-stage">
          <div class="ss-stage-badge" id="ss-stage-badge">Estilo Activo</div>
          <div class="ss-stage-text" id="ss-stage-text">${esc(SS_STATE.sampleText)}</div>
        </div>

        <div class="ss-custom-input-row">
          <label style="font-size:12px;color:var(--muted);white-space:nowrap">Texto de muestra:</label>
          <input type="text" class="ss-custom-input" id="ss-custom-text"
            value="${esc(SS_STATE.sampleText)}"
            placeholder="Escribe una frase para previsualizar..."
            oninput="ssUpdateSample(this.value)">
        </div>

        <div class="ss-grid" id="ss-grid"></div>

        <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:6px">
          <button class="btn ghost" onclick="closeSubtitleSwitcher()">Cancelar</button>
          <button class="btn primary" onclick="applySelectedSubtitleStyle()">✓ Aplicar estilo</button>
        </div>
      </div>
    </div>`;

  document.addEventListener('keydown', ssEscClose);
  renderSubtitleGrid();
  updateSubtitleStage();
}

function ssEscClose(e) {
  if (e.key === 'Escape') closeSubtitleSwitcher();
}

function closeSubtitleSwitcher() {
  document.removeEventListener('keydown', ssEscClose);
  closeOverlay();
}

function ssUpdateSample(text) {
  SS_STATE.sampleText = text || 'ESTO CAMBIA TODO';
  updateSubtitleStage();
  renderSubtitleGrid();
}

function selectSubtitlePreset(presetId) {
  SS_STATE.selectedId = presetId;
  updateSubtitleStage();
  renderSubtitleGrid();
}

function updateSubtitleStage() {
  const p = SS_STATE.presets.find(x => x.id === SS_STATE.selectedId) || SS_STATE.presets[0];
  if (!p) return;
  const badge = $('#ss-stage-badge');
  if (badge) badge.textContent = `${p.emoji} ${p.name} · ${p.font}`;
  const textEl = $('#ss-stage-text');
  if (textEl) {
    const isUpper = p.id === 'mrbeast' || p.id === 'hormozi' || p.id === 'neon';
    const txt = isUpper ? SS_STATE.sampleText.toUpperCase() : SS_STATE.sampleText;
    textEl.textContent = txt;
    textEl.style.cssText = p.preview_css;
  }
}

function renderSubtitleGrid() {
  const container = $('#ss-grid');
  if (!container) return;

  container.innerHTML = SS_STATE.presets.map(p => {
    const isSel = p.id === SS_STATE.selectedId;
    const isUpper = p.id === 'mrbeast' || p.id === 'hormozi' || p.id === 'neon';
    const sample = isUpper ? SS_STATE.sampleText.toUpperCase() : SS_STATE.sampleText;
    return `
      <div class="ss-card ${isSel ? 'selected' : ''}" onclick="selectSubtitlePreset('${p.id}')">
        <div class="ss-card-top">
          <span class="ss-name">${p.emoji} ${esc(p.name)}</span>
          ${isSel ? '<span style="color:var(--accent);font-size:12px;font-weight:700">✓ ACTIVO</span>' : ''}
        </div>
        <div class="ss-sample-box">
          <div style="${p.preview_css};font-size:14px;pointer-events:none">${esc(sample.slice(0, 22))}</div>
        </div>
        <div class="ss-desc">${esc(p.description)}</div>
        <div class="ss-tags">
          ${(p.tags || []).map(t => `<span class="ss-tag">${esc(t)}</span>`).join('')}
        </div>
      </div>`;
  }).join('');
}

async function applySelectedSubtitleStyle() {
  const sid = SS_STATE.selectedId;
  const p = SS_STATE.presets.find(x => x.id === sid);
  const name = p ? `${p.emoji} ${p.name}` : sid;

  if (SS_STATE.target === 'brand_form') {
    const sel = $('#bpf-subtitles');
    if (sel) sel.value = sid;
    closeSubtitleSwitcher();
    toast(`Subtítulo asignado al canal: ${name}`, 'ok');
    return;
  }

  if (SS_STATE.target === 'wizard') {
    W.subtitles = sid;
    const sel = $('#wiz-sub-select');
    if (sel) sel.value = sid;
    closeSubtitleSwitcher();
    toast(`Estilo de subtítulo seleccionado: ${name}`, 'ok');
    return;
  }

  if (SS_STATE.target === 'project' && SS_STATE.projectId) {
    try {
      await api('/subtitles/apply', {
        method: 'POST',
        body: { style_id: sid, project_id: SS_STATE.projectId }
      });
      if (S.project && S.project.id === SS_STATE.projectId) {
        S.project.meta = S.project.meta || {};
        S.project.meta.subtitle_style = sid;
        renderProject();
      }
      closeSubtitleSwitcher();
      toast(`Estilo de subtítulo actualizado en el proyecto: ${name}`, 'ok');
      return;
    } catch (e) {
      toast('Error al aplicar subtítulos: ' + e.message, 'err');
      return;
    }
  }

  // Global default
  try {
    await api('/subtitles/apply', { method: 'POST', body: { style_id: sid } });
    closeSubtitleSwitcher();
    toast(`Estilo de subtítulo predeterminado guardado: ${name}`, 'ok');
  } catch (e) {
    toast('Error: ' + e.message, 'err');
  }
}


/* ══ INT-044 · VIRAL CLIPPER (LONG-TO-SHORTS) ══════════════════════════════
   Inspirado en OpenShorts: Transforma videos largos de YouTube en Shorts 9:16
   con detección de momentos virales, Virality Score (0-100) y recorte FFmpeg. */
let CLIPPER_STATE = {
  url: '',
  source: null,
  moments: [],
  loading: false,
  renderingId: null
};

function renderClipper() {
  const S_c = CLIPPER_STATE;
  let resultsHTML = '';

  if (S_c.loading) {
    resultsHTML = `
      <div class="card" style="text-align:center; padding:40px 20px;">
        <div style="font-size:32px; animation:spin 1s infinite linear;">⏳</div>
        <h3 style="margin:12px 0 6px;">Analizando video y transcribiendo timestamps…</h3>
        <p class="hintline">El Estratega Viral de IA está evaluando el gancho de retención y calculando el Virality Score de cada momento.</p>
      </div>`;
  } else if (S_c.source && S_c.moments.length) {
    const src = S_c.source;
    resultsHTML = `
      <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:16px;">
          <div>
            <h3 style="margin:0;">🎬 Video origen: ${esc(src.title)}</h3>
            <span class="hintline">Canal: <b>${esc(src.channel)}</b> · Duración: <b>${esc(src.duration_fmt)}</b> · <b>${S_c.moments.length} momentos virales</b> detectados</span>
          </div>
          <button class="btn ghost" onclick="clipperReset()">🔄 Analizar otro video</button>
        </div>

        <div class="clipper-moments-grid">
          ${S_c.moments.map(m => {
            const isRendering = S_c.renderingId === m.id;
            const scoreClass = m.virality_score >= 90 ? 'score-ultra' : (m.virality_score >= 80 ? 'score-high' : 'score-good');
            const hookS = m.hook_score || m.virality_score;
            const flowS = m.flow_score || Math.max(60, m.virality_score - 2);
            const valS = m.value_score || m.virality_score;
            const tags = m.hashtags || ['#viral', '#podcast', '#shorts'];

            return `
              <div class="clipper-moment-card" id="card-${m.id}">
                <div class="clipper-card-header">
                  <div class="clipper-card-title">#${m.rank} ${esc(m.title)}</div>
                  <span class="clipper-score-badge ${scoreClass}">🔥 ${m.virality_score}/100</span>
                </div>

                <!-- INT-057: Matriz de 3 Pilares OpusClip -->
                <div class="clipper-score-pillars">
                  <div class="clipper-pillar-item">
                    <span>🎯 Hook</span>
                    <b>${hookS}%</b>
                  </div>
                  <div class="clipper-pillar-item">
                    <span>📈 Ritmo</span>
                    <b>${flowS}%</b>
                  </div>
                  <div class="clipper-pillar-item">
                    <span>💡 Valor</span>
                    <b>${valS}%</b>
                  </div>
                </div>

                <!-- INT-057: Ajustador Fino de Tiempos (Trim +/-2s estilo Klap) -->
                <div class="clipper-trim-bar">
                  <div>
                    <span style="color:var(--muted); font-size:10.5px; display:block;">Inicio:</span>
                    <button type="button" class="clipper-trim-btn" onclick="clipperAdjustStart('${m.id}', -2)">-2s</button>
                    <b id="start-disp-${m.id}" style="color:var(--text); margin:0 4px;">${esc(m.start_fmt)}</b>
                    <button type="button" class="clipper-trim-btn" onclick="clipperAdjustStart('${m.id}', 2)">+2s</button>
                  </div>
                  <div style="text-align:center;">
                    <span style="color:var(--muted); font-size:10.5px; display:block;">Duración:</span>
                    <b id="dur-disp-${m.id}" style="color:var(--accent); font-size:12.5px;">${m.duration}s</b>
                  </div>
                  <div>
                    <span style="color:var(--muted); font-size:10.5px; display:block;">Fin:</span>
                    <button type="button" class="clipper-trim-btn" onclick="clipperAdjustEnd('${m.id}', -2)">-2s</button>
                    <b id="end-disp-${m.id}" style="color:var(--text); margin:0 4px;">${esc(m.end_fmt)}</b>
                    <button type="button" class="clipper-trim-btn" onclick="clipperAdjustEnd('${m.id}', 2)">+2s</button>
                  </div>
                </div>

                <div class="clipper-hook-box">
                  <b>🎯 Hook Inicial:</b>
                  ${esc(m.hook || m.summary)}
                </div>

                <div class="clipper-reason-box">
                  💡 <b>Por qué engancha:</b> ${esc(m.reason)}
                </div>

                <!-- INT-057: Consejo Táctico y Hashtags Virales -->
                <div class="clipper-advice-box">
                  🚀 <b>Estrategia:</b> ${esc(m.viral_advice || 'Publicar en horas pico de TikTok con subtítulos llamativos.')}
                </div>

                <div>
                  ${tags.map(t => `<span class="clipper-tag-pill" onclick="navigator.clipboard.writeText('${t}');toast('Copiado: ${t}')">${t}</span>`).join('')}
                </div>

                <div id="preview-${m.id}"></div>
                <div class="clipper-card-actions">
                  <button class="btn btn-primary" id="btn-render-${m.id}" onclick="clipperRenderMoment('${m.id}')" ${isRendering ? 'disabled' : ''}>
                    ${isRendering ? '⏳ Cortando…' : '🎬 Cortar Short 9:16'}
                  </button>
                  <button class="btn ghost" onclick="clipperSaveProject('${m.id}')">🗂️ Guardar Proyecto</button>
                </div>
              </div>`;
          }).join('')}
        </div>
      </div>`;
  }

  $('#view').innerHTML = `
    <div class="clipper-container">
      <div class="clipper-hero">
        <h2>✂️ Clipper Viral <span class="hint" style="color:var(--accent); font-weight:700;">Long-to-Shorts (OpenShorts Engine)</span></h2>
        <p>Pega un enlace de YouTube de cualquier podcast, entrevista o video largo. La IA detectará los momentos con mayor probabilidad de volverse virales con su <b>Virality Score</b> y los recortará a formato vertical 9:16 con fondo difuminado en 1 clic.</p>
      </div>

      <div class="clipper-form-card">
        <div class="clipper-input-row">
          <input type="text" id="clipper-url-input" placeholder="https://www.youtube.com/watch?v=... o video largo" value="${esc(S_c.url)}" oninput="CLIPPER_STATE.url = this.value">
          <button class="btn btn-primary" id="clipper-analyze-btn" onclick="clipperRunAnalysis()" ${S_c.loading ? 'disabled' : ''} style="font-weight:700; padding:10px 18px;">
            ${S_c.loading ? '⏳ Analizando…' : '🔍 Detectar Momentos Virales'}
          </button>
        </div>

        <div class="clipper-selects-row">
          <div class="clipper-field">
            <label for="clipper-count">Cantidad de momentos</label>
            <select id="clipper-count">
              <option value="3">3 momentos</option>
              <option value="5" selected>5 momentos (Recomendado)</option>
              <option value="8">8 momentos</option>
              <option value="10">10 momentos</option>
            </select>
          </div>
          <div class="clipper-field">
            <label for="clipper-dur">Rango de duración</label>
            <select id="clipper-dur">
              <option value="20-65" selected>Short estándar (20s - 65s)</option>
              <option value="15-35">Ultra rápido (15s - 35s)</option>
              <option value="40-90">Extendido (40s - 90s)</option>
            </select>
          </div>
          <div class="clipper-field">
            <label for="clipper-style">Estilo de reencuadre 9:16</label>
            <select id="clipper-style">
              <option value="blur_bg" selected>Podcast con fondo difuminado (Recomendado)</option>
              <option value="center_crop">Recorte centrado directo 9:16</option>
              <option value="split_screen">👥 Split-Screen (Podcast 2 Hablantes: Arriba/Abajo)</option>
              <option value="face_tracking">🎯 Auto Face-Tracking (Cámara inteligente que sigue caras)</option>
              <option value="speaker_switch">🎙️ Active Speaker Switch (Corte dinámico al que habla)</option>
            </select>
          </div>
          <div class="clipper-field">
            <label for="clipper-subs-style">Subtítulos Karaoke Dinámicos</label>
            <select id="clipper-subs-style">
              <option value="hormozi" selected>🔥 Hormozi Pop (Amarillo Impacto)</option>
              <option value="mrbeast">⚡ MrBeast Neon (Verde Eléctrico)</option>
              <option value="cyberpunk">👾 Cyberpunk Glitch (Magenta Neon)</option>
              <option value="minimal">✨ Clean Minimal (Blanco Suave)</option>
              <option value="none">Sin subtítulos quemados</option>
            </select>
          </div>
          <div class="clipper-field" style="display:flex; flex-direction:column; justify-content:center;">
            <label style="display:flex; align-items:center; gap:8px; cursor:pointer; font-weight:600; margin-top:14px;">
              <input type="checkbox" id="clipper-broll-toggle" checked style="width:16px; height:16px; accent-color:var(--accent);">
              <span>🎥 Auto B-Roll Cutaway</span>
            </label>
            <span style="font-size:10.5px; color:var(--muted);">Pexels overlay anti-aburrimiento</span>
          </div>
          <div class="clipper-field" style="display:flex; flex-direction:column; justify-content:center;">
            <label style="display:flex; align-items:center; gap:8px; cursor:pointer; font-weight:600; margin-top:14px;">
              <input type="checkbox" id="clipper-emojis-toggle" checked style="width:16px; height:16px; accent-color:var(--accent);">
              <span>😀 Emojis Dinámicos</span>
            </label>
            <span style="font-size:10.5px; color:var(--muted);">Estilo CapCut / OpusClip (+35% retención)</span>
          </div>
          <div class="clipper-field" style="display:flex; flex-direction:column; justify-content:center;">
            <label style="display:flex; align-items:center; gap:8px; cursor:pointer; font-weight:600; margin-top:14px;">
              <input type="checkbox" id="clipper-pb-toggle" checked style="width:16px; height:16px; accent-color:var(--accent);">
              <span>📊 Barra Progreso 9:16</span>
            </label>
            <span style="font-size:10.5px; color:var(--muted);">Barra inferior dinámica (retención Shorts)</span>
          </div>
        </div>
      </div>

      <div id="clipper-results-zone">
        ${resultsHTML}
      </div>
    </div>`;
}

async function clipperRunAnalysis() {
  const urlEl = $('#clipper-url-input');
  const url = (urlEl ? urlEl.value : CLIPPER_STATE.url).trim();
  if (!url) { toast('Pega una URL válida de YouTube o podcast', 'err'); return; }

  const count = parseInt($('#clipper-count') ? $('#clipper-count').value : '5', 10);
  const durVal = ($('#clipper-dur') ? $('#clipper-dur').value : '20-65').split('-');
  const minDur = parseInt(durVal[0], 10);
  const maxDur = parseInt(durVal[1], 10);

  CLIPPER_STATE.url = url;
  CLIPPER_STATE.loading = true;
  CLIPPER_STATE.source = null;
  CLIPPER_STATE.moments = [];
  renderClipper();

  try {
    const res = await api('/clipper/analyze', {
      method: 'POST',
      body: { url, count, min_duration: minDur, max_duration: maxDur }
    });
    CLIPPER_STATE.source = res.source;
    CLIPPER_STATE.moments = res.moments || [];
    toast(`¡Análisis completado! Se detectaron ${CLIPPER_STATE.moments.length} momentos virales 🎯`, 'ok');
  } catch (e) {
    toast('Error al analizar video: ' + e.message, 'err');
  } finally {
    CLIPPER_STATE.loading = false;
    renderClipper();
  }
}

function clipperFormatTs(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
}

function clipperAdjustStart(momentId, delta) {
  const m = CLIPPER_STATE.moments.find(x => x.id === momentId);
  if (!m) return;
  const newStart = Math.max(0, Math.round((m.start + delta) * 10) / 10);
  if (m.end - newStart < 5.0) {
    toast('La duración mínima de clip es de 5 segundos', 'err');
    return;
  }
  m.start = newStart;
  m.duration = Math.round((m.end - m.start) * 10) / 10;
  m.start_fmt = clipperFormatTs(m.start);
  const startEl = $(`#start-disp-${momentId}`);
  const durEl = $(`#dur-disp-${momentId}`);
  if (startEl) startEl.textContent = m.start_fmt;
  if (durEl) durEl.textContent = `${m.duration}s`;
}

function clipperAdjustEnd(momentId, delta) {
  const m = CLIPPER_STATE.moments.find(x => x.id === momentId);
  if (!m) return;
  const newEnd = Math.max(m.start + 5.0, Math.round((m.end + delta) * 10) / 10);
  m.end = newEnd;
  m.duration = Math.round((m.end - m.start) * 10) / 10;
  m.end_fmt = clipperFormatTs(m.end);
  const endEl = $(`#end-disp-${momentId}`);
  const durEl = $(`#dur-disp-${momentId}`);
  if (endEl) endEl.textContent = m.end_fmt;
  if (durEl) durEl.textContent = `${m.duration}s`;
}

window.clipperAdjustStart = clipperAdjustStart;
window.clipperAdjustEnd = clipperAdjustEnd;

function clipperReset() {
  CLIPPER_STATE = { url: '', source: null, moments: [], loading: false, renderingId: null };
  renderClipper();
}

async function clipperRenderMoment(momentId) {
  const m = CLIPPER_STATE.moments.find(x => x.id === momentId);
  if (!m) return;
  const btn = $(`#btn-render-${momentId}`);
  const previewZone = $(`#preview-${momentId}`);
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Cortando y exportando…'; }

  const style = $('#clipper-style') ? $('#clipper-style').value : 'blur_bg';
  const subsStyle = $('#clipper-subs-style') ? $('#clipper-subs-style').value : 'hormozi';
  const broll = $('#clipper-broll-toggle') ? $('#clipper-broll-toggle').checked : false;
  const autoEmojis = $('#clipper-emojis-toggle') ? $('#clipper-emojis-toggle').checked : true;
  const progressBar = $('#clipper-pb-toggle') ? $('#clipper-pb-toggle').checked : true;

  try {
    toast(`Descargando, reencuadrando, insertando B-Roll y quemando Karaoke a "${m.title}"…`);
    const res = await api('/clipper/render', {
      method: 'POST',
      body: {
        url: CLIPPER_STATE.url,
        start: m.start,
        end: m.end,
        title: m.title,
        style: style,
        subtitle_text: m.quote || '',
        subtitle_style: subsStyle,
        broll: broll
      }
    });

    toast(`¡Short 9:16 generado con éxito! 🎬`, 'ok');
    m.video_url = res.url;
    m.file_name = res.file_name;

    if (previewZone) {
      previewZone.innerHTML = `
        <div class="clipper-video-preview">
          <video controls autoplay muted src="${esc(res.url)}"></video>
          <div style="display:flex; justify-content:space-between; width:100%; margin-top:6px; font-size:11.5px;">
            <a href="${esc(res.url)}" download="${esc(res.file_name)}" class="btn" style="padding:4px 10px; font-size:11px;">⬇️ Descargar MP4</a>
            <span style="color:var(--muted); align-self:center;">Vertical 9:16 (${res.duration}s)</span>
          </div>
        </div>`;
    }
  } catch (e) {
    toast('Error al renderizar momento: ' + e.message, 'err');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🎬 Recortar de nuevo'; }
  }
}

async function clipperSaveProject(momentId) {
  const m = CLIPPER_STATE.moments.find(x => x.id === momentId);
  if (!m) return;
  try {
    const res = await api('/clipper/create-project', {
      method: 'POST',
      body: {
        title: m.title,
        hook: m.hook,
        summary: m.summary,
        url: CLIPPER_STATE.url,
        video_url: m.video_url || '',
        start: m.start,
        end: m.end
      }
    });
    toast('¡Proyecto guardado en tu biblioteca! 🗂️', 'ok');
    await refreshAll();
  } catch (e) {
    toast('Error al guardar proyecto: ' + e.message, 'err');
  }
}


/* ── INT-061: Multi-Angle UGC Hooks Generator (Arcads / CreateUGC Style) ── */
let CURRENT_QC_HOOKS = [];

async function generateQCHooks() {
  const inp = document.getElementById('qc-input-text');
  const prodName = inp ? inp.value.trim() : '';
  const container = document.getElementById('qc-hooks-container');
  if (!container) return;

  container.style.display = 'block';
  container.innerHTML = `
    <div style="text-align:center; padding:18px; color:var(--muted);">
      <div style="font-size:24px; animation:spin 1s linear infinite; display:inline-block;">⚡</div>
      <p style="margin-top:8px; font-size:12px;">Generando 5 ganchos psicológicos con IA (Arcads & CreateUGC formulas)...</p>
    </div>
  `;

  try {
    const res = await api('/api/ugc/multi-angle-hooks', {
      method: 'POST',
      body: JSON.stringify({ product_name: prodName })
    });
    if (!res || !res.ok || !res.hooks) throw new Error('No se pudieron generar los ganchos');
    CURRENT_QC_HOOKS = res.hooks;
    renderQCHooksList(CURRENT_QC_HOOKS, prodName);
  } catch (err) {
    container.innerHTML = `<div style="color:var(--danger); padding:10px; font-size:12px;">❌ Error: ${esc(err.message)}</div>`;
  }
}

function renderQCHooksList(hooks, prodName) {
  const container = document.getElementById('qc-hooks-container');
  if (!container) return;

  const html = hooks.map((h, i) => `
    <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:12px; margin-bottom:10px; transition:border-color 0.2s;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="font-weight:700; font-size:13px; color:#fff;">${esc(h.badge)}</span>
          <span class="badge" style="background:rgba(99,102,241,0.2); color:#a5b4fc; font-size:10px; padding:2px 6px; border-radius:4px;">${esc(h.tag)}</span>
        </div>
        <div style="display:flex; align-items:center; gap:6px;">
          <span style="font-size:11px; color:var(--muted);">Stop-Rate:</span>
          <span class="badge" style="background:rgba(16,185,129,0.2); color:#34d399; font-weight:800; font-size:11px; padding:2px 6px; border-radius:4px;">${h.predicted_stop_rate}%</span>
        </div>
      </div>
      <p style="font-size:12.5px; line-height:1.45; color:var(--text); margin:0 0 8px 0; font-style:italic;">"${esc(h.hook_text)}"</p>
      <div style="font-size:11px; color:var(--muted); margin-bottom:10px; display:flex; align-items:center; gap:4px;">
        <span>🎬 <b>Visual Cue:</b></span> <span>${esc(h.visual_cue)}</span>
      </div>
      <div style="display:flex; gap:8px; justify-content:flex-end;">
        <button type="button" class="btn ghost small" style="padding:4px 10px; font-size:11px;" onclick="playHookTTSPreview('${esc(h.hook_text.replace(/'/g, "\\'"))}', this)">
          🎧 Escuchar Gancho
        </button>
        <button type="button" class="btn primary small" style="padding:4px 12px; font-size:11px;" onclick="selectQCHook('${esc(h.hook_text.replace(/'/g, "\\'"))}')">
          ✅ Usar este Gancho
        </button>
      </div>
    </div>
  `).join('');

  container.innerHTML = `
    <div style="margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;">
      <span style="font-size:11.5px; font-weight:700; color:var(--muted);">Fórmulas ordenadas por Retención (Stop-Rate):</span>
      <button type="button" class="btn ghost small" style="padding:4px 10px; font-size:11px; color:#a5b4fc; border:1px solid rgba(165,180,252,0.3);" onclick="generateABVariantsModal('${esc((prodName || '').replace(/'/g, "\\'"))}')">
        📦 Matriz A/B (5 Variantes)
      </button>
    </div>
    ${html}
  `;
}

async function playHookTTSPreview(text, btn) {
  const origText = btn.innerHTML;
  btn.innerHTML = '⏳ Cargando...';
  btn.disabled = true;
  try {
    const res = await api('/api/ugc/preview-tts-hook', {
      method: 'POST',
      body: JSON.stringify({ text })
    });
    if (res && res.ok && res.audio_url) {
      const audio = new Audio(res.audio_url);
      audio.play();
      btn.innerHTML = '🔊 Reproduciendo...';
      audio.onended = () => {
        btn.innerHTML = origText;
        btn.disabled = false;
      };
    } else {
      throw new Error('No se pudo generar el audio');
    }
  } catch (err) {
    toast('Error en preview TTS: ' + err.message, 'error');
    btn.innerHTML = origText;
    btn.disabled = false;
  }
}

function selectQCHook(hookText) {
  QC_STATE.selectedHook = hookText;
  toast('¡Gancho fijado con éxito para tu anuncio!', 'success');
}

async function generateABVariantsModal(prodName) {
  try {
    toast('Construyendo matriz A/B de 5 variantes...', 'info');
    const res = await api('/api/ugc/ab-variants', {
      method: 'POST',
      body: JSON.stringify({
        product_name: prodName || 'Producto Viral',
        hooks: CURRENT_QC_HOOKS
      })
    });
    if (!res || !res.ok) throw new Error('Error al construir variantes');
    const variants = res.variants;
    alert(`🎉 Matriz A/B UGC lista con ${variants.length} variantes (Arcads Cloned):\n\n` +
      variants.map(v => `${v.variant_letter}) [${v.badge}] Stop-Rate: ${v.predicted_stop_rate}% | Duración: ${v.total_duration_sec}s`).join('\n') +
      '\n\nCada variante tiene su propio gancho inicial y comparte el cuerpo demostrativo y llamada a la acción para testeo A/B rápido.');
  } catch (err) {
    toast('Error: ' + err.message, 'error');
  }
}

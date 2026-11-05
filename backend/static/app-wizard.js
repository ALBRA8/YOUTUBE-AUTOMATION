/* ============================================================
   app-wizard.js — INT-088 · asistente Crear y pickers
   Modal rápido 1-clic, wizard 4 pasos con selector de plantillas
   (INT-087), Brand Profiles, admin de nichos, avatares, galería
   de voces (INT-040) y presets de subtítulos (INT-041).
   ============================================================ */
'use strict';

/* ── MODAL DE CREACIÓN RÁPIDA 1-CLIC (Estilo LabsIA · $0.00) ── */
const QC_STATE = {
  tpl: '',   // INT-087: plantilla de nicho seleccionada
  mode: 'idea',
  format: 'short',
  pacing: 'normal',
  style: 'auto',
  subtitles: 'shorts',
  voice: '',
  title: '',
  text: '',
  url: '',
  audioFile: null,
  destino: ''   // INT-091: carpeta de destino elegida con el explorador de Windows
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

        ${renderTplCards('qc')}

        ${inputField}

        <!-- INT-091 · libre elección de carpeta destino (diálogo nativo Windows) -->
        <div class="field" style="margin-bottom:14px;">
          <label style="font-size:13px; font-weight:700; margin-bottom:6px; display:block;">📂 Carpeta de destino en tu PC <small style="color:var(--muted); font-weight:400;">(opcional — vacío = carpeta estándar del servidor)</small></label>
          <div style="display:flex; gap:8px; align-items:center;">
            <input type="text" id="qc-destino" readonly value="${esc(QC_STATE.destino || '')}" placeholder="D:\\PROYECTOS\\FRUTINOVELAS\\Mi_Video" style="flex:1; border-radius:10px; padding:10px; font-size:12px; color:var(--muted);">
            <button type="button" class="btn" style="padding:10px 14px; font-size:12px; white-space:nowrap;" onclick="qcPickDestino()" title="Abre el diálogo nativo de Windows para elegir la carpeta exacta">🔍 Examinar en mi PC</button>
          </div>
          <small style="color:var(--muted); display:block; margin-top:5px;">marca.json, guion/ y out/ nacen DIRECTAMENTE en la carpeta que elijas (INT-091).</small>
        </div>

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
    if (QC_STATE.tpl) body.template_id = QC_STATE.tpl;  // INT-087: plantilla de nicho
    if (QC_STATE.destino) body.custom_workspace_path = QC_STATE.destino;  // INT-091: destino del usuario
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

    const p = await api('/projects', {
      method: 'POST',
      // INT-080: audio_path viaja en el POST (puerta validada server-side) —
      // el PATCH meta_patch anterior recibía 403 por M6 y la voz se perdía.
      body: audioPath ? { ...body, audio_path: audioPath } : body
    });

    closeOverlay();
    toast('¡Fabricación iniciada! 🚀 El motor IA está creando tu video', 'ok');
    startJob(p.id);
  } catch (err) {
    toast('Error: ' + err.message, 'err');
    if (btn) { btn.disabled = false; btn.textContent = '🚀 Fabricar Video Ahora ($0.00)'; }
  }
}

/* ── INT-091 · Carpeta de destino elegida por el usuario ─────────────
   Diálogo NATIVO del PC (POST /api/dialog/pick-folder → Explorador de
   Windows): el usuario elige la carpeta EXACTA donde vivirán marca.json,
   guion/ y out/ del proyecto. El path devuelto viaja en la creación como
   custom_workspace_path y el pipeline lo respeta absoluto.
   NOTA: se usa el diálogo del SERVIDOR y no window.showDirectoryPicker()
   porque el File System Access API NO entrega rutas físicas reales
   (solo handles sandboxeados sin «D:\…») — el requisito es la ruta real. */
async function pickDestinoFolder() {
  toast('Abriendo explorador de tu PC… 📂');
  try {
    const r = await api('/dialog/pick-folder', { method: 'POST' });
    if (r.ok && r.path) { toast('📂 Carpeta destino: ' + r.path, 'ok'); return r.path; }
    toast('No se eligió ninguna carpeta', 'err');
    return null;
  } catch (e) { toast('No se pudo abrir el diálogo: ' + e.message, 'err'); return null; }
}

async function qcPickDestino() {
  const p = await pickDestinoFolder();
  if (p) { QC_STATE.destino = p; renderQuickCreateModal(); }
}

async function wizardPickDestino() {
  const p = await pickDestinoFolder();
  if (p) { W.destino = p; renderCreate(); }
}

window.openQuickCreateModal = openQuickCreateModal;
window.startDirectCreation = openQuickCreateModal;
window.qcSwitchMode = qcSwitchMode;
window.executeQuickCreate = executeQuickCreate;
window.openWizardFromQC = openWizardFromQC;
window.pickDestinoFolder = pickDestinoFolder;    // INT-091
window.qcPickDestino = qcPickDestino;            // INT-091
window.wizardPickDestino = wizardPickDestino;    // INT-091


/* ── v2.36 · INT-079 · Brand Profiles en el asistente ─────────────
   INT-042 añadió la llamada renderWizardBrandProfileBar() pero la definición
   nunca existió → ReferenceError silencioso que mataba TODO el asistente
   Crear (✨ Crear, ＋ Nuevo video en nicho, CTA de nichos, wizard rápido).
   Regla de oro: la barra NUNCA lanza — sin perfiles o con error → ''. */
function renderWizardBrandProfileBar() {
  try {
    const profiles = S.brandProfiles || [];
    if (!profiles.length) return '';   // sin perfiles → wizard clásico intacto
    const sel = profiles.find(p => p.id === W.brandProfile);
    const hint = sel ? [sel.niche, sel.tone].filter(Boolean).map(esc).join(' · ') : '';
    return `
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:10px;padding:10px 14px;margin-bottom:14px">
        <span style="font-size:12.5px;font-weight:700;color:var(--muted)">🏢 Perfil de marca:</span>
        <select onchange="W.brandProfile=this.value;if(W.brandProfile){applyBrandToWizard();toast('Perfil de marca aplicado 🏢','ok')}renderCreate()" style="max-width:280px">
          <option value="">— Sin perfil (configuración manual) —</option>
          ${profiles.map(p => `<option value="${p.id}" ${W.brandProfile === p.id ? 'selected' : ''}>${p.is_default ? '⭐ ' : ''}${esc(p.name)}</option>`).join('')}
        </select>
        ${hint ? `<small style="color:var(--muted);font-size:11.5px">${hint}</small>` : ''}
        <small style="color:var(--muted);font-size:11px;margin-left:auto"><a href="#" onclick="openBrandProfilesModal();return false" style="color:var(--accent2)">Administrar</a></small>
      </div>`;
  } catch (e) { return ''; }   // jamás puede tumbar el asistente
}

/* autofill 1-clic (documentado en Ajustes): solo campos seguros, sin pisar
   decisiones del usuario — lo vacío en el perfil se deja como esté. */
function applyBrandToWizard() {
  const p = (S.brandProfiles || []).find(x => x.id === W.brandProfile);
  if (!p) return;
  if (p.subtitle_style) W.subtitles = p.subtitle_style;
  if (p.visual_style && p.visual_style !== 'auto') W.style = p.visual_style;
  if (p.tts_provider === 'gemini') W.voice = 'gemini';
  else if (p.tts_provider === 'edge-tts') W.voice = '';
}

/* v2.36 · INT-079 · modal de administración de Canales y Marcas.
   INT-042 dejó el botón de Ajustes apuntando a una función inexistente. */
async function openBrandProfilesModal() {
  if (guardDemo()) return;
  try { S.brandProfiles = (await api('/brand-profiles')).profiles || []; } catch (e) {}
  $('#overlay-root').innerHTML = `<div class="overlay nicho-overlay" onclick="if(event.target===this)closeOverlay()"><div class="box card nicho-box">
    <div class="nicho-modal-head">
      <h3>🏢 Canales y Marcas</h3>
      <button class="modal-x" onclick="closeOverlay()" title="Cerrar">✕</button>
    </div>
    ${renderBrandProfilesAdmin()}
  </div></div>`;
  document.addEventListener('keydown', nichoEscClose);
}

function renderBrandProfilesAdmin() {
  const profiles = S.brandProfiles || [];
  return `
    <div class="field"><label>Nombre del canal / marca *</label><input type="text" id="bp-name" placeholder="Canal Principal / Shorts Virales"></div>
    <div class="row">
      <div class="field"><label>Nicho</label><input type="text" id="bp-niche" placeholder="Curiosidades y Misterios"></div>
      <div class="field"><label>Estilo visual</label><select id="bp-style">
        <option value="auto">auto</option>
        ${(S.styles || []).map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('')}
      </select></div>
    </div>
    <div class="field"><label>Audiencia objetivo</label><input type="text" id="bp-audience" placeholder="Audiencia joven (18-35) en TikTok/Shorts..."></div>
    <div class="field"><label>Tono de voz</label><input type="text" id="bp-tone" placeholder="Directo, intrigante, ritmo acelerado"></div>
    <div class="row">
      <div class="field"><label>Voz neuronal</label><input type="text" id="bp-voice" placeholder="es-ES-AlvaroNeural"></div>
      <div class="field" style="max-width:130px"><label>TTS</label><select id="bp-tts">
        <option value="edge-tts">edge-tts</option><option value="gemini">gemini</option>
      </select></div>
      <div class="field"><label>Subtítulos</label><select id="bp-subs">
        ${['shorts','hormozi','mrbeast','neon','tiktok','boxed','minimal','karaoke'].map(v => `<option value="${v}">${v}</option>`).join('')}
      </select></div>
    </div>
    <div class="field"><label>Reglas y directivas de guion</label><textarea id="bp-rules" rows="3" placeholder="1. Gancho de impacto en los primeros 3 segundos...\n2. Frases concisas (máx 12 palabras)...\n3. Tensión narrativa hasta la última escena."></textarea></div>
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;margin-bottom:10px;cursor:pointer">
      <input type="checkbox" id="bp-default"> ⭐ Marcar como predeterminado (autocompleta nuevos videos)</label>
    <button class="btn small primary" onclick="saveBrandProfile()">💾 Guardar perfil</button>
    <div class="card" style="margin-top:10px">${profiles.length ? profiles.map(p => `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid rgba(128,128,128,.15)">
        <span>${p.is_default ? '⭐ ' : '🏢 '} <b>${esc(p.name)}</b> <small style="color:var(--muted)">· ${esc(p.niche || 'sin nicho')}</small></span>
        <span style="display:flex;gap:6px">
          ${p.is_default ? '' : `<button class="btn small ghost" onclick="setBrandDefault('${p.id}')" title="Hacer predeterminado">⭐</button>`}
          <button class="btn small danger" onclick="delBrandProfile('${p.id}')">🗑️</button>
        </span>
      </div>`).join('') : '<span style="color:var(--muted);font-size:13px">Sin perfiles aún — crea el primero arriba.</span>'}</div>`;
}

async function saveBrandProfile() {
  if (guardDemo()) return;
  try {
    await api('/brand-profiles', { method: 'POST', body: {
      name: $('#bp-name').value, niche: $('#bp-niche').value,
      audience: $('#bp-audience').value, tone: $('#bp-tone').value,
      visual_style: $('#bp-style') ? $('#bp-style').value : 'auto',
      voice: ($('#bp-voice').value || '').trim() || 'es-ES-AlvaroNeural',
      tts_provider: $('#bp-tts') ? $('#bp-tts').value : 'edge-tts',
      subtitle_style: $('#bp-subs') ? $('#bp-subs').value : 'hormozi',
      prompt_rules: $('#bp-rules').value,
      is_default: !!($('#bp-default') && $('#bp-default').checked) }});
    S.brandProfiles = (await api('/brand-profiles')).profiles || [];
    toast('Perfil de marca guardado ✅', 'ok');
    openBrandProfilesModal();
    if (S.view === 'settings') renderSettings();
  } catch (e) { toast(e.message, 'err'); }
}

async function delBrandProfile(id) {
  if (guardDemo()) return;
  try {
    await api('/brand-profiles/' + id, { method: 'DELETE' });
    if (W.brandProfile === id) W.brandProfile = '';
    S.brandProfiles = (await api('/brand-profiles')).profiles || [];
    toast('Perfil eliminado');
    openBrandProfilesModal();
    if (S.view === 'settings') renderSettings();
  } catch (e) { toast(e.message, 'err'); }
}

async function setBrandDefault(id) {
  if (guardDemo()) return;
  try {
    await api('/brand-profiles/' + id + '/default', { method: 'POST' });
    S.brandProfiles = (await api('/brand-profiles')).profiles || [];
    toast('Perfil predeterminado ⭐', 'ok');
    openBrandProfilesModal();
    if (S.view === 'settings') renderSettings();
  } catch (e) { toast(e.message, 'err'); }
}

/* ── vista: WIZARD CREAR (4 pasos como Labsia) ───────────── */
const W = { step: 1, mode: 'idea', format: 'short', style: 'auto',
            title: '', idea: '', script: '', url: '', custom: '', voice: '', tts: '',
            avatar: '', platforms: ['youtube', 'tiktok'],
            transitions: true, styleReference: true, subtitles: 'shorts', brandProfile: '',
            cookies: '', nicho: '', nichoAdjust: '', pacing: 'normal',
            tpl: '', nicheLabel: '',   // INT-087: plantilla de nicho + nicho de marca
            destino: '' };  // INT-091: carpeta de destino elegida con el explorador

/* ── INT-087 · selector de plantillas de nicho (marca.json + workspace) ── */
let TPLS = [];            // catálogo GET /api/templates
let TPLS_LOADED = false;

async function loadTemplates(force) {
  if (TPLS_LOADED && !force) return TPLS;
  try {
    const r = await fetch('/api/templates');
    if (r.ok) { TPLS = await r.json(); TPLS_LOADED = true; }
  } catch (e) { /* best-effort: la UI funciona sin catálogo */ }
  return TPLS;
}

function tplCardHTML(t, ctx) {
  const sel = (ctx === 'qc' ? QC_STATE.tpl : W.tpl) === t.id;
  const cierre = (t.marca && t.marca.cierre) || {};
  return `
      <div class="card mode-card tpl-card ${sel ? 'sel' : ''}" data-tpl="${t.id}"
           style="${sel ? 'border-color:var(--accent2)' : ''}"
           onclick="pickTemplate('${t.id}','${ctx}')">
        <div class="emoji">${t.icono || '🎬'}</div><h3>${esc(t.nombre || t.id)}</h3>
        <p>${esc(t.descripcion || '')}</p>
        ${sel ? `<small style="color:var(--accent2);display:block;margin-top:6px">🎯 ritmo ${esc(t.ritmo || t.pacing || 'normal')} · voz ${esc(t.voice || (t.marca && t.marca.voz_default) || 'auto')}${cierre.frase ? ` · cierre: ${esc(cierre.frase)}` : ''}</small>` : ''}
      </div>`;
}

function renderTplCards(ctx) {
  if (!TPLS.length) {
    loadTemplates().then(() => { if (TPLS.length) (ctx === 'qc' ? renderQuickCreateModal() : renderCreate()); });
    return `<p style="color:var(--muted);font-size:12px;margin:6px 0">Cargando plantillas…</p>`;
  }
  return `
      <h3 style="font-size:14px;font-weight:800;margin:20px 0 4px">🧩 Plantillas de nicho (opcional)</h3>
      <small style="color:var(--muted);display:block;margin-bottom:10px">Elige una y se autocompletan nicho, voz, ritmo, subtítulos y el cierre de tu marca (marca.json) — el proyecto nace en su carpeta propia data/projects/&lt;nicho&gt;_&lt;titulo&gt;_&lt;id&gt;/.</small>
      <div class="modes">${TPLS.map(t => tplCardHTML(t, ctx)).join('')}</div>`;
}

function pickTemplate(id, ctx) {
  const t = TPLS.find(x => x.id === id) || null;
  if (ctx === 'qc') {
    QC_STATE.tpl = (QC_STATE.tpl === id) ? '' : id;   // toggle: 2º clic deselecciona
    if (QC_STATE.tpl && t) {
      QC_STATE.format = t.format || QC_STATE.format;
      QC_STATE.pacing = t.pacing || QC_STATE.pacing;
      QC_STATE.subtitles = t.subtitle_style || QC_STATE.subtitles;
      QC_STATE.voice = t.voice || QC_STATE.voice;
    }
    renderQuickCreateModal();
  } else {
    W.tpl = (W.tpl === id) ? '' : id;                 // toggle
    if (W.tpl && t) {
      W.format = t.format || W.format;
      W.pacing = t.pacing || W.pacing;
      W.subtitles = t.subtitle_style || W.subtitles;
      W.voice = t.voice || W.voice;
      W.style = t.style || W.style;
      W.nicheLabel = (t.marca && t.marca.nicho) || '';
    }
    renderCreate();
  }
}

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
        <div class="emoji">${m.emoji}</div><h3>${m.t}</h3><p>${m.d}</p></div>`).join('')}</div>
      ${renderTplCards('w')}`;
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
        <input type="text" maxlength="60" value="${esc(W.title)}" oninput="W.title=this.value" placeholder="solo referencia, lo genera la IA si lo dejas vacío"></div>
      <!-- INT-091 · libre elección de carpeta destino (diálogo nativo Windows) -->
      <div class="field"><label>📂 Carpeta de destino en tu PC <small style="color:var(--muted)">(opcional — vacío = carpeta estándar)</small></label>
        <div style="display:flex;gap:8px;align-items:center">
          <input type="text" readonly value="${esc(W.destino || '')}" placeholder="D:\\PROYECTOS\\FRUTINOVELAS\\Mi_Video" style="flex:1;color:var(--muted)">
          <button type="button" class="btn small ghost" onclick="wizardPickDestino()" title="Abre el diálogo nativo de Windows para elegir la carpeta exacta">🔍 Examinar en mi PC</button>
        </div>
        <small style="color:var(--muted);display:block;margin-top:5px">marca.json, guion/ y out/ nacen DIRECTAMENTE en la carpeta que elijas (INT-091).</small>
      </div>`;
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

  // INT-082: en el paso final, aviso visible si falta algo crítico (TTS/ffmpeg)
  if (W.step === 4 || (W.mode === 'nicho' && W.step === 2)) renderPreflightBanner();
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
        <div style="display:flex; gap:6px; margin-top:8px; padding-top:8px; border-top:1px solid rgba(255,255,255,0.06);">
          <button class="btn small" style="flex:1; padding:4px 6px; font-size:11px; background:rgba(168,85,247,0.15); color:#c084fc; border:1px solid rgba(168,85,247,0.3); font-weight:700;" onclick="animateAvatarLivePortrait('${a.id}', this)" title="Anima parpadeo y micro-movimiento facial LivePortrait">🎬 LivePortrait</button>
          <button class="btn small" style="flex:1; padding:4px 6px; font-size:11px; background:rgba(56,189,248,0.15); color:#38bdf8; border:1px solid rgba(56,189,248,0.3); font-weight:700;" onclick="lipsyncAvatarMuseTalk('${a.id}')" title="Genera habla y sincronización labial exacta con MuseTalk">👄 MuseTalk</button>
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
    const res = await api('/ugc/multi-angle-hooks', {
      body: { product_name: prodName }
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
    const res = await api('/ugc/preview-tts-hook', {
      body: { text }
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
    const res = await api('/ugc/ab-variants', {
      body: {
        product_name: prodName || 'Producto Viral',
        hooks: CURRENT_QC_HOOKS
      }
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



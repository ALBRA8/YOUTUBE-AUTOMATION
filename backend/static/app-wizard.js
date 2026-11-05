/* ============================================================
   app-wizard.js — INT-088 · pickers y modal de creación
   INT-092: el wizard antiguo de 4 pasos se PURGÓ — la creación vive
   SOLO en el modal rápido 1-clic de Inicio (sin Perfil de marca,
   sin plantillas genéricas). Quedan aquí: modal rápido, Brand
   Profiles (Ajustes), admin de nichos, avatares, galería de voces
   (INT-040) y presets de subtítulos (INT-041).
   ============================================================ */
'use strict';

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
  audioFile: null,
  destino: ''   // INT-091: carpeta de destino elegida con el explorador de Windows
};

function openQuickCreateModal(mode, prefillText) {
  QC_STATE.mode = mode || 'idea';
  QC_STATE.text = prefillText || '';  // INT-092: prefill (ideas de Tendencias, «＋ Nuevo video» de nichos)
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
        <div style="display:flex; gap:10px; margin-top:12px; flex-wrap:wrap; background:var(--soft); padding:10px; border-radius:10px; border:1px solid var(--border);">
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
                <strong style="font-size:13px; color:var(--text)">Hooks Multi-Ángulo (Arcads / CreateUGC)</strong>
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
        <input type="file" id="qc-input-file" accept="audio/*" style="width:100%; padding:10px; border-radius:10px; background:var(--soft); border:1px dashed var(--border);">
        <small style="color:var(--muted); display:block; margin-top:5px;">Sincronizaremos los subtítulos dinámicos y escenas con tu propia voz.</small>
      </div>`;
  }

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

        <!-- INT-091 · libre elección de carpeta destino (diálogo nativo Windows) -->
        <div class="field" style="margin-bottom:14px;">
          <label style="font-size:13px; font-weight:700; margin-bottom:6px; display:block;">📂 Carpeta de destino en tu PC <small style="color:var(--muted); font-weight:400;">(opcional — vacío = carpeta estándar del servidor)</small></label>
          <div style="display:flex; gap:8px; align-items:center;">
            <input type="text" id="qc-destino" readonly value="${esc(QC_STATE.destino || '')}" placeholder="D:\\PROYECTOS\\FRUTINOVELAS\\Mi_Video" style="flex:1; border-radius:10px; padding:10px; font-size:12px; color:var(--muted);">
            <button type="button" class="btn" style="padding:10px 14px; font-size:12px; white-space:nowrap;" onclick="qcPickDestino()" title="Abre el diálogo nativo de Windows para elegir la carpeta exacta">🔍 Examinar en mi PC</button>
          </div>
          <small style="color:var(--muted); display:block; margin-top:5px;">marca.json, guion/ y out/ nacen DIRECTAMENTE en la carpeta que elijas (INT-091).</small>
        </div>

        <!-- INT-092: grid mínimo — SOLO Formato + Voz (la barra de Perfil
             de marca y las plantillas genéricas se purgaron; pacing,
             estilo visual, subtítulos y avatar usan los valores por
             defecto del pipeline y se ajustan por proyecto en su visor) -->
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-bottom:16px; background:var(--soft); padding:14px; border-radius:12px; border:1px solid var(--border);">
          <div class="field" style="margin:0;">
            <label style="font-size:11.5px; font-weight:700; color:var(--muted); margin-bottom:4px; display:block;">Formato</label>
            <div style="display:flex; gap:6px;">
              <button type="button" class="btn small ${QC_STATE.format === 'short' ? 'primary' : 'ghost'}" onclick="QC_STATE.format='short';renderQuickCreateModal()" style="flex:1; padding:6px 8px; font-size:11px;">📱 9:16 Short</button>
              <button type="button" class="btn small ${QC_STATE.format === 'long' ? 'primary' : 'ghost'}" onclick="QC_STATE.format='long';renderQuickCreateModal()" style="flex:1; padding:6px 8px; font-size:11px;">🖥️ 16:9 Largo</button>
            </div>
          </div>

          <div class="field" style="margin:0;">
            <label style="font-size:11.5px; font-weight:700; color:var(--muted); margin-bottom:4px; display:block;">Voz</label>
            <select style="width:100%; padding:6px 8px; font-size:12px; border-radius:6px;" onchange="QC_STATE.voice=this.value">
              <option value="">edge-tts · Salomé 🇨🇴 (gratis ilimitado)</option>
              <option value="gemini" ${S.health.gemini ? '' : 'disabled'}>Gemini TTS · Fenrir 🎖️ (premium)</option>
            </select>
          </div>
        </div>

        <div style="display:flex; gap:10px; align-items:center;">
          <button type="button" class="btn primary" id="qc-submit-btn" onclick="executeQuickCreate()" style="flex:1; padding:12px 18px; font-size:14px; font-weight:800; border-radius:10px; background:linear-gradient(135deg, #10b981, #059669); box-shadow:0 4px 14px rgba(16,185,129,0.35);">
            🚀 Fabricar Video Ahora ($0.00)
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
    if (QC_STATE.destino) body.custom_workspace_path = QC_STATE.destino;  // INT-091: destino del usuario
    if (QC_STATE.voice) body.tts_provider = QC_STATE.voice;  // INT-092: voz elegida en el modal rápido
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

window.openQuickCreateModal = openQuickCreateModal;
window.startDirectCreation = openQuickCreateModal;
window.qcSwitchMode = qcSwitchMode;
window.executeQuickCreate = executeQuickCreate;
window.pickDestinoFolder = pickDestinoFolder;    // INT-091
window.qcPickDestino = qcPickDestino;            // INT-091


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
        <div style="display:flex; gap:6px; margin-top:8px; padding-top:8px; border-top:1px solid var(--border);">
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
    <div style="background:var(--soft); border:1px solid var(--border); border-radius:10px; padding:12px; margin-bottom:10px; transition:border-color 0.2s;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="font-weight:700; font-size:13px; color:var(--text)">${esc(h.badge)}</span>
          <span class="badge" style="background:rgba(99,102,241,0.2); color:var(--accent); font-size:10px; padding:2px 6px; border-radius:4px;">${esc(h.tag)}</span>
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
      <button type="button" class="btn ghost small" style="padding:4px 10px; font-size:11px; color:var(--accent); border:1px solid var(--border);" onclick="generateABVariantsModal('${esc((prodName || '').replace(/'/g, "\\'"))}')">
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



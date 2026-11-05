/* ============================================================
   app-projects.js — INT-088 · proyectos y pipeline
   Lista/árbol de nichos, crear/eliminar, job status (SSE),
   preflight, Flow, fábrica, publicar y hooks A/B.
   ============================================================ */
'use strict';

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
  if (!(await preflightGate())) return;  // INT-082: aviso antes de gastar recursos
  if (W.mode === 'nicho') {
    if (!W.nicho) return toast('Elige un nicho primero', 'err');
    try {
      const p = await api('/projects', { method: 'POST', body: {
        mode: 'nicho', niche_template: W.nicho, idea: W.nichoAdjust || null,
        auto_start: true,
        platforms: W.platforms.length ? W.platforms : ['youtube'],
        transitions: W.transitions, style_reference: W.styleReference,
        custom_workspace_path: W.destino || null }});  // INT-091: destino
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
    if (W.tpl) { body.template_id = W.tpl; if (W.nicheLabel) body.niche = W.nicheLabel; }  // INT-087: plantilla + nicho de marca
    if (W.destino) body.custom_workspace_path = W.destino;  // INT-091: destino del usuario
    if (audioPath) body.audio_path = audioPath;  // INT-080: puerta legitima (antes PATCH → 403)
    if (W.mode === 'idea') body.idea = W.idea;
    if (W.mode === 'script') { body.script = W.script; body.title = W.title || W.script.slice(0, 50); }
    if (W.mode === 'url') body.url = W.url;
    if (W.style === 'custom-studio') body.custom_style_prompt = W.custom;
    const p = await api('/projects', { method: 'POST', body });
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

/* ── INT-082 · preflight ligero antes de gastar recursos (mejora 3 del
   informe de revisión en vivo): si falta la voz (TTS) o ffmpeg, avisar ANTES
   de crear un proyecto que moriría a mitad del pipeline con guion e imágenes
   ya gastados. Resultado en caché 60s para no sondear en cada clic. ── */
S.preflight = { ts: 0, data: null };

async function preflightCrear(force) {
  const now = Date.now();
  if (!force && S.preflight.data && (now - S.preflight.ts) < 60000) return S.preflight.data;
  try {
    const d = await api('/doctor/preflight_creacion');
    S.preflight = { ts: now, data: d };
    return d;
  } catch { return null; }  // fail-open: si el endpoint no responde, la fábrica sigue
}

function preflightAvisos(d) {
  const lines = [];
  (d?.blockers || []).forEach(b => lines.push('❌ ' + b.detail + (b.hint ? ' → ' + b.hint : '')));
  (d?.warns || []).forEach(w => lines.push('⚠️ ' + w.detail + (w.hint ? ' → ' + w.hint : '')));
  return lines.join('\n');
}

async function preflightGate() {
  const d = await preflightCrear();
  if (!d || d.ok) return true;  // sin blockers (o endpoint caído) → producir
  return confirm('⚠️ Preflight de creación — faltan piezas críticas:\n\n' + preflightAvisos(d) +
    '\n\nEl proyecto quedaría mudo o fallaría a mitad del pipeline (se gastarían guion e imágenes).\n¿Continuar de todos modos?');
}

function renderPreflightBanner() {
  preflightCrear().then(d => {
    if (!d || d.ok) return;
    const host = document.querySelector('#view .wizard');
    if (!host || host.querySelector('.preflight-banner')) return;  // cambió de vista
    const body = preflightAvisos(d).split('\n').map(l => `<div>${esc(l)}</div>`).join('');
    host.insertAdjacentHTML('afterbegin',
      `<div class="card preflight-banner" style="border:1px solid rgba(245,158,11,.35);background:rgba(245,158,11,.08);margin-bottom:12px">
        <b>⚠️ Preflight de creación</b>
        <div style="margin-top:6px;font-size:13px;line-height:1.65">${body}</div>
      </div>`);
  });
}

async function startJob(pid) {
  if (guardDemo()) return;
  if (!(await preflightGate())) return;  // INT-082: aviso antes de gastar recursos
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
  nav('create');
  if (_NICHO_TPL_ID) {
    W.mode = 'nicho';
    W.step = 2;
    W.nicho = _NICHO_TPL_ID;
  } else {
    W.mode = 'idea';
    W.step = 1;
    if (_PROJ_NICHO) {
      W.idea = 'Video para el nicho ' + _PROJ_NICHO + ': ';
    }
  }
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
          ${p.status === 'ready' ? `<a class="btn" href="/api/projects/${p.id}/video?download=1" download>⬇️ Descargar MP4</a>` : ''}
          <a class="btn" href="/api/projects/${p.id}/export/flow.zip" download title="ZIP método completo: PROMPT MÁSTER (imágenes base + videos en cadena), script.json de tu extensión, método ChatGPT y guion">🌊 Flow (Método Completo)</a>
          <a class="btn" href="/api/projects/${p.id}/export/flow.zip?ai=1" download title="Igual que el anterior, pero Gemini (free tier) escribe los prompts en inglés con calidad editorial — tarda ~1 min">✨ Flow +IA</a>
          <a class="btn" href="/api/projects/${p.id}/export/flow.zip?format=artesano&ai=1" download title="Modo FABRICACIÓN DE PERSONAJE (tu método palma+pino): imagen ancla + secuencia iterativa para Flow + maestro de fabricación (REGLA ABSOLUTA + PASOS) + meta-prompt para re-editar el TXT en ChatGPT. Gemini extrae héroe/materiales/emblema — tarda ~1 min">🎭 Flow Artesano</a>
          <button class="btn ghost" onclick="copyFlowJson('${p.id}')" title="Copia el JSON para pegarlo en la extensión (plan B sin autodetección)">📋 Copiar JSON</button>
          <button class="btn" onclick="importFlow('${p.id}')" title="Importa el ZIP de carpetas Escena_XX que deja tu extensión en el disco">📥 Importar Escena_XX</button>
          ${scenes.length && scenes.every(sc => sc.image_path) ? `<button class="btn primary" onclick="renderFlow('${p.id}')" title="Ensambla el MP4 final con las imágenes reales de Flow (voz + subtítulos incluidos)">🎞️ Renderizar con Flow</button>` : ''}
          <button class="btn ghost" onclick="openSubtitleSwitcher({target:'project', project_id: '${p.id}'})" title="Cambiar preset visual de subtítulos">🎨 Subtítulos: <b style="margin-left:4px">${esc(((p.meta||{}).subtitle_style || 'shorts').toUpperCase())}</b></button>
          <a class="btn ghost" href="/api/projects/${p.id}/subtitles.srt" download>💬 Subtítulos SRT</a>
          <button class="btn ghost" onclick="downloadProjectScriptTxt('${p.id}')" title="Guarda el guion completo (narración + prompts de imagen) en un .txt en la carpeta que elijas de tu PC">💾 Guardar Guión (.txt)</button>
          <button class="btn" onclick="openProjectFolder('${p.id}')" title="Abre la carpeta REAL de este proyecto en el Explorador de Archivos de Windows (1 clic)">📂 Abrir Carpeta</button>
          <button class="btn danger" onclick="delProject('${p.id}')">🗑️</button>
        </div>
        ${p.error ? `<p style="color:var(--err);font-size:12.5px;margin-top:10px">⚠️ ${esc(p.error)}</p>` : ''}
      </div>
    </div>
    ${p.workspace ? renderWorkspacePanel(p.workspace) : ''}
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

/* ── AGENTE 2 · Visor visual del workspace (INT-086b) ─────────────────
   Muestra el estado real de las 5 carpetas canónicas del proyecto en
   disco + marca.json, sincronizado con GET /api/projects/{pid}. */
function renderWorkspacePanel(w) {
  const carpetas = [
    ['fuentes', '📁', 'fuentes/', 'Material de origen y referencias'],
    ['guion', '📝', 'guion/', 'guion.json · guion.md'],
    ['voz', '🎙️', 'voz/', 'Audios TTS generados'],
    ['clips', '🎬', 'clips/', 'Videos Flow / B-roll'],
    ['out', '📦', 'out/', 'Video final · subtítulos · portada'],
  ];
  const chip = ([key, emoji, nombre, desc]) => {
    const info = (w.carpetas || {})[key] || { n: 0, items: [] };
    const vacia = !info.n;
    const items = (info.items || []).slice(0, 3).join(' · ');
    return `<div class="card" style="margin:0;padding:10px 12px;border:1px solid ${vacia ? 'rgba(255,255,255,0.08)' : 'rgba(74,222,128,0.35)'};opacity:${vacia ? 0.55 : 1}" title="${esc(desc)}${items ? ' — ' + esc(items) : ''}">
      <div style="display:flex;align-items:center;gap:6px;font-size:13px"><span>${emoji}</span><b>${esc(nombre)}</b>
        <span style="margin-left:auto;font-size:11px;color:var(--muted);background:rgba(255,255,255,0.06);padding:1px 8px;border-radius:10px">${info.n} ${info.n === 1 ? 'archivo' : 'archivos'}</span></div>
      <div style="font-size:11px;color:var(--muted);margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${vacia ? 'vacía' : esc(items)}${info.n > 3 ? ' · …' : ''}</div>
    </div>`;
  };
  return `<div class="card" style="margin-top:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px">
      <div>
        <b style="font-size:15px;display:flex;align-items:center;gap:6px">🗂️ Espacio de trabajo
          <span style="font-size:11px;font-weight:400;color:var(--muted);background:rgba(255,255,255,0.06);padding:2px 8px;border-radius:10px">${esc(w.name || '')}</span>
          ${w.custom ? '<span style="font-size:11px;font-weight:700;color:#fbbf24;background:rgba(251,191,36,0.12);padding:2px 8px;border-radius:10px" title="Carpeta elegida por ti con el explorador de Windows (INT-091) — el pipeline la respeta absoluta">📂 tu carpeta</span>' : ''}
          ${w.existe ? '' : '<span style="font-size:11px;color:var(--muted)">· se crea al generar</span>'}</b>
        <p style="font-size:12px;color:var(--muted);margin-top:2px">Orden real en tu disco — 📂 Abrir Carpeta te lleva directo a esta vista en tu PC${w.legacy && w.legacy.existe && !w.existe ? ' (ahora mismo: almacén legacy output/)' : ''}</p>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <span style="font-size:12px;${w.marca ? 'color:var(--ok,#4ade80)' : 'color:var(--muted)'}" title="Identidad activa del canal: nicho, tono, voz y cierre">${w.marca ? '🏷️ marca.json activa' : '🏷️ marca.json —'}</span>
        <button class="btn small primary" onclick="openProjectFolder('${S.project.id}')">📂 Abrir Carpeta</button>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px">
      ${carpetas.map(chip).join('')}
    </div>
  </div>`;
}

async function openProjectFolder(pid) {
  toast('Abriendo carpeta del proyecto… 📂');
  try {
    const r = await api(`/projects/${pid}/open-folder`, { method: 'POST' });
    if (r.abierto) toast('📂 Carpeta abierta en tu PC: ' + (r.path || ''), 'ok');
    else toast('📁 ' + (r.path || 'carpeta del proyecto') + ' — ' + (r.metodo || 'sin explorador'), 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

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
  try {
    await api('/factory/ideas', { method: 'POST', body: { idea: v } });
    S.ideas = await api('/factory/ideas'); S.factory = await api('/factory'); renderFactory();
  } catch (e) { toast(e.message, 'err'); }
}

async function delIdea(ix) {
  try {
    const ideas = S.ideas.filter((_, i) => i !== ix);
    await fetch('/api/factory/ideas', { method: 'DELETE' });
    for (const i of ideas) await api('/factory/ideas', { method: 'POST', body: { idea: i } });
    S.ideas = await api('/factory/ideas'); S.factory = await api('/factory'); renderFactory();
  } catch (e) { toast(e.message, 'err'); }
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




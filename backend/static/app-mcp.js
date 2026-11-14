/* ============================================================
   app-mcp.js — INT-088 · panel MCP, SSO Google, Flow, NotebookLM
   INT-022 Connection Manager + sesión unificada Google (INT-025)
   + INT-023 Pipeline Orchestrator (polling ligero).
   ============================================================ */
'use strict';


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
  // U4 · el selector de nicho/cuaderno vive en la TARJETA PRINCIPAL
  // (ecoNichoNidHTML); esta tarjeta (Avanzado) queda para diagnóstico.
  return `<div class="mcp-svc">
    <div class="mcp-svc-head">
      <h3>${label}</h3>
      <span id="mcp-${svc}-badge">${mcpBadgeHTML('disconnected')}</span>
    </div>
    <p class="hintline">${hint}</p>
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
      <p class="hintline" id="pipe-block-reason" style="display:none"></p>
      <div class="mcp-row" id="pipe-force-wrap" style="display:none">
        <label class="hintline"><input type="checkbox" id="pipe-force-ph"> forzar placeholders en escenas fallidas (clip de color con su narración — el testeo nunca se deadlocka)</label>
      </div>
      <div id="pipe-progress"></div>
      <pre class="mcp-log" id="pipe-log" style="display:none"></pre>
    </div>
    <details class="mcp-adv" id="mcp-advanced">
      <summary>⚙️ Avanzado — tarjetas por servicio, reparar, pruebas y consola</summary>
      <p class="hintline">Todo lo de aquí es de diagnóstico: no hace falta
        abrirlo para usar el ecosistema. El volcado crudo de la consola
        vive SOLO aquí dentro.</p>
      ${mcpSvcHTML('google-flow', '🎬 Google Flow MCP',
        'Servidor tools/GoogleFlowMCP (Node). Con el login unificado se engancha POR CDP al Chrome del perfil ' +
        'compartido (<code>GOOGLE_PROFILE_GLOBAL</code>, puerto <code>FLOW_CDP_PORT</code>) y hereda la sesión — ' +
        'sin login separado. Sin el login global, usa su Chrome dedicado de siempre. Requiere ' +
        '<code>FLOW_MCP_ENABLED=1</code> en backend/.env.')}
      ${mcpSvcHTML('notebooklm', '📚 NotebookLM MCP',
        'Servidor <code>notebooklm-mcp-server</code> v0.1.15 (comandos <code>notebooklm-mcp</code> y ' +
        '<code>notebooklm-mcp-auth</code>; <code>uv tool list</code> lo confirma). Autenticación: ' +
        '«🔑 Login Google» + «📥 Capturar sesión» escribe el <code>storage_state.json</code> desde el ' +
        'MISMO login. El notebook se elige del DROPDOWN (se rellena solo al conectar y se ' +
        'recuerda por nicho); si lo dejas vacío, el pre-flight [0/3] intenta auto-descubrirlo y, si no puede, ' +
        'aborta con <code>PRE_FLIGHT_MISSING_NOTEBOOK_ID</code>.')}
      <div class="mcp-row btns" style="margin-top:14px">
        <button class="btn" onclick="mcpTest('')">🧪 Test Pipeline (ambos)</button>
        <button class="btn ghost" onclick="mcpRefresh()">🔄 Refrescar estado</button>
        <button class="btn ghost" onclick="gsessOpenWindow()">🪟 Abrir ventana de Chrome</button>
        <button class="btn ghost" onclick="gsessRepairProfile()">🔧 Reparar perfil</button>
      </div>
      <pre class="mcp-log" id="mcp-log">Estado en vivo…</pre>
    </details>
  </div>`;
  mcpRefresh();
  gsessRefresh(true);   // INT-025 · estado de la sesión unificada sin ruido
  mcpNichosCargar();    // U4 · nichos + cuaderno recordado
}

function mcpSaveId() { const el = $('#nblm-nid'); if (el) localStorage.setItem(NID_KEY, el.value.trim()); }
function mcpNid() { const el = $('#nblm-nid'); return el ? el.value.trim() : (localStorage.getItem(NID_KEY) || ''); }

/* ══ INT-071 · GOOGLE ONE-TAP HUB — «[G] Continuar con Google» ══════════
   Una tarjeta, DOS estados (sustituye los 5 botones técnicos de INT-025):
   · DESCONECTADO → botón oficial de Google: abre el Chrome del perfil
     compartido en el SELECTOR de cuentas (AccountChooser → Flow) + NotebookLM
     (POST /api/mcp/google-sso) y el backend vigila cada 2 s la cookie
     __Secure-1PSID/SID: al verla captura storage_state.json y conecta
     Flow + NotebookLM SOLO.
   · CONECTADO → panel de perfil: avatar + cuenta, pills verdes por servicio
     y acciones discretas (Ver mis Notebooks / Abrir Chrome / Cambiar cuenta).
   El login sigue siendo UNO para todo el ecosistema (perfil global CDP 9333). */

const G_LOGO_SVG = '<svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>';

let gsessPollTimer = null;

function mcpGsessHTML() {
  /* U2 · LA tarjeta principal: semáforo REAL por fila (fuente: U1
     /api/mcp/resumen) + botón primario «Conectar todo». */
  return `<div class="mcp-svc ghub" id="gsess-card">
    <div class="mcp-svc-head">
      <h3>${G_LOGO_SVG}<span>Ecosistema Google</span></h3>
      <span id="gsess-badge"><span class="mcp-badge mcp-b-gray">COMPROBANDO…</span></span>
    </div>
    <div id="gsess-profile"></div>
    <div id="gsess-rows"><p class="hintline">Comprobando el estado real del ecosistema…</p></div>
    <div class="mcp-row btns" style="margin-top:10px">
      <button class="btn" id="gsess-connect-all" onclick="gsessConnectAll()">🚀 Conectar todo</button>
      <button class="btn ghost" onclick="gsessRefresh()">🔄 Refrescar estado</button>
    </div>
    <p class="hintline" id="gsess-connectall-nota" style="display:none"></p>
    <p class="hintline" id="eco-aviso" style="display:none"></p>
    ${ecoNichoNidHTML()}
  </div>`;
}

/* U4 · selector de NICHO + CUADERNO en la tarjeta principal. Al conectar
   NotebookLM el desplegable se rellena solo (list-notebooks) y la
   elección se RECUERDA por nicho en el registro de nichos (Q4:
   POST /api/registro/nicho — UN cuaderno por nicho, nunca por
   historia). Los vacíos dicen qué hacer, no «conecta NotebookLM» si ya
   está conectado. */
const NICHOS_KEY = 'yta-eco-nicho';

function ecoNichoNidHTML() {
  return `<div class="mcp-row eco-nicho">
    <label for="nblm-nicho-sel">Nicho (recuerda tu cuaderno)</label>
    <select id="nblm-nicho-sel" onchange="mcpNichoChange(this.value)">
      <option value="">— sin nicho: la elección no se recuerda —</option>
    </select>
    <label for="nblm-nid-sel">Notebook activo</label>
    <select id="nblm-nid-sel" onchange="mcpPickNotebook(this.value)">
      <option value="">— conecta NotebookLM para listar los tuyos —</option>
      <option value="__manual__">✍️ Pegar ID manual…</option>
    </select>
    <input id="nblm-nid" type="text" placeholder="ej. 9a1b2c3d… (vacío = auto-descubrir en [0/3])"
           value="${esc(localStorage.getItem(NID_KEY) || '')}" oninput="mcpSaveId()"
           style="display:none; margin-top:6px">
    <div class="mcp-row btns">
      <button class="btn ghost" id="nblm-list-btn" onclick="mcpListNotebooks()">🔄 Listar / refrescar notebooks</button>
    </div>
  </div>`;
}

/* U4 · rellena el selector de nichos (GET /api/niches/templates) y
   restaura el nicho recordado + su cuaderno del registro. */
async function mcpNichosCargar() {
  const sel = $('#nblm-nicho-sel');
  if (!sel) return;
  try {
    const nbs = await api('/niches/templates');
    const cur = localStorage.getItem(NICHOS_KEY) || '';
    sel.innerHTML = '<option value="">— sin nicho: la elección no se recuerda —</option>' +
      (nbs || []).map(n =>
        `<option value="${esc(n.id)}">${esc((n.emoji ? n.emoji + ' ' : '') + (n.name || n.id))}</option>`).join('');
    if (cur) { sel.value = cur; if (sel.value === cur) await mcpNichoChange(cur, true); }
  } catch (e) { /* sin nichos registrados: el selector queda honesto */ }
}

/* U4 · al cambiar de nicho, carga su cuaderno recordado (si lo hay) y
   preselecciona en el desplegable; 404 = aún sin cuaderno (silencio). */
async function mcpNichoChange(nicho, silencioso) {
  nicho = (nicho || '').trim();
  localStorage.setItem(NICHOS_KEY, nicho);
  if (!nicho) return;
  try {
    const js = await api('/registro/nicho/' + encodeURIComponent(nicho));
    const nid = (js && js.notebook_id) || '';
    if (!nid) return;
    const el = $('#nblm-nid'), sel = $('#nblm-nid-sel');
    if (el) el.value = nid;
    mcpSaveId();
    if (sel) {
      const hit = Array.from(sel.options).find(o => o.value === nid);
      sel.value = hit ? nid : '__manual__';
      if (el) el.style.display = (sel.value === '__manual__') ? '' : 'none';
    }
    if (!silencioso) toast('Cuaderno del nicho cargado: ' + (js.nombre_cuaderno || nid), 'ok');
    gsessRefresh(true);
  } catch (e) { /* nicho sin cuaderno todavía — se elige al listar */ }
}

async function gsessStart() {
  const btn = $('#gsess-gbtn');
  const lbl = btn ? btn.querySelector('span') : null;
  if (btn) { btn.disabled = true; if (lbl) lbl.textContent = 'Abriendo Google…'; }
  try {
    // Abre directamente desde el navegador nativo (cero bloqueos del SO)
    window.open('https://flow.google.com', '_blank');
    await api('/mcp/google-sso', { method: 'POST', body: {} });
    toast('Pestaña de Google Flow abierta en tu navegador. Sincronizando sesión...', 'info');
    await gsessRefresh(true);
    await mcpRefresh(true);
  } catch (e) {
    toast('Continuar con Google: ' + e.message, 'err');
  } finally {
    if (btn) { btn.disabled = false; if (lbl) lbl.textContent = 'Continuar con Google'; }
  }
}

function gsessNameFromEmail(email) {
  const local = String(email || '').split('@')[0] || '';
  const name = local.replace(/[._+-]+/g, ' ').trim()
    .replace(/\b\w/g, c => c.toUpperCase());
  return name || 'Cuenta Google';
}

function gsessSvcState(s) { return s && s.state === 'connected'; }

/* U2 · fila del semáforo REAL: cada fila toma su estado de U1
   (/api/mcp/resumen) — nada de deducciones locales que puedan mentir. */
function ecoRowHTML(etiqueta, pieza) {
  const p = pieza || { ok: false, detalle: 'sin dato', accion_siguiente: '' };
  return `<div class="eco-row ${p.ok ? 'eco-ok' : 'eco-ko'}">` +
    `<div class="eco-row-head"><span class="eco-dot">${p.ok ? '🟢' : '🔴'}</span>` +
    `<b>${esc(etiqueta)}</b><span class="hintline">${esc(p.detalle || '')}</span></div>` +
    (p.accion_siguiente ? `<p class="eco-accion">→ ${esc(p.accion_siguiente)}</p>` : '') +
    `</div>`;
}

/* U2/W2 · botón primario: 1 clic → POST /api/mcp/connect-all-google.
   Muestra el resultado REAL de la respuesta: si chrome_up es false,
   mensaje de error con la acción siguiente («Chrome no abrió: pulsa
   «Abrir ventana de Chrome» en Avanzado»); NUNCA un «listo» genérico. */
async function gsessConnectAll() {
  const btn = $('#gsess-connect-all');
  const chromeOk = !!(S.eco && S.eco.piezas && S.eco.piezas.chrome &&
                      S.eco.piezas.chrome.ok);
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Conectando…'; }
  if (!chromeOk) toast('Se va a abrir una ventana de Chrome: INICIA SESIÓN con tu cuenta de Google en la ventana que se abre.', 'info');
  try {
    const res = await api('/mcp/connect-all-google', { method: 'POST', body: {} });
    const nota = $('#gsess-connectall-nota');
    if (!res || res.chrome_up === false) {
      const errDetalle = (res && res.chrome_error) ? (' (' + res.chrome_error + ')') : '';
      if (nota) {
        nota.style.display = '';
        // X4: el detalle del error va en el texto VISIBLE, no solo en el toast:
        // «Chrome no abrió (no respondió en el puerto CDP 9333 tras 30 s): pulsa …»
        nota.textContent = 'Chrome no abrió' + errDetalle + ': pulsa «Abrir ventana de Chrome» en Avanzado.';
      }
      toast('Chrome no abrió: pulsa «Abrir ventana de Chrome» en Avanzado' + errDetalle, 'err');
    } else {
      if (nota) {
        if (!chromeOk) {
          nota.style.display = '';
          nota.textContent = 'Chrome estaba apagado: inicia sesión en la ventana que se abrió y pulsa «Refrescar estado».';
        } else {
          nota.style.display = 'none';
        }
      }
      if (res.ok) {
        toast('Ecosistema Google conectado correctamente ✅', 'ok');
      } else {
        toast(chromeOk ? 'Chrome activo pero servicios pendientes: verifica sesión o pulsa «Refrescar estado».' :
          'Chrome se abrió: si te pide login, INICIA SESIÓN en esa ventana y pulsa «Refrescar estado».', 'info');
      }
    }
  } catch (e) {
    // X4: si la llamada misma falla (red/backend), el detalle también queda visible
    const nota = $('#gsess-connectall-nota');
    if (nota) {
      nota.style.display = '';
      nota.textContent = 'Conectar todo falló (' + e.message + '). Revisa el backend y pulsa «Refrescar estado».';
    }
    toast('Conectar todo: ' + e.message, 'err');
  }
  finally { if (btn) { btn.disabled = false; btn.textContent = '🚀 Conectar todo'; } }
  await gsessRefresh(true);
  await mcpRefresh(true);
}

async function gsessRepairProfile() {
  try {
    const res = await api('/mcp/repair-profile', { method: 'POST', body: {} });
    const acts = (res.actions || []).length ? res.actions.join(', ') : 'perfil en estado óptimo';
    toast('Perfil saneado ✅: ' + acts, 'ok');
  } catch (e) { toast('Reparar perfil: ' + e.message, 'err'); }
}

/* INT-071-fix: «Abrir Ventana de Chrome» — fuerza ventana interactiva visible.
   Si hay un Chrome fantasma (proceso vivo sin MainWindowHandle), el endpoint
   lo purga con taskkill /F, borra los Singleton* y relanza limpia con foco. */
async function gsessOpenWindow() {
  try {
    const res = await api('/mcp/google-sso/launch', {
      method: 'POST',
      body: { force_window: true }
    });
    if (res && res.ok) {
      const extra = res.relaunched
        ? 'instancia fantasma purgada y ventana relanzada'
        : 'ventana reenviada a la instancia viva';
      toast('Ventana de Chrome lanzada 🪟 (' + extra + ')', 'ok');
      gsessRefresh();
    } else {
      toast('No se pudo abrir la ventana de Chrome', 'err');
    }
  } catch (e) { toast('Abrir ventana: ' + e.message, 'err'); }
}

/* U2 · el badge verde del ecosistema SOLO aparece si U1 confirma
   todo_conectado (TODAS las piezas ok). Con cualquier pieza caída se
   pinta INCOMPLETO con el contador real — fin del estado mentiroso. */
function gsessApply(eco, sso) {
  const badge = $('#gsess-badge'), rows = $('#gsess-rows');
  if (!rows) return;
  eco = eco || {}; sso = sso || {};
  const piezas = eco.piezas || {};
  const nOk = Object.values(piezas).filter(p => p && p.ok).length;
  if (badge) {
    badge.innerHTML = eco.todo_conectado
      ? '<span class="mcp-badge mcp-b-green">ECOSISTEMA CONECTADO</span>'
      : `<span class="mcp-badge mcp-b-gray">ECOSISTEMA INCOMPLETO · ${nOk}/4</span>`;
  }
  const esperando = (sso.sso_phase === 'watching' || sso.sso_phase === 'connecting')
    ? `<p class="hintline">⏳ Esperando tu inicio de sesión en la ventana de Chrome — conectamos al ver la sesión (vigilancia cada ${(sso.poll_s || 2)} s)…</p>`
    : '';
  const cuaderno = piezas.cuaderno || {};
  rows.innerHTML = esperando +
    ecoRowHTML('Chrome (CDP 9333)', piezas.chrome) +
    ecoRowHTML('Google Flow', piezas.flow) +
    ecoRowHTML('NotebookLM', piezas.notebooklm) +
    `<p class="hintline eco-cuaderno">${cuaderno.ok ? '🟢' : '🔴'} Cuaderno: ${esc(cuaderno.detalle || 'sin dato')}` +
    (cuaderno.accion_siguiente ? ` — ${esc(cuaderno.accion_siguiente)}` : '') + `</p>`;
  const prof = $('#gsess-profile');
  if (prof) {
    const acc = sso.account || {};
    if (acc.email) {
      prof.innerHTML = `<div class="ghub-profile ghub-mini">
        <div class="ghub-id">
          <div class="ghub-name">${esc(acc.name || gsessNameFromEmail(acc.email))}</div>
          <div class="ghub-email">${esc(acc.email)}</div>
        </div>
        <div class="ghub-actions">
          <button class="btn ghost" onclick="gsessOpenChrome()">🌐 Abrir Chrome</button>
          <button class="btn ghost" onclick="gsessLogout()">🚪 Cambiar cuenta</button>
        </div>
      </div>`;
    } else if (!esperando) {
      prof.innerHTML = `<button class="gbtn" id="gsess-gbtn" onclick="gsessStart()">${G_LOGO_SVG}<span>Continuar con Google</span></button>`;
    } else prof.innerHTML = '';
  }
  if (sso.sso_phase === 'watching' || sso.sso_phase === 'connecting') gsessStartPoll();
  else gsessStopPoll();
}

/* Polling del Hub: 2 s mientras el backend vigila el login; sin poll en
   reposo (el estado se refresca al abrir la pestaña y tras cada acción). */
function gsessStartPoll() {
  if (gsessPollTimer) return;
  gsessPollTimer = setInterval(() => {
    if (!$('#gsess-body')) { gsessStopPoll(); return; }   // salimos de #mcp
    gsessRefresh(true);
  }, 2000);
}
function gsessStopPoll() {
  if (gsessPollTimer) { clearInterval(gsessPollTimer); gsessPollTimer = null; }
}

/* U2 · fuente de verdad = U1: el semáforo del ecosistema sale SIEMPRE
   de /api/mcp/resumen (agregador solo lectura); el estado SSO aporta
   solo el perfil (cuenta) y la fase de vigilancia del login. */
async function gsessRefresh(silent) {
  try {
    const nid = mcpNid();
    const nicho = (localStorage.getItem(NICHOS_KEY) || '').trim();
    const q = new URLSearchParams();
    if (nicho) q.set('nicho_id', nicho);
    if (nid) q.set('notebook_id', nid);
    const qs = q.toString() ? ('?' + q.toString()) : '';
    const [eco, sso] = await Promise.all([
      qs ? api('/mcp/resumen' + qs) : api('/mcp/resumen'),
      api('/mcp/google-sso/status').catch(() => ({})),
    ]);
    S.eco = eco;
    gsessApply(eco, sso);
    pipeGateApply();      // U5 · habilita/deshabilita Run con motivo
    mcpRefresh(true);
    return eco;
  } catch (e) { if (!silent) toast('Estado ecosistema: ' + e.message, 'err'); return null; }
}

async function gsessOpenNotebooks() {
  if (S.mcp && (S.mcp.notebooklm || {}).state === 'connected') {
    mcpListNotebooks({});
    const el = $('#nblm-nid-sel');
    if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.focus(); }
    toast('Notebooks cargados en el desplegable de NotebookLM 📚', 'ok');
  } else {
    toast('NotebookLM MCP aún no está conectado — revisa su tarjeta más abajo', 'err');
    await gsessRefresh();
  }
}

async function gsessOpenChrome() {
  try {
    const js = await api('/mcp/launch-auth-browser', { method: 'POST', body: {} });
    toast(js.already_up
      ? 'El Chrome del ecosistema ya estaba abierto ✅'
      : 'Chrome abierto con tu sesión 🌐 (' + (js.pages || []).length + ' pestañas)', 'ok');
  } catch (e) { toast('Abrir Chrome: ' + e.message, 'err'); }
}

async function gsessLogout() {
  const btns = document.querySelectorAll('.ghub-actions button');
  btns.forEach(b => { b.disabled = true; });
  try {
    const res = await api('/mcp/google-sso/logout', { method: 'POST', body: {} });
    toast('Ecosistema desconectado: ' + (res.actions || []).join(' · '), 'ok');
    await gsessRefresh(true);
    await mcpRefresh(true);
  } catch (e) { toast('Cambiar cuenta: ' + e.message, 'err'); }
  finally { btns.forEach(b => { b.disabled = false; }); }
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
  // U4 · UN cuaderno por nicho: se guarda en el registro (Q4) si hay
  // nicho elegido; sin nicho no hay memoria (se avisa con qué hacer).
  const nicho = (localStorage.getItem(NICHOS_KEY) || '').trim();
  const titulo = (sel && sel.selectedIndex >= 0)
    ? String(sel.options[sel.selectedIndex].text.split(' · ')[0] || '') : '';
  if (nicho) {
    api('/registro/nicho', { method: 'POST', body: {
      nicho_id: nicho, notebook_id: id,
      nombre_cuaderno: titulo || ('Cuaderno del nicho ' + nicho) } })
      .then(() => {
        toast('Notebook fijado ✅ y recordado para el nicho «' + nicho + '» — ya puedes lanzar el pipeline', 'ok');
        gsessRefresh(true);
      })
      .catch(e => {
        toast('Notebook fijado ✅ (no se pudo recordar por nicho: ' + e.message + ')', 'info');
        gsessRefresh(true);
      });
  } else {
    toast('Notebook fijado ✅ ' + id.slice(0, 8) + '… — elige un nicho arriba para que se recuerde');
    gsessRefresh(true);
  }
}

/* U3 · traducción HUMANA de avisos conocidos de la consola (p. ej.
   «fastmcp desactualizado»): una línea que dice que NO afecta. El
   volcado crudo sigue SOLO en Avanzado. */
function avisoHumanoDe(services) {
  const joined = Object.values(services || {})
    .map(v => ((v && v.stderr_tail) || []).join('\n')).join('\n');
  if (/fastmcp/i.test(joined))
    return 'ℹ Aviso conocido de FastMCP (framework interno del servidor MCP): ' +
           'aunque la consola lo marque desactualizado, NO afecta a tus ' +
           'herramientas ni al pipeline.';
  return '';
}

function mcpZoneHTML(svc, st) {
  let h = '';
  if (st.auth_detail) h += `<p class="hintline">🔐 ${esc(st.auth_detail)}</p>`;
  if (st.last_error) h += `<p class="hintline" style="color:var(--err)">⚠ ${esc(st.last_error)}</p>`;
  if (st.server_info && st.server_info.name) {
    if (svc === 'notebooklm') {
      // U6 · honestidad de paquete: el server real es notebooklm-mcp-server
      // v0.1.15 (comandos notebooklm-mcp / notebooklm-mcp-auth); la versión
      // de server_info es del FRAMEWORK FastMCP — nunca se presenta como
      // versión del paquete.
      h += `<p class="hintline">Paquete: <b>notebooklm-mcp-server v0.1.15</b>` +
           ` (comandos <code>notebooklm-mcp</code> · <code>notebooklm-mcp-auth</code>)` +
           (st.pid ? ` · PID ${st.pid} · ${st.uptime_s || 0}s` : '') + `</p>`;
      h += `<p class="hintline">Versión de server_info: ${esc(st.server_info.version || '?')} ` +
           `(framework <b>FastMCP</b>, NO la versión del paquete)</p>`;
    } else {
      h += `<p class="hintline">Servidor: <b>${esc(st.server_info.name)}</b> v${esc(st.server_info.version || '?')}` +
           (st.pid ? ` · PID ${st.pid} · ${st.uptime_s || 0}s` : '') + `</p>`;
    }
  }
  if (st.tools && st.tools.length)
    h += `<details class="mcp-tools"><summary>🔧 ${st.tools.length} tools expuestas</summary><ul>` +
         st.tools.map(t => `<li><b>${esc(t.name)}</b>${t.description ? ' — ' + esc(t.description) : ''}</li>`).join('') +
         `</ul></details>`;
  if (st.hint) h += `<p class="hintline" style="color:var(--warn)">ℹ ${esc(st.hint)}</p>`;
  if (st.browser_up !== undefined)
    h += `<p class="hintline">Chrome CDP (${st.cdp_port || ''}): ${st.browser_up ? '✅ arriba' : '❌ no responde — abre el Chrome dedicado'}</p>`;
  if (st.notebook_id_valid !== undefined && st.notebook_id)
    h += `<p class="hintline">notebookId «${esc(st.notebook_id)}»: ${st.notebook_id_valid ? '✅ válido' : '❌ inválido'}</p>`;
  if (st.stderr_tail && st.stderr_tail.length) {
    const humano = avisoHumanoDe({ solo: st });
    if (humano) h += `<p class="hintline">${esc(humano)}</p>`;
    // volcado crudo: SOLO visible aquí (la zona vive dentro de «Avanzado»)
    h += `<pre class="mcp-log">${esc(st.stderr_tail.join('\n'))}</pre>`;
  }
  return h || '<p class="hintline">Sin información adicional.</p>';
}

function mcpApplyStatus(services) {
  S.mcp = services || {};
  ['google-flow', 'notebooklm'].forEach(svc => {
    const st = S.mcp[svc] || {};
    const badge = $('#mcp-' + svc + '-badge');
    if (badge) badge.innerHTML = mcpBadgeHTML(st.state || 'disconnected');
    const zone = $('#mcp-' + svc + '-zone');
    if (zone) zone.innerHTML = mcpZoneHTML(svc, st);
    const btnC = $('#mcp-' + svc + '-connect'), btnD = $('#mcp-' + svc + '-disc');
    if (btnC) { btnC.disabled = st.state === 'connecting'; btnC.textContent = st.state === 'connecting' ? '⏳ Conectando…' : '🔌 Conectar'; }
    if (btnD) btnD.disabled = st.state === 'connecting' || st.state === 'disconnected';
  });
  // U3 · aviso conocido (p. ej. FastMCP) como línea humana en la tarjeta
  // principal — NUNCA el volcado crudo fuera de «Avanzado».
  const aviso = avisoHumanoDe(services);
  const elAviso = $('#eco-aviso');
  if (elAviso) { elAviso.style.display = aviso ? '' : 'none'; if (aviso) elAviso.textContent = aviso; }
  // U4 · el texto del vacío dice qué hacer: si NotebookLM ya está
  // conectado, NO puede seguir diciendo «conecta NotebookLM».
  const op0 = ($('#nblm-nid-sel') || {}).querySelector ?
    $('#nblm-nid-sel').querySelector('option[value=""]') : null;
  if (op0 && op0.textContent !== '— elige notebook —') {
    op0.textContent = (S.mcp && (S.mcp.notebooklm || {}).state === 'connected')
      ? 'NotebookLM conectado: pulsa «🔄 Listar / refrescar notebooks» para cargar tus cuadernos'
      : '— conecta NotebookLM para listar los tuyos —';
  }
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
  gsessRefresh(true);
}

async function mcpDisconnect(svc) {
  try { await api('/mcp/disconnect', { method: 'POST', body: { service: svc } }); toast('Desconectado'); }
  catch (e) { toast('Desconexión: ' + e.message, 'err'); }
  mcpRefresh(true);
  gsessRefresh(true);
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

/* U5 · «Run Full Pipeline» deshabilitado mientras U1 diga
   listo_para_pipeline=false, mostrando el motivo EXACTO (pieza rota +
   detalle). Sin datos de U1 NO bloquea por adivinanza; si la corrida
   está activa, sigue bloqueado como siempre. */
function pipeGateApply() {
  const btn = $('#pipe-run-btn');
  const motivo = $('#pipe-block-reason');
  if (!btn) return;
  const corriendo = pipeActive(S.pipeRun);
  const eco = S.eco || {};
  if (eco.listo_para_pipeline === false) {
    btn.disabled = true;
    btn.title = 'Pendiente: ' + (eco.siguiente_paso || 'ecosistema incompleto');
    if (motivo) {
      const rota = Object.entries(eco.piezas || {}).find(([, p]) => p && !p.ok);
      motivo.textContent = '⛔ Run Full Pipeline bloqueado — ' +
        (rota ? rota[0] + ': ' + rota[1].detalle
              : (eco.siguiente_paso || 'ecosistema incompleto'));
      motivo.style.display = '';
    }
    return;
  }
  if (motivo) { motivo.style.display = 'none'; motivo.textContent = ''; }
  btn.disabled = corriendo;   // sin bloqueo de U1: como siempre
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
  pipeGateApply();          // U5 · la última palabra la tiene U1
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
  // U5 · defensa en profundidad: si U1 dice que NO está listo, no se
  // lanza (antes fallaba después del clic).
  if (S.eco && S.eco.listo_para_pipeline === false) {
    toast('No listo: ' + (S.eco.siguiente_paso || 'ecosistema incompleto'), 'err');
    pipeGateApply();
    return;
  }
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



/* ============================================================
   app-player.js — INT-088 · reproducción inline y medios
   Clipper (INT-044), reproducción de audio de escenas, hoja de
   contacto/video modal y animación de avatares (INT-066).
   ============================================================ */
'use strict';

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
      try {
        await api(`/projects/${S.project.id}/reorder`, { method: 'POST', body: { scene_ids: ids } });
      } catch (e) { toast('Error reordenando: ' + e.message, 'err'); }
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
        broll: broll,
        auto_emojis: autoEmojis,   // INT-080: los toggles existían pero nunca viajaban
        progress_bar: progressBar
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


/* ── INT-066: LivePortrait & MuseTalk Motion Handlers ── */
async function animateAvatarLivePortrait(aid, btn) {
  const orig = btn.innerHTML;
  btn.innerHTML = '⏳ Animando...';
  btn.disabled = true;
  try {
    const res = await api(`/avatars/${aid}/animate-liveportrait`, {
      body: { duration_sec: 4.0 }
    });
    if (res && res.ok && res.video_url) {
      toast('¡Avatar animado con éxito con LivePortrait!', 'success');
      showVideoModal(res.video_url, '🎭 Animación Facial LivePortrait');
    } else {
      throw new Error('Error al animar avatar');
    }
  } catch (err) {
    toast('Error LivePortrait: ' + err.message, 'error');
  } finally {
    btn.innerHTML = orig;
    btn.disabled = false;
  }
}

async function lipsyncAvatarMuseTalk(aid) {
  const text = prompt('Escribe la frase que dirá el avatar con sincronización labial MuseTalk:', 'Hola, soy tu presentador virtual y este video fue generado con inteligencia artificial a cero costo.');
  if (!text) return;
  toast('Sintetizando voz y sincronización labial MuseTalk...', 'info');
  try {
    const res = await api(`/avatars/${aid}/lipsync-musetalk`, {
      body: { text }
    });
    if (res && res.ok && res.video_url) {
      toast('¡Sincronización labial MuseTalk completada!', 'success');
      showVideoModal(res.video_url, '👄 Sincronización Labial MuseTalk');
    } else {
      throw new Error('Error en sincronización labial');
    }
  } catch (err) {
    toast('Error MuseTalk: ' + err.message, 'error');
  }
}

function showVideoModal(videoUrl, title) {
  const root = document.getElementById('overlay-root');
  if (!root) return;
  root.innerHTML = `
    <div class="overlay" onclick="if(event.target===this)closeOverlay()">
      <div class="qc-box card" style="max-width:540px; text-align:center; padding:18px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <h3 style="margin:0; font-size:16px;">${esc(title)}</h3>
          <button class="modal-x" onclick="closeOverlay()" style="background:transparent; border:none; color:var(--muted); font-size:18px; cursor:pointer;">✕</button>
        </div>
        <div style="aspect-ratio:1/1; max-width:380px; margin:0 auto; overflow:hidden; border-radius:12px; background:#000; box-shadow:0 10px 30px rgba(0,0,0,0.5);">
          <video src="${videoUrl}?t=${Date.now()}" controls autoplay loop style="width:100%; height:100%; object-fit:cover;"></video>
        </div>
        <div style="margin-top:14px;">
          <button class="btn primary small" onclick="closeOverlay()">Cerrar</button>
        </div>
      </div>
    </div>
  `;
}

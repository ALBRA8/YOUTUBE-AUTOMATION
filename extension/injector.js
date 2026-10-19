/* =============================================================================
 * injector.js — Inyector de Red e Interceptor tRPC (manual 3.5)
 * MUNDO: MAIN (contexto nativo de Google Labs) · run_at: document_start
 * -----------------------------------------------------------------------------
 * Google Labs genera imagenes/videos de forma asincrona y no devuelve la URL
 * al DOM de inmediato. Este script:
 *   1. Parchea window.fetch filtrando URLs con /fx/api/trpc/ o batchGenerate*.
 *   2. Parchea XMLHttpRequest para las mismas rutas.
 *   3. Decodifica el cuerpo: JSON plano o NDJSON (lineas separadas por \n).
 *   4. Extrae metadatos (batchId, workflowId, mediaId, prompt).
 *   5. Emite window.postMessage({ type: 'FLOW_BATCH_RESPONSE', data }, '*').
 *   6. [observability v1.1] Los ERRORES HTTP (4xx/5xx) y los fallos de red
 *      de las MISMAS rutas ya NO se descartan: se capturan como EVIDENCIA
 *      CRUDA read-only (status, statusText, ok, URL sin query, método,
 *      timestamp, cuerpo con redacción de secretos y truncado determinista)
 *      y se emiten por FLOW_NETWORK_EVIDENCE. La clasificación de la causa
 *      vive en el backend (flow_adaptation); aquí solo se OBSERVA.
 *   7. [flow-start-frame F1] Observación PASIVA de batchexecute (Google
 *      Flow): se identifican de forma segura los rpcids eb1hJf / WuwhI /
 *      jwpduf / as29s y se extrae SOLO estructura (rpcid, operación,
 *      videoModelKey, aspectRatio, count, presencia de Start Frame mediaId,
 *      identificadores no sensibles de job/workflow, estados). Los mediaId
 *      NUNCA se guardan en crudo: huella determinista de 12 hex (fp) para
 *      correlación. CERO mutación de requests/responses; los cuerpos de
 *      request solo se LEEN si son string/URLSearchParams/FormData (un
 *      ReadableStream jamás se consume); se emite FLOW_RPC_EVIDENCE por el
 *      mismo canal postMessage existente. NO persiste en backend.
 *   8. [flow-start-frame F2] parser ANIDADO de MEDIA_GENERATION_SETTINGS:
 *      cadena real body → f.req → JSON externo → envelope RPC → MEDIA_
 *      GENERATION_SETTINGS cuyo VAL es un STRING con JSON dentro (se
 *      requiere JSON.parse de segundo nivel; F1 leía solo la externa →
 *      nulls). Extracción: videoModelKey, aspectRatio (string O número),
 *      count, structuredPrompt (solo presencia), Start Frame por estructura
 *      (inputFrames.firstFrame / firstFrame / startImage histórico) y
 *      cropCoordinates (whitelist numérica). VAL malformado → evidencia
 *      parcial diagnóstica (settingsParseError); observer JAMÁS roto.
 * La pagina NO se ve afectada: siempre se lee desde resp.clone(); el
 * interceptor es silencioso y jamás altera la respuesta ni lanza.
 * ========================================================================== */
(function () {
  'use strict';
  if (window.__FLOW_EXT_INJECTOR__) return;
  window.__FLOW_EXT_INJECTOR__ = true;

  const URL_HINTS = ['/fx/api/trpc/', 'batchGenerateImages', 'batchGenerateVideo', '/fx/api/', 'batchexecute']; // [flow-start-frame F1] batchexecute es pasivo y filtrado por rpcid
  const MARKER_RE = /batchId|workflowId|mediaId|batchGenerate|"media"|workflows|fifeUrl/i;
  const MAX_BODY = 8 * 1024 * 1024; // 8MB de seguridad
  const EVIDENCE_BODY_MAX = 1200;   // [observability v1.1] techo del cuerpo capturado (truncado determinista)

  /* ---- [flow-start-frame F1] constantes de observación batchexecute ---- */
  const RPC_IDS = ['eb1hJf', 'WuwhI', 'jwpduf', 'as29s'];
  const RPC_IDS_RE = /^(eb1hJf|WuwhI|jwpduf|as29s)$/;
  const RPC_MIRROR_MAX = 30;   // techo del espejo window.__FLOW_RPC_OBS__
  const RPC_BODY_MAX = 524288; // techo de lectura del cuerpo de request (512KB)
  const RPC_DFS_NODES = 500;   // techo de nodos visitados por DFS
  const RPC_DFS_DEPTH = 8;     // techo de profundidad por DFS
  const RPC_ID_VAL_MAX = 80;   // techo de valor de identificador capturado
  const RPC_IDS_MAX = 16;      // techo de identificadores por evento
  const RPC_MEDIA_FP_MAX = 8;  // techo de huellas mediaId por evento
  /* llaves de identificadores NO sensibles (job/workflow) permitidas */
  const RPC_ID_KEYS = ['workflowId', 'batchId', 'videoId', 'jobId', 'projectId', 'toolId'];
  /* llaves de ESTADO permitidas (solo texto corto; sin semántica inventada) */
  const RPC_STATE_KEYS = ['status', 'state', 'generationStatus'];

  function emit(type, data) {
    try {
      window.postMessage({ type: type || 'FLOW_BATCH_RESPONSE', source: 'flow-ext-injector', data: data }, '*');
    } catch (_) { /* nunca romper la pagina */ }
  }

  /* ---- [observability v1.1] utilidades de evidencia ------------------- */
  /* Redacción DETERMINISTA de secretos: jamás se capturan cookies, tokens
   * de autorización, API keys ni passwords. Solo patrones explícitos. */
  function redactSecrets(text) {
    let t = String(text == null ? '' : text);
    try {
      t = t.replace(/(authorization|api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|id[_-]?token|auth[_-]?token|secret|password|set-cookie|cookie|x-csrf-token|csrf[_-]?token)\s*['\"=:\s]+[^\s'\",;&}]{4,}/gi, '$1=[REDACTED]');
      t = t.replace(/Bearer\s+[A-Za-z0-9\-._~+/=]{8,}/gi, 'Bearer [REDACTED]');
    } catch (_) { /* jamás lanzar */ }
    return t;
  }

  /* Truncado DETERMINISTA: misma entrada → misma salida, con marca de
   * longitud original (tamaño total auditable). */
  function truncateDeterministic(text, max) {
    const t = String(text == null ? '' : text);
    if (t.length <= max) return { text: t, truncated: false, total: t.length };
    return { text: t.slice(0, max) + '[TRUNCATED]', truncated: true, total: t.length };
  }

  /* Categoría del endpoint (evidencia, sin inventar semántica). */
  function endpointCategory(url) {
    const u = String(url || '');
    if (u.indexOf('batchexecute') !== -1) return 'batchexecute';
    if (u.indexOf('/fx/api/trpc/') !== -1) return 'trpc';
    if (u.indexOf('batchGenerateImages') !== -1) return 'batchGenerateImages';
    if (u.indexOf('batchGenerateVideo') !== -1) return 'batchGenerateVideo';
    if (u.indexOf('/fx/api/') !== -1) return 'fx_api';
    return 'other';
  }

  /* ========================================================================
   * [flow-start-frame F1] observación PASIVA de batchexecute.
   * SOLO lectura. Jamás muta requests/responses. rpcids distintos de
   * eb1hJf/WuwhI/jwpduf/as29s se IGNORAN en silencio (cero ruido, cero
   * riesgo). Los mediaId jamás se guardan en crudo: huella determinista.
   * ====================================================================== */

  /* Huella DETERMINISTA de 12 hex (FNV-1a doble): permite correlacionar el
   * mismo mediaId entre eventos SIN almacenar el valor crudo. */
  function fpHash(s) {
    let h1 = 0x811c9dc5, h2 = 0x01000193;
    const str = String(s == null ? '' : s);
    for (let i = 0; i < str.length; i++) {
      const c = str.charCodeAt(i);
      h1 = ((h1 ^ c) * 16777619) >>> 0;
      h2 = ((h2 ^ (c + i + 1)) * 2246822519) >>> 0;
    }
    return ('00000000' + h1.toString(16)).slice(-8) + ('0000' + (h2 & 0xffff).toString(16)).slice(-4);
  }

  function mediaFp(v) {
    if (typeof v !== 'string' || !v) return null;
    return { present: true, fp: fpHash(v) };
  }

  /* rpcids declarados en la query de la URL (?rpcids=WuwhI&...) */
  function rpcIdsFromUrl(url) {
    try {
      const q = String(url || '').split('?')[1] || '';
      const m = q.match(/(?:^|&)rpcids=([^&]*)/);
      if (!m) return [];
      return decodeURIComponent(m[1] || '').split(',').map((s) => s.trim()).filter(Boolean);
    } catch (_) { return []; }
  }

  /* Lectura SEGURA del cuerpo de request: solo tipos inmutables/síncronos.
   * Un ReadableStream (o cualquier otro tipo) NUNCA se consume: la pasividad
   * manda — si el cuerpo no se puede leer sin riesgo, no se lee. */
  function rpcBodyText(body) {
    try {
      if (typeof body === 'string') return body.slice(0, RPC_BODY_MAX);
      if (!body || typeof body !== 'object') return null;
      if (typeof URLSearchParams !== 'undefined' && body instanceof URLSearchParams) {
        return body.toString().slice(0, RPC_BODY_MAX);
      }
      if (typeof FormData !== 'undefined' && typeof body.get === 'function' && typeof body.entries === 'function') {
        try {
          const v = body.get('f.req');
          if (typeof v === 'string') return v.slice(0, RPC_BODY_MAX);
        } catch (_) { /* FormData sin f.req */ }
        return null;
      }
      return null;
    } catch (_) { return null; }
  }

  /* Extrae del cuerpo los envelopes f.req: [["<rpcid>","<payload>",...],...]
   * Acepta cuerpo urlencoded (f.req=...) o el JSON crudo del envelope. */
  function parseFreqEntries(bodyText) {
    const out = [];
    try {
      const t = String(bodyText || '');
      if (!t) return out;
      let freqJson = null;
      const eq = t.indexOf('f.req=');
      if (eq !== -1) {
        let seg = '';
        for (const piece of t.slice(eq + 6).split('&')) { seg = piece; break; }
        try { freqJson = decodeURIComponent(seg.replace(/\+/g, ' ')); } catch (_) { freqJson = seg; }
      } else if (/^\s*\[/.test(t)) {
        freqJson = t;
      }
      if (!freqJson) return out;
      const parsed = JSON.parse(freqJson);
      /* DFS acotado: cualquier array cuyo [0] sea un rpcid conocido es una
       * entrada; el payload (si existe) es [1] como STRING doble-codificada. */
      let nodes = 0;
      (function dig(node, depth) {
        if (!Array.isArray(node) || depth > 6 || nodes++ > RPC_DFS_NODES) return;
        if (typeof node[0] === 'string' && RPC_IDS_RE.test(node[0])) {
          out.push({ rpcid: node[0], payload: typeof node[1] === 'string' ? node[1] : null });
          return;
        }
        for (const el of node) dig(el, depth + 1);
      })(parsed, 0);
    } catch (_) { /* cuerpo no parseable: cero entradas, cero riesgo */ }
    return out;
  }

  /* Des-enrolla un payload batchexecute (string doble-codificada → objeto).
   * Máximo 2 niveles de JSON.parse. */
  function unwrapPayloadString(ps) {
    let cur = ps;
    for (let i = 0; i < 2 && typeof cur === 'string'; i++) {
      try { cur = JSON.parse(cur); } catch (_) { break; }
    }
    return (cur && typeof cur === 'object') ? cur : null;
  }

  /* Clasifica los mediaId de Start Frame por ESTRUCTURA de ruta (contrato
   * forense F1): variante A = ...inputFrames.firstFrame.mediaId; variante B
   * = ...firstFrame.mediaId NO bajo inputFrames (p.ej. MEDIA_GENERATION_
   * SETTINGS.firstFrame). Aunque ambas traigan el MISMO id, ambas se
   * reportan. Sin match → undefined (lo ausente no se fabrica). */
  function findFirstFrameMediaIds(root) {
    const res = { inputFrames: undefined, standalone: undefined, startImage: undefined }; /* [F2] +startImage (histórico, solo si existe) */
    let nodes = 0;
    (function dig(node, path, depth) {
      if (!node || typeof node !== 'object' || depth > RPC_DFS_DEPTH || nodes++ > RPC_DFS_NODES) return;
      for (const k of Object.keys(node)) {
        const v = node[k];
        const np = path.concat(k);
        if (k === 'mediaId' && typeof v === 'string' && np.length >= 2) {
          if (np[np.length - 2] === 'firstFrame') {
            if (np.length >= 3 && np[np.length - 3] === 'inputFrames') {
              if (res.inputFrames === undefined) res.inputFrames = v;
            } else if (res.standalone === undefined) {
              res.standalone = v;
            }
          } else if (np[np.length - 2] === 'startImage' && res.startImage === undefined) {
            /* [F2] variante histórica: NO se asume que startImage existe */
            res.startImage = v;
          }
        }
        if (v && typeof v === 'object') dig(v, np, depth + 1);
      }
    })(root, [], 0);
    return res;
  }

  /* ========================================================================
   * [flow-start-frame F2] parser ANIDADO de MEDIA_GENERATION_SETTINGS.
   * El payload real (captura LIVE) trae MEDIA_GENERATION_SETTINGS cuyo VAL
   * es un STRING con JSON dentro: hay que JSON.parse de segundo nivel.
   * Todo defensivo: lo ausente no se fabrica; lo no parseable no rompe.
   * ====================================================================== */

  /* Localiza el VAL de MEDIA_GENERATION_SETTINGS en el payload ya
   * desenrollado: por llave de objeto O por par protobuf-ish
   * ['MEDIA_GENERATION_SETTINGS', <VAL>, ...]. DFS acotado. */
  function locateMediaGenSettingsValue(root) {
    let found;
    let nodes = 0;
    (function dig(node, depth) {
      if (found !== undefined || !node || typeof node !== 'object'
          || depth > RPC_DFS_DEPTH || nodes++ > RPC_DFS_NODES) return;
      if (Array.isArray(node)) {
        if (node.length >= 2 && node[0] === 'MEDIA_GENERATION_SETTINGS') {
          found = node[1];
          return;
        }
        for (const el of node) {
          if (found !== undefined) return;
          dig(el, depth + 1);
        }
        return;
      }
      for (const k of Object.keys(node)) {
        if (found !== undefined) return;
        if (k === 'MEDIA_GENERATION_SETTINGS') { found = node[k]; return; }
        const v = node[k];
        if (v && typeof v === 'object') dig(v, depth + 1);
      }
    })(root, 0);
    return found;
  }

  /* ¿El objeto tiene la forma del objeto real de settings? Solo marcadores
   * CONOCIDOS del protocolo observado (sin inventar campos). */
  function hasSettingsMarkers(o) {
    if (!o || typeof o !== 'object') return false;
    return findKeyFirst(o, 'videoModelKey') !== undefined
        || findKeyFirst(o, 'aspectRatio') !== undefined
        || findKeyFirst(o, 'count') !== undefined
        || findKeyFirst(o, 'inputFrames') !== undefined
        || findKeyFirst(o, 'firstFrame') !== undefined
        || findKeyFirst(o, 'startImage') !== undefined
        || findKeyFirst(o, 'structuredPrompt') !== undefined;
  }

  /* Busca DENTRO de un objeto el primer string que al parsear produce un
   * objeto con marcadores de settings (cubre VAL envuelto en sub-objeto). */
  function embeddedSettingsFromString(obj) {
    let found = null;
    let nodes = 0;
    (function dig(node, depth) {
      if (found || !node || typeof node !== 'object'
          || depth > RPC_DFS_DEPTH || nodes++ > RPC_DFS_NODES) return;
      for (const k of Object.keys(node)) {
        if (found) return;
        const v = node[k];
        if (typeof v === 'string' && v.length > 1 && v.length <= RPC_BODY_MAX
            && (v.charAt(0) === '{' || v.charAt(0) === '[')) {
          const cand = unwrapPayloadString(v);
          if (cand && hasSettingsMarkers(cand)) { found = cand; return; }
        }
        if (v && typeof v === 'object') dig(v, depth + 1);
      }
    })(obj, 0);
    return found;
  }

  /* Resuelve el objeto REAL de settings a partir del VAL localizado:
   *  - string  → JSON.parse (hasta 2 niveles, vía unwrapPayloadString)
   *  - objeto con marcadores → tal cual (formato F1/histórico)
   *  - objeto sin marcadores → busca string JSON embebido (VAL envuelto)
   *  - si nada funciona → parseError=true (evidencia parcial diagnóstica) */
  function resolveMediaGenSettings(payload, val) {
    if (val === undefined) return { settings: null, parseError: false };
    if (typeof val === 'string') {
      const parsed = unwrapPayloadString(val);
      if (parsed && hasSettingsMarkers(parsed)) return { settings: parsed, parseError: false };
      return { settings: null, parseError: true };
    }
    if (val && typeof val === 'object') {
      if (hasSettingsMarkers(val)) return { settings: val, parseError: false };
      const embedded = embeddedSettingsFromString(val);
      if (embedded) return { settings: embedded, parseError: false };
      return { settings: null, parseError: true };
    }
    return { settings: null, parseError: true };
  }

  /* [F2] cropCoordinates: whitelist estricta de números finitos top/left/
   * bottom/right (la captura LIVE muestra exactamente esas llaves; no es
   * secreto). Cualquier otra llave se ignora. */
  function sanitizeCrop(cc) {
    if (!cc || typeof cc !== 'object' || Array.isArray(cc)) return null;
    const out = {};
    for (const k of ['top', 'left', 'bottom', 'right']) {
      const v = cc[k];
      if (typeof v === 'number' && isFinite(v)) out[k] = v;
    }
    return Object.keys(out).length ? out : null;
  }

  /* [F2] cropCoordinates por ESTRUCTURA de ruta, igual que los mediaId:
   * inputFrames.firstFrame / firstFrame (standalone) / startImage (hist. */
  function findCropCoordinates(root) {
    const res = { inputFrames_firstFrame: undefined, firstFrame: undefined, startImage: undefined };
    let nodes = 0;
    (function dig(node, path, depth) {
      if (!node || typeof node !== 'object' || depth > RPC_DFS_DEPTH || nodes++ > RPC_DFS_NODES) return;
      for (const k of Object.keys(node)) {
        const v = node[k];
        const np = path.concat(k);
        if (k === 'cropCoordinates' && np.length >= 2) {
          const parent = np[np.length - 2];
          let cat = null;
          if (parent === 'firstFrame') {
            cat = (np.length >= 3 && np[np.length - 3] === 'inputFrames')
              ? 'inputFrames_firstFrame' : 'firstFrame';
          } else if (parent === 'startImage') {
            cat = 'startImage';
          }
          if (cat && res[cat] === undefined) {
            const s = sanitizeCrop(v);
            if (s) res[cat] = s;
          }
        }
        if (v && typeof v === 'object') dig(v, np, depth + 1);
      }
    })(root, [], 0);
    return res;
  }

  /* Primer valor por nombre exacto de llave (DFS acotado). */
  function findKeyFirst(root, keyName) {
    let found;
    let seen = false;
    let nodes = 0;
    (function dig(node, depth) {
      if (seen || !node || typeof node !== 'object' || depth > RPC_DFS_DEPTH || nodes++ > RPC_DFS_NODES) return;
      for (const k of Object.keys(node)) {
        if (k === keyName && !seen) { found = node[k]; seen = true; return; }
        const v = node[k];
        if (v && typeof v === 'object') dig(v, depth + 1);
      }
    })(root, 0);
    return seen ? found : undefined;
  }

  /* Escaneo con LISTA BLANCA de un objeto respuesta/request: captura SOLO
   * llaves conocidas no sensibles; mediaId → huella; el resto se ignora. */
  function scanWhitelisted(root) {
    const ids = {};
    const states = {};
    const mediaFps = [];
    let nodes = 0;
    (function dig(node, depth) {
      if (!node || typeof node !== 'object' || depth > RPC_DFS_DEPTH || nodes++ > RPC_DFS_NODES) return;
      for (const k of Object.keys(node)) {
        const v = node[k];
        if (k === 'mediaId') {
          if (typeof v === 'string' && v && mediaFps.length < RPC_MEDIA_FP_MAX) {
            const fp = fpHash(v);
            if (mediaFps.indexOf(fp) === -1) mediaFps.push(fp);
          }
        } else if (RPC_ID_KEYS.indexOf(k) !== -1 && typeof v === 'string' && v && !(k in ids)) {
          if (Object.keys(ids).length < RPC_IDS_MAX) ids[k] = redactSecrets(v).slice(0, RPC_ID_VAL_MAX);
        } else if (RPC_STATE_KEYS.indexOf(k) !== -1 && v != null && typeof v !== 'object' && !(k in states)) {
          if (Object.keys(states).length < RPC_IDS_MAX) states[k] = redactSecrets(String(v)).slice(0, 40);
        }
        if (v && typeof v === 'object') dig(v, depth + 1);
      }
    })(root, 0);
    return { ids, states, mediaFps };
  }

  /* Espejo local + traza de consola (visibilidad para la prueba manual F1);
   * y emisión por el canal existente. Nada de esto puede fallar jamás. */
  function recordRpcObs(obs) {
    try {
      try {
        const arr = (window.__FLOW_RPC_OBS__ = window.__FLOW_RPC_OBS__ || []);
        arr.push(obs);
        while (arr.length > RPC_MIRROR_MAX) arr.shift();
        console.info('[flow-ext][rpc]', obs.kind, obs.rpcid, JSON.stringify(obs));
      } catch (_) { /* espejo best-effort */ }
      emit('FLOW_RPC_EVIDENCE', obs);
    } catch (_) { /* silencioso */ }
  }

  /* Observa el REQUEST batchexecute (fetch o XHR). SOLO estructura. */
  function observeRpcRequestBody(url, method, bodyValue) {
    try {
      const urlIds = rpcIdsFromUrl(url);
      const entries = parseFreqEntries(rpcBodyText(bodyValue));
      const seen = {};
      const ordered = [];
      for (const rid of urlIds) {
        if (RPC_IDS_RE.test(rid) && !seen[rid]) { seen[rid] = true; ordered.push({ rpcid: rid, payload: null }); }
      }
      for (const e of entries) {
        if (!seen[e.rpcid]) { seen[e.rpcid] = true; ordered.push(e); }
        else {
          /* entrada del cuerpo con payload para un rpcid ya listado en URL */
          const prev = ordered.find((x) => x.rpcid === e.rpcid);
          if (prev && !prev.payload) prev.payload = e.payload;
        }
      }
      for (const e of ordered) {
        const obs = {
          kind: 'rpc_request', rpcid: e.rpcid, operation: null,
          url: safeUrl(url), method: String(method || 'GET').toUpperCase().slice(0, 10),
          ts: Date.now(),
          videoModelKey: null, aspectRatio: null, count: null,
          startFrame: null, ids: {},
        };
        const payload = e.payload ? unwrapPayloadString(e.payload) : null;
        if (payload) {
          /* operación SOLO si el marcador estructural existe (sin inventar);
           * [F2] localiza el VAL aunque venga como par protobuf-ish */
          const settingsVal = locateMediaGenSettingsValue(payload);
          if (settingsVal !== undefined
              || /MEDIA_GENERATION/.test(String(e.payload || '').slice(0, RPC_BODY_MAX))) {
            obs.operation = 'MEDIA_GENERATION';
          }
          /* [F2] VAL anidado: MEDIA_GENERATION_SETTINGS puede ser un STRING
           * con JSON (formato LIVE) u objeto directo (formato F1). */
          const r = resolveMediaGenSettings(payload, settingsVal);
          const src = r.settings || payload;
          const vmk = findKeyFirst(src, 'videoModelKey');
          if (typeof vmk === 'string' && vmk) obs.videoModelKey = redactSecrets(vmk).slice(0, 60);
          else if (typeof vmk === 'number' && isFinite(vmk)) obs.videoModelKey = String(vmk);
          const ar = findKeyFirst(src, 'aspectRatio');
          if (typeof ar === 'string' && ar) obs.aspectRatio = redactSecrets(ar).slice(0, 30);
          else if (typeof ar === 'number' && isFinite(ar)) obs.aspectRatio = ar; /* LIVE: 1 */
          const cnt = findKeyFirst(src, 'count');
          if (typeof cnt === 'number' && isFinite(cnt)) obs.count = cnt;
          else if (typeof cnt === 'string' && /^\d{1,4}$/.test(cnt)) obs.count = parseInt(cnt, 10);
          /* [F2] structuredPrompt: SOLO presencia (el contenido no se emite) */
          if (findKeyFirst(src, 'structuredPrompt') !== undefined) obs.structuredPromptPresent = true;
          /* Start Frame: campos del contrato forense clasificados por
           * ESTRUCTURA (no por valor). [F1] dos rutas; [F2] +startImage y
           * representación plana {mediaIdPresent, fingerprint}. */
          const ff = findFirstFrameMediaIds(src);
          const inFp = mediaFp(ff.inputFrames);
          const stFp = mediaFp(ff.standalone);
          const siFp = mediaFp(ff.startImage);
          if (inFp || stFp || siFp) {
            obs.startFrame = {
              mediaIdPresent: true,
              fingerprint: (inFp || stFp || siFp).fp,
            };
            if (inFp) obs.startFrame.inputFrames_firstFrame_mediaId = inFp;
            if (stFp) obs.startFrame.firstFrame_mediaId = stFp;
            if (siFp) obs.startFrame.startImage_mediaId = siFp;
            if (inFp) obs.ids.inputFramesFirstFrame = inFp.fp;
            if (stFp) obs.ids.firstFrame = stFp.fp;
            if (siFp) obs.ids.startImage = siFp.fp;
          }
          /* [F2] cropCoordinates (no es secreto; whitelist numérica) */
          const cc = findCropCoordinates(src);
          if (cc.inputFrames_firstFrame || cc.firstFrame || cc.startImage) obs.cropCoordinates = cc;
          const w = scanWhitelisted(payload);
          obs.ids = Object.assign(w.ids, obs.ids); /* ids F1 + huellas F2 */
          /* [F2] JSON anidado no parseable → evidencia parcial diagnóstica */
          if (r.parseError) obs.settingsParseError = true;
        }
        recordRpcObs(obs);
      }
    } catch (_) { /* silencioso */ }
  }

  /* Observa la RESPONSE batchexecute ya parseada (array NDJSON u objeto).
   * Identifica entradas wrb.fr de los rpcids de interés y captura SOLO
   * identificadores/estados de la lista blanca. */
  function observeRpcResponseBody(url, parsedBody) {
    try {
      const nodes = Array.isArray(parsedBody) ? parsedBody : [parsedBody];
      let visited = 0;
      const visit = (node, depth) => {
        if (!node || typeof node !== 'object' || depth > 4 || visited++ > RPC_DFS_NODES) return;
        if (Array.isArray(node)) {
          if (typeof node[0] === 'string' && node[0] === 'wrb.fr' && RPC_IDS_RE.test(String(node[1] || ''))) {
            const rpcid = String(node[1]);
            const obs = { kind: 'rpc_response', rpcid, url: safeUrl(url), ts: Date.now(), ids: {}, states: {}, mediaFps: [] };
            const inner = unwrapPayloadString(typeof node[2] === 'string' ? node[2] : null);
            if (inner) {
              const w = scanWhitelisted(inner);
              obs.ids = w.ids; obs.states = w.states; obs.mediaFps = w.mediaFps;
            } else if (typeof node[2] === 'string' && node[2]) {
              /* payload no parseable: escaneo regex acotado de la lista blanca */
              const s = node[2].slice(0, RPC_BODY_MAX);
              const re = /"(mediaId|workflowId|batchId|videoId|jobId|projectId|toolId|status|state|generationStatus)"\s*:\s*"([^"]{1,80})"/g;
              let m, n = 0;
              while ((m = re.exec(s)) !== null && n < RPC_IDS_MAX) {
                n++;
                if (m[1] === 'mediaId') {
                  const fp = fpHash(m[2]);
                  if (obs.mediaFps.length < RPC_MEDIA_FP_MAX && obs.mediaFps.indexOf(fp) === -1) obs.mediaFps.push(fp);
                } else if (RPC_ID_KEYS.indexOf(m[1]) !== -1) {
                  obs.ids[m[1]] = redactSecrets(m[2]).slice(0, RPC_ID_VAL_MAX);
                } else {
                  obs.states[m[1]] = redactSecrets(m[2]).slice(0, 40);
                }
              }
            }
            recordRpcObs(obs);
            return;
          }
          for (const el of node) visit(el, depth + 1);
        } else {
          for (const k of Object.keys(node)) visit(node[k], depth + 1);
        }
      };
      for (const n of nodes) visit(n, 0);
    } catch (_) { /* silencioso */ }
  }

  /* URL SIN query string: los query params pueden contener tokens/firmas
   * (p.ej. URLs firmadas de media); se eliminan SIEMPRE. */
  function safeUrl(url) {
    try { return String(url || '').split('?')[0].slice(0, 200); } catch (_) { return ''; }
  }

  function emitNetworkFailure(url, method, err) {
    try {
      emit('FLOW_NETWORK_EVIDENCE', {
        kind: 'network_failure', source: 'flow_network',
        status: null, statusText: '', ok: false,
        url: safeUrl(url), method: String(method || 'GET').toUpperCase().slice(0, 10),
        ts: Date.now(), endpoint: endpointCategory(url),
        body: '', truncated: false, total: 0,
        error: truncateDeterministic(redactSecrets((err && (err.message || String(err))) || 'fallo de red'), 200).text,
      });
    } catch (_) { /* silencioso */ }
  }

  async function captureNetworkError(url, method, resp) {
    try {
      if (!resp) return;
      let bodyInfo = { text: '', truncated: false, total: 0 };
      try {
        const raw = await resp.clone().text();
        bodyInfo = truncateDeterministic(redactSecrets(raw), EVIDENCE_BODY_MAX);
      } catch (_) { /* cuerpo ilegible: sin cuerpo, la evidencia sigue */ }
      emit('FLOW_NETWORK_EVIDENCE', {
        kind: 'http_error', source: 'flow_network',
        status: resp.status, statusText: String(resp.statusText || '').slice(0, 80), ok: !!resp.ok,
        url: safeUrl(url), method: String(method || 'GET').toUpperCase().slice(0, 10),
        ts: Date.now(), endpoint: endpointCategory(url),
        body: bodyInfo.text, truncated: bodyInfo.truncated, total: bodyInfo.total,
        error: '',
      });
    } catch (_) { /* interceptor silencioso */ }
  }
  /* ---- fin [observability v1.1] --------------------------------------- */

  function safeStringify(x) {
    try { return JSON.stringify(x); } catch (_) { return ''; }
  }

  function parseMaybeNdjson(text) {
    const trimmed = (text || '').trim();
    if (!trimmed) return null;
    try { return JSON.parse(trimmed); } catch (_) { /* probar NDJSON */ }
    if (trimmed.indexOf('\n') === -1) return null;
    const lines = trimmed.split('\n').filter((l) => l.trim());
    if (!lines.length) return null;
    const parsed = [];
    for (const line of lines) {
      try { parsed.push(JSON.parse(line)); } catch (_) { /* linea no JSON, ignorar */ }
    }
    return parsed.length ? parsed : null;
  }

  async function captureResponse(url, resp, method) {
    try {
      /* [observability v1.1] los errores HTTP (4xx/5xx) son EVIDENCIA CRUDA:
       * se capturan por FLOW_NETWORK_EVIDENCE y se retorna (la extracción de
       * batch/media SOLO aplica a respuestas OK — sin regresión). */
      if (!resp) return;
      if (!resp.ok) { await captureNetworkError(url, method, resp); return; }
      const ct = (resp.headers && resp.headers.get('content-type')) || '';
      let body = null;
      if (/ndjson/i.test(ct)) {
        const text = await resp.clone().text();
        body = parseMaybeNdjson(text);
      } else {
        const text = await resp.clone().text();
        if (text && text.length <= MAX_BODY) body = parseMaybeNdjson(text);
      }
      if (!body) return;
      /* [flow-start-frame F1] respuesta batchexecute: observación PASIVA de
       * los rpcids de interés (usa el body YA parseado; cero lecturas extra).
       * batchexecute NO entra al canal FLOW_BATCH_RESPONSE (canal tRPC de la
       * automatización: antes de F1 jamás vio batchexecute → cero cambio de
       * comportamiento y el mediaId crudo no transita por él). */
      if (endpointCategory(url) === 'batchexecute') {
        try { observeRpcResponseBody(url, body); } catch (_) {}
        return;
      }
      const s = safeStringify(body);
      if (s && s.length <= MAX_BODY && MARKER_RE.test(s)) emit('FLOW_BATCH_RESPONSE', body);
    } catch (_) { /* interceptor silencioso */ }
  }

  function relevantUrl(url) {
    try {
      const u = String(url || '');
      if (!u || u.indexOf('http') !== 0) return false;
      return URL_HINTS.some((h) => u.indexOf(h) !== -1);
    } catch (_) { return false; }
  }

  /* ---- Parche de window.fetch ---- */
  const originalFetch = window.fetch;
  if (typeof originalFetch === 'function') {
    window.fetch = function (input, init) {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const method = ((init && init.method) || (input && input.method) || 'GET');
      const relevant = relevantUrl(url);
      if (relevant) {
        /* [flow-start-frame F1] lectura PASIVA del cuerpo (init.body) sin
         * mutarlo jamás: se pasa la referencia original, solo se lee. */
        try { observeRpcRequestBody(url, method, init ? init.body : null); } catch (_) {}
      }
      const promise = originalFetch.apply(this, arguments);
      if (relevant) {
        promise.then((resp) => { captureResponse(url, resp, method); })
               .catch((err) => { emitNetworkFailure(url, method, err); });
      }
      return promise;
    };
  }

  /* ---- Parche de XMLHttpRequest ---- */
  const XHR = window.XMLHttpRequest;
  if (XHR && XHR.prototype) {
    const originalOpen = XHR.prototype.open;
    const originalSend = XHR.prototype.send;

    XHR.prototype.open = function (method, url) {
      try {
        this.__flowExtUrl = relevantUrl(url) ? String(url) : null;
        this.__flowExtMethod = String(method || 'GET');
      } catch (_) {}
      return originalOpen.apply(this, arguments);
    };

    XHR.prototype.send = function () {
      if (this.__flowExtUrl) {
        /* [flow-start-frame F1] cuerpo de request XHR (solo lectura; la
         * referencia original pasa intacta a originalSend). */
        try { observeRpcRequestBody(this.__flowExtUrl, this.__flowExtMethod, arguments[0]); } catch (_) {}
        this.addEventListener('load', () => {
          try {
            if (this.readyState !== 4) return;
            /* [observability v1.1] errores HTTP del XHR también son evidencia */
            if (this.status < 200 || this.status >= 300) {
              if (this.status >= 400) {
                let bodyInfo = { text: '', truncated: false, total: 0 };
                try {
                  const rt = (this.responseType || 'text');
                  const rawText = (rt === 'json') ? safeStringify(this.response)
                    : (rt === 'text' || rt === '') ? this.responseText : '';
                  bodyInfo = truncateDeterministic(redactSecrets(rawText || ''), EVIDENCE_BODY_MAX);
                } catch (_) { /* responseText puede lanzar según responseType */ }
                emit('FLOW_NETWORK_EVIDENCE', {
                  kind: 'http_error', source: 'flow_network',
                  status: this.status,
                  statusText: String(this.statusText || '').slice(0, 80), ok: false,
                  url: safeUrl(this.__flowExtUrl),
                  method: String(this.__flowExtMethod || 'GET').toUpperCase().slice(0, 10),
                  ts: Date.now(), endpoint: endpointCategory(this.__flowExtUrl),
                  body: bodyInfo.text, truncated: bodyInfo.truncated, total: bodyInfo.total,
                  error: '',
                });
              }
              return;
            }
            const rt = (this.responseType || 'text');
            let body = null;
            if (rt === 'json') body = this.response;
            else if (rt === 'text' || rt === '') body = parseMaybeNdjson(this.responseText);
            if (!body) return;
            /* [flow-start-frame F1] respuesta batchexecute por XHR: canal
             * propio; NO entra a FLOW_BATCH_RESPONSE (mismo motivo que fetch) */
            if (endpointCategory(this.__flowExtUrl) === 'batchexecute') {
              try { observeRpcResponseBody(this.__flowExtUrl, body); } catch (_) {}
              return;
            }
            const s = safeStringify(body);
            if (s && s.length <= MAX_BODY && MARKER_RE.test(s)) emit('FLOW_BATCH_RESPONSE', body);
          } catch (_) { /* silencioso */ }
        });
        this.addEventListener('error', () => {
          emitNetworkFailure(this.__flowExtUrl, this.__flowExtMethod, new Error('network error (XHR)'));
        });
        this.addEventListener('timeout', () => {
          emitNetworkFailure(this.__flowExtUrl, this.__flowExtMethod, new Error('timeout de red (XHR)'));
        });
      }
      return originalSend.apply(this, arguments);
    };
  }
})();

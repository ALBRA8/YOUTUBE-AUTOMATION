"""
Flow Adaptation — capa OPERACIONAL entre el Production JSON y Google Flow.

Cadena contractual (v3):

    Production JSON → Adapter (production_json) → FLOW ADAPTATION (aquí)
                    → Flow Jobs → Bridge → Extensión → Google Flow

QUÉ ES (mandato FLOW ADAPTATION / RUNTIME LEARNING):
  Google Flow NO es determinista: la misma entrada puede variar por red,
  carga, inferencia, cola, video vs imagen, errores transitorios, políticas,
  restricciones de identidad/imagen derechos, formulaciones de cámara o
  palabras rechazadas. Esta capa implementa el ciclo operacional:

      OBSERVAR → CLASIFICAR → ADAPTAR → REINTENTAR (cuando corresponda)
      → VALIDAR → REGISTRAR

QUÉ NO ES (límites duros, inviolables):
  - NO es un segundo Creative Engine. La autoridad creativa sigue siendo el
    Creative Engine (script/producción): aquí jamás se genera contenido, ni
    se cambia historia, personajes, narrativa, identidad creativa, Niche
    Blueprint ni el Production JSON original.
  - NO modifica production_unit, production.json, niche_extra, image_prompt,
    video_prompt ni ningún campo creativo: SOLO escribe (1) la columna
    operacional flow_jobs.prompt_adapted (P2) vía flow_jobs.set_adapted_prompt
    y (2) su propio ledger JSONL (memoria operacional separada).
  - NO inventa causas: la taxonomía V1.1 (A-I) se asigna SOLO con evidencia
    observada y con PRIORIDAD DE EVIDENCIA (④). Sin evidencia → I UNKNOWN.

FLOW OBSERVABILITY V1.1 (separación watchdog vs proveedor, mandato ③④):
  La evidencia que llega del veredicto local de la extensión trae CAPAS
  CRUDAS: red (http:/http-body:), notificaciones del sistema de Flow
  (notif: "…", source flow_notification), error-tiles (tile:),
  configuración (cfg:, source flow_generation_settings) y audio (audio=).
  Taxonomía A-I — SOLO con evidencia textual clara para C-H:

    A) FLOW_WATCHDOG_TIMEOUT     ventana LOCAL agotada sin evidencia
                                 específica del proveedor (NUNCA se
                                 interpreta como timeout del proveedor)
    B) FLOW_PROVIDER_ERROR       Flow reportó un error explícito y la causa
                                 NO es determinable (no se inventa)
    C) FLOW_AUDIO_ERROR          video generado pero audio falló/omitido
                                 (SOLO con texto explícito de audio)
    D) FLOW_POLICY_ERROR         rechazo de política de contenido
    E) FLOW_CREDIT_ERROR         créditos insuficientes/agotados
    F) FLOW_IDENTITY_LIKENESS_ERROR  restricción de identidad/likeness
    G) FLOW_COPYRIGHT_ERROR      copyright/contenido protegido
    H) FLOW_UNUSUAL_ACTIVITY     actividad inusual señalada por Flow
    I) UNKNOWN_FLOW_FAILURE      sin resultado/evidencia clasificable

  Prioridad de evidencia (④, de fuerte a débil — la débil JAMÁS contradice
  a la fuerte): 1 red/respuesta con causa clara > 2 notificación del
  sistema con causa clara > 3 error-tile con texto claro > 4 estado DOM >
  5 watchdog local > 6 sin resultado. Un status HTTP aislado NO infiere
  causa (403 genérico → B, no D); "No se pudo generar el video" NO es un
  fallo de audio; un tile genérico + watchdog → A (no B de proveedor).

P1 / P2 (separación inequívoca):
  P1 = prompt creativo original (flow_jobs.prompt, fuente única
       build_script_json) — NUNCA se sobrescribe.
  P2 = prompt adaptado SOLO para ejecución operacional en Flow
       (flow_jobs.prompt_adapted) — un único intento extra por job.

Memoria operacional (ledger JSONL, append-only): cada retry registra
  prompt_original, evidencia cruda + estructura, clasificación con
  confianza y fuente de la evidencia, transformación, prompt_adaptado,
  resultado y retry. Las observaciones son EVIDENCIA OPERACIONAL, no reglas
  universales. NO modifica Creative Engine, Niche Blueprint, narrativa ni
  Production JSON.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import database as db

# ── constantes del contrato ──────────────────────────────────────────────────

FLOW_ADAPTATION_REQUIRED = "FLOW_ADAPTATION_REQUIRED"

# Taxonomía V1.1 (③): SOLO con evidencia; sin evidencia → I.
CLASES = {
    "A": "FLOW_WATCHDOG_TIMEOUT",
    "B": "FLOW_PROVIDER_ERROR",
    "C": "FLOW_AUDIO_ERROR",
    "D": "FLOW_POLICY_ERROR",
    "E": "FLOW_CREDIT_ERROR",
    "F": "FLOW_IDENTITY_LIKENESS_ERROR",
    "G": "FLOW_COPYRIGHT_ERROR",
    "H": "FLOW_UNUSUAL_ACTIVITY",
    "I": "UNKNOWN_FLOW_FAILURE",
}

# Patrones operacionales V1.1 (clases C-H: SOLO texto claro; sin patrón →
# B/I, jamás se inventa causa). Matching case-insensitive por subcadena.
_PATRONES = {
    "D": ("politica", "política", "policy", "infringement",
          "bloqueo de politicas", "bloqueo de políticas", "content policy",
          "no permitido", "viola nuestras"),
    "E": ("no tienes creditos", "no tienes créditos", "sin creditos",
          "sin créditos", "insuficientes creditos", "insuficientes créditos",
          "creditos insuficientes", "créditos insuficientes",
          "credito insuficiente", "crédito insuficiente",
          "not enough credits", "out of credits", "insufficient credits",
          "agotaste tus creditos", "agotaste tus créditos",
          "compra creditos", "compra créditos", "buy credits to",
          "upgrade your plan", "actualiza tu plan"),
    "F": ("persona real", "personas reales", "identidad", "likeness",
          "derechos de imagen", "imagen de una persona",
          "figura publica", "figura pública", "celebridad",
          "rostro de una persona"),
    "G": ("copyright", "derechos de autor", "material protegido",
          "marca registrada", "contenido protegido",
          "propiedad intelectual"),
    "H": ("actividad inusual", "unusual activity", "actividad sospechosa",
          "comportamiento inusual", "cuenta limitada",
          "cuenta restringida"),
}
# Prioridad DETERMINISTA entre clases cuando el mismo texto tocara varias
# (la más específica/estructural primero; C audio se evalúa aparte porque
# exige su patrón regex propio — ver _AUDIO_FALLO_RE).
_PRIORIDAD = ("D", "F", "G", "H", "E")

# C) audio: SOLO cuando el texto menciona 'audio' con fallo EXPLÍCITO.
#    "No se pudo generar el video" NO casa (no menciona audio) → ⑨.
_AUDIO_WORD_RE = re.compile(r"\baudio\b", re.IGNORECASE)
_AUDIO_FALLO_RE = re.compile(
    r"(sin audio|audio fall\w*|fall\w+ de audio|error de audio|"
    r"no se pudo generar el audio|no pudimos generar el audio|"
    r"audio no disponible|audio omitid\w*|silencioso|mudo)",
    re.IGNORECASE)

# ── parser de las CAPAS de evidencia (formato composeEvidence, ext 2.3.1) ────
_HTTP_RE = re.compile(r"(?:^|\|\s*)http:\s*(\d{3})\s*([A-Za-z]{3,8})?", re.IGNORECASE)
_HTTP_BODY_RE = re.compile(r"(?:^|\|\s*)http-body:\s*([^\|]+)", re.IGNORECASE)
_NOTIF_RE = re.compile(r"(?:^|\|\s*)(?:notif|notificacion|notificación):\s*\"([^\"]*)\"",
                       re.IGNORECASE)
_TILE_RE = re.compile(r"(?:^|\|\s*)(?:flow-error-tile|tile):\s*([^\|]+)", re.IGNORECASE)
_WATCHDOG_RE = re.compile(r"watchdog|timeout|lease|ventana", re.IGNORECASE)
_EXPLICIT_FAIL_RE = re.compile(r"error|fallo|falló|no se pudo|no pudimos|fracas",
                               re.IGNORECASE)
_CFG_RE = re.compile(r"(?:^|\|\s*)cfg:\s*([^\|]+)", re.IGNORECASE)
_AUDIO_SILENT_RE = re.compile(r"(?:^|\|\s*)audio=(\w+)", re.IGNORECASE)


# Patrones S1 (reencuadre identidad→descripción visual existente, clase F).
_S2_ELIMINADA = ("S2 eliminada en V1.1: la taxonomía A-I ya no tiene clase "
                 "de 'interpretación de prompt'; sin clase con evidencia no "
                 "hay estrategia (fail-closed → FLOW_ADAPTATION_REQUIRED)")
RETRY_POLICY = {
    "A": {"reintentar": False, "adaptar": None, "motivo":
          "ventana LOCAL agotada sin evidencia específica del proveedor: "
          "no se asume causa, no se cambia el prompt; el requeue lo gobierna "
          "el contrato de lease (recover_expired), esta capa no concede extra"},
    "B": {"reintentar": True, "adaptar": None, "motivo":
          "Flow reportó un error explícito sin causa determinable: no se "
          "inventa adaptación; reintento limitado con P1"},
    "C": {"reintentar": True, "adaptar": None, "motivo":
          "fallo de audio: el prompt visual NO se toca; reintento limitado "
          "con P1"},
    "D": {"reintentar": False, "adaptar": None, "motivo":
          "rechazo de política de contenido: no existe estrategia segura y "
          "determinista → reportar (no reintento idéntico)"},
    "E": {"reintentar": False, "adaptar": None, "motivo":
          "créditos insuficientes: reintento no resuelve la causa "
          "operacional → sin reintento"},
    "F": {"reintentar": True, "adaptar": "S1", "motivo":
          "restricción de identidad/likeness: S1 reencuadra identidad → "
          "descripción visual del avatar (datos creativos existentes)"},
    "G": {"reintentar": False, "adaptar": None, "motivo":
          "restricción de copyright/contenido protegido: sin estrategia "
          "segura ni workaround inventado → reportar (S1 prohibido)"},
    "H": {"reintentar": False, "adaptar": None, "motivo":
          "actividad inusual señalada por Flow: causa operacional de "
          "cuenta; pausar reintentos inmediatos"},
    "I": {"reintentar": True, "adaptar": None, "motivo":
          "fallo desconocido sin evidencia clasificable: registrar + "
          "reintento limitado SIN inventar causa"},
}
MAX_EXTRA_GRANTS = 1  # total de reencolas concedidas por esta capa por job

# ── memoria operacional (ledger JSONL separado, patcheable en tests) ─────────

LEDGER_PATH = Path(__file__).resolve().parent.parent / "data" / "flow_adaptation" / "ledger.jsonl"


def _ledger() -> Path:
    """Resuelve el path EN CALL TIME (los tests reasignan LEDGER_PATH)."""
    return Path(LEDGER_PATH)


def _registrar(registro: dict) -> None:
    """Append-only al ledger operacional. Jamás tumba la operación."""
    try:
        p = _ledger()
        p.parent.mkdir(parents=True, exist_ok=True)
        reg = dict(registro)
        reg.setdefault("ts", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — observabilidad, nunca crítico
        pass


def _grants_previos(job_id: str) -> int:
    """Cuántos reencolas concedió esta capa al job (anti-bucle, límite duro)."""
    try:
        p = _ledger()
        if not p.exists():
            return 0
        n = 0
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except (ValueError, TypeError):
                    continue  # línea corrupta: se ignora
                if r.get("job_id") == job_id and r.get("otorgado"):
                    n += 1
        return n
    except Exception:  # noqa: BLE001
        return 0


def registrar_cierre(job_id: str, resultado: str, detalle: str = "") -> None:
    """Cierra el ciclo del retry en el ledger: registra si la adaptación
    FUNCIONÓ (asset validado al completar el job con P2) o si se agotó.
    Auditoría v3-audit-backend (riesgo 2): sin esto el outcome quedaba
    'pendiente' perpetuo. Registro {'cierre': True} — jamás toca datos
    creativos; tolerado si el ledger no puede escribirse."""
    _registrar({"cierre": True, "job_id": job_id,
                "resultado": resultado, "detalle": (detalle or "")[:300]})


# ── OBSERVAR → CLASIFICAR (solo evidencia; nunca inventar causa) ─────────────

def _causa_especifica(texto: str) -> tuple[str, str] | None:
    """Detección de causa ESPECÍFICA (clases C-H) SOLO por texto claro.
    Devuelve (clase, detalle_patron) o None. Orden determinista: C audio
    (regex propia), luego _PRIORIDAD D>F>G>H>E. 'No se pudo generar el
    video' NO es audio (no menciona audio) → ⑨."""
    t = (texto or "").lower()
    if not t:
        return None
    if _AUDIO_WORD_RE.search(texto) and _AUDIO_FALLO_RE.search(texto):
        return ("C", "fallo de audio explícito")
    for k in _PRIORIDAD:
        for pat in _PATRONES[k]:
            if pat in t:
                return (k, pat)
    return None


def _parse_evidencia(evidencia: str, contexto: dict) -> dict:
    """⑩ Capa ESTRUCTURAL: parsea las capas CRUDAS del veredicto de la
    extensión (composeEvidence) SIN sustituirlas. El texto bruto viaja
    siempre íntegro en 'bruto'."""
    raw = evidencia or ""
    estructura: dict = {
        "http": None, "http_body": None,
        "notificaciones": [], "tiles": [],
        "configuracion": None, "audio_silencioso": None,
        "watchdog_local": bool(_WATCHDOG_RE.search(raw))
        or bool(contexto.get("ventana_agotada")),
        "bruto": raw[:600],
    }
    m = _HTTP_RE.search(raw)
    if m:
        estructura["http"] = {"status": int(m.group(1)),
                              "metodo": (m.group(2) or "?").upper()}
    mb = _HTTP_BODY_RE.search(raw)
    if mb:
        estructura["http_body"] = mb.group(1).strip()[:300]
    for mn in _NOTIF_RE.finditer(raw):
        estructura["notificaciones"].append(
            {"text": mn.group(1).strip()[:300], "source": "flow_notification"})
    for mt in _TILE_RE.finditer(raw):
        estructura["tiles"].append(
            {"text": mt.group(1).strip()[:300], "source": "flow_error_tile"})
    mc = _CFG_RE.search(raw)
    if mc:
        cfg: dict = {"source": "flow_generation_settings"}
        for par in mc.group(1).split(","):
            if "=" in par:
                k, v = par.split("=", 1)
                cfg[k.strip()[:12]] = v.strip()[:60]
        estructura["configuracion"] = cfg
    mas = _AUDIO_SILENT_RE.search(raw)
    if mas:
        estructura["audio_silencioso"] = mas.group(1).lower()
    return estructura


def clasificar(evidencia: str, kind: str = "video",
               contexto: dict | None = None) -> dict:
    """Clasifica un fallo de Flow según la EVIDENCIA observada (V1.1).

    contexto: {transitorio: bool (intento fallido con generación aún activa),
               ventana_agotada: bool, resultado_valido: bool}.

    Prioridad de evidencia (④, fuerte→débil; la débil JAMÁS contradice a la
    fuerte): 1) causa específica por capa: http-body > notificación >
    error-tile > texto bruto (legado); 2) watchdog local → A
    FLOW_WATCHDOG_TIMEOUT (NUNCA es un timeout del proveedor); 3) error
    explícito de Flow sin causa → B FLOW_PROVIDER_ERROR; 4) nada → I
    UNKNOWN_FLOW_FAILURE. Un status HTTP aislado NO infiere causa.

    Confianza (⑪): HIGH = causa específica por respuesta de red o
    notificación; MEDIUM = causa específica por tile, o error explícito de
    Flow sin causa completa; LOW = solo estado local (A/I).
    Un resultado válido NO es un fallo: {clase: None}."""
    ctx = contexto or {}
    raw = evidencia or ""
    texto = raw.lower()
    if ctx.get("resultado_valido"):
        return {"clase": None, "codigo": "SUCCESS",
                "motivo": "hay resultado válido: no es un fallo",
                "evidencia": raw[:300],
                "evidencia_estructura": _parse_evidencia(raw, ctx),
                "classification_confidence": None,
                "fuente_evidencia": None}
    estructura = _parse_evidencia(raw, ctx)

    # 1) causa específica por capa de evidencia (fuerte → débil)
    capas = (
        ("http_response", estructura.get("http_body"), "HIGH"),
        ("flow_notification",
         " ".join(n["text"] for n in estructura["notificaciones"]), "HIGH"),
        ("flow_error_tile",
         " ".join(t["text"] for t in estructura["tiles"]), "MEDIUM"),
        ("texto_legado", raw, "MEDIUM"),
    )
    for fuente, capa_texto, conf in capas:
        if not capa_texto:
            continue
        hit = _causa_especifica(capa_texto)
        if hit:
            clase, detalle = hit
            return {"clase": clase, "codigo": CLASES[clase],
                    "motivo": f"evidencia textual de clase {clase} "
                              f"({CLASES[clase]}) vía {fuente}: {detalle}",
                    "evidencia": raw[:300],
                    "evidencia_estructura": estructura,
                    "classification_confidence": conf,
                    "fuente_evidencia": fuente}

    # 2) watchdog local (⑤/evidencia local): NUNCA se interpreta como
    #    timeout del proveedor (③); causalidad LOCAL, confianza LOW (⑪)
    if estructura["watchdog_local"]:
        return {"clase": "A", "codigo": CLASES["A"],
                "motivo": "ventana LOCAL agotada sin evidencia específica "
                          "del proveedor: no se asume causa (la causalidad "
                          "de proveedor es LOCAL/LOW)",
                "evidencia": raw[:300],
                "evidencia_estructura": estructura,
                "classification_confidence": "LOW",
                "fuente_evidencia": "watchdog_local",
                "alcance_causal": "LOCAL"}

    # 3) error explícito de Flow sin causa determinable → B
    if estructura.get("http") or estructura["tiles"] \
            or estructura["notificaciones"] \
            or _EXPLICIT_FAIL_RE.search(texto):
        fuente = ("http_status" if estructura.get("http")
                  else ("flow_notification" if estructura["notificaciones"]
                        else ("flow_error_tile" if estructura["tiles"]
                              else "texto_error")))
        return {"clase": "B", "codigo": CLASES["B"],
                "motivo": "Flow reportó un error explícito sin causa "
                          "determinable: no se inventa (un status HTTP "
                          "aislado no infiere causa)",
                "evidencia": raw[:300],
                "evidencia_estructura": estructura,
                "classification_confidence": "MEDIUM",
                "fuente_evidencia": fuente}

    # 4) sin evidencia clasificable → I
    return {"clase": "I", "codigo": CLASES["I"],
            "motivo": "sin evidencia clasificable: causa desconocida "
                      "(no se inventa)",
            "evidencia": raw[:300],
            "evidencia_estructura": estructura,
            "classification_confidence": "LOW",
            "fuente_evidencia": "sin_evidencia"}


# ── ADAPTAR (mínima, determinista, trazable, reversible) ─────────────────────

def _s1_identidad_a_visual(p1: str, contexto: dict) -> dict:
    """S1 — restricción de identidad/likeness (clase F en V1.1).

    Reencuadre preservando la intención visual: IDENTIDAD CREATIVA →
    descripción visual del avatar (ya existente: avatars.appearance o el
    image_prompt de la escena) → acción/posición/entorno/cámara (P1 con el
    nombre del personaje neutralizado). NO inventa identidad nueva, NO
    cambia personaje/historia, NO elimina características visuales.
    Requiere character_name + descripcion_visual en contexto; sin ellos NO
    aplica (fail-closed → FLOW_ADAPTATION_REQUIRED)."""
    nombre = (contexto.get("character_name") or "").strip()
    visual = (contexto.get("descripcion_visual") or "").strip()
    if not visual:
        return {"aplicada": False, "motivo":
                "S1 sin descripción visual existente del avatar: no se "
                "inventa identidad visual (FLOW_ADAPTATION_REQUIRED)"}
    p2 = ("Avatar ficticio — personaje imaginario de ficción, no "
          "corresponde a ninguna persona real. Descripción visual del "
          "avatar: " + visual + ". ")
    accion = (p1 or "").strip()
    reemplazo_nombre = None
    if nombre:
        patron = re.compile(r"\b" + re.escape(nombre) + r"\b", re.IGNORECASE)
        if patron.search(accion):
            accion = patron.sub("el personaje", accion)
            reemplazo_nombre = f"'{nombre}' → 'el personaje'"
    return {"aplicada": True, "estrategia": "S1", "p2": p2 + accion,
            "transformacion": ("reencuadre identidad→descripción visual "
                               "existente" + (f"; {reemplazo_nombre}" if
                                              reemplazo_nombre else
                                              "; el nombre no aparecía en P1")),
            "motivo": "preserva sujeto visual, acción, posición, entorno y "
                      "cámara; solo reencuadra la identidad como avatar "
                      "ficticio descrito visualmente"}


def _s2_camara_generica(p1: str, contexto: dict) -> dict:
    """S2 — ELIMINADA en V1.1.

    La taxonomía A-I ya no contiene la clase de 'interpretación de prompt'
    (la V3 la mapeaba a F PROMPT_INTERPRETATION_PROBLEM → S2). Sin clase con
    evidencia no hay estrategia segura: fail-closed → FLOW_ADAPTATION_REQUIRED.
    Se conserva el símbolo con este docstring para trazabilidad histórica
    (las baterías V3 documentaban su existencia)."""
    return {"aplicada": False, "motivo": _S2_ELIMINADA}


def adaptar_prompt(p1: str, clase: str, contexto: dict | None = None) -> dict:
    """Punto único de adaptación: SOLO si la clase tiene estrategia segura
    (F→S1 en V1.1). NUNCA preventiva: sin clase con evidencia → no aplica.
    C audio NUNCA toca el prompt visual (⑥); G copyright sin workaround (⑥)."""
    ctx = contexto or {}
    if clase == "F":
        return _s1_identidad_a_visual(p1 or "", ctx)
    return {"aplicada": False, "motivo":
            f"sin estrategia segura para la clase {clase}: "
            "no se toca el prompt creativo"}


# ── REINTENTAR (limitado y dependiente de la clasificación) ──────────────────

def decidir_reintento(clase: str | None, intentos: int, kind: str,
                      ya_adaptado: bool = False,
                      grants_previos: int = 0) -> dict:
    """Política de retry por clase. Límites duros: MAX_EXTRA_GRANTS por job
    (cualquier clase) + una sola adaptación P2 (guard en flow_jobs). Nunca
    DEAD inmediato (eso lo decide fail() con max_attempts del contrato) ni
    retry infinito (esta capa no concede más allá de MAX_EXTRA_GRANTS).

    Orden de evaluación (v1.1): 1) clases sin estrategia segura (D política,
    G copyright) emiten reporte FLOW_ADAPTATION_REQUIRED SIEMPRE —
    independiente de los grants; E (créditos) y H (actividad inusual) no
    reintentan (causa operacional, no de adaptación) sin reporte de
    adaptación; 2) si P2 ya se usó y falló → reporte SIEMPRE (la única
    adaptación se quemó); 3) recién entonces el límite de grants; 4)
    política de la clase."""
    pol = RETRY_POLICY.get(clase) if clase else None
    base = {"clase": clase, "reintentar": False, "adaptar": None,
            "otorgado": False, "motivo": pol["motivo"] if pol else
            "clase sin política"}
    if clase is None:
        base["motivo"] = "resultado válido: sin reintento"
        return base
    if kind != "video":
        base["motivo"] = "la capa solo interviene en video (imagen conserva " \
                         "su contrato propio)"
        return base
    if not pol.get("reintentar"):  # D/G: sin estrategia segura → reporte siempre
        if clase in ("D", "G"):
            base["reporte"] = FLOW_ADAPTATION_REQUIRED
        return base
    if ya_adaptado and pol.get("adaptar"):
        # F con P2 ya usado: la única adaptación se quemó → detener y
        # reportar (ANTES del límite de grants, para no perder la señal)
        base["motivo"] = (base["motivo"] + " — P2 ya se usó y falló: una "
                          "sola adaptación por job → reportar")
        base["reporte"] = FLOW_ADAPTATION_REQUIRED
        return base
    if grants_previos >= MAX_EXTRA_GRANTS:
        base["motivo"] = (base["motivo"] + " — LÍMITE: ya se concedió el "
                          "reencolar extra permitido para este job")
        if clase in ("D", "G", "I"):
            # fallo repetido sin más opciones: detenerse y reportar (mandato:
            # REPEATED FAILURE → detenerse y reportar)
            base["reporte"] = FLOW_ADAPTATION_REQUIRED
        return base
    base["reintentar"] = True
    base["adaptar"] = pol.get("adaptar")
    return base


# ── contexto creativo (SOLO LECTURA; jamás se escribe) ───────────────────────

def _flatten_appearance(appearance) -> str:
    """Aplana el JSON appearance del avatar (datos creativos EXISTENTES) a
    una descripción visual textual. Determinista; sin inventar nada."""
    if isinstance(appearance, str):
        try:
            appearance = json.loads(appearance)
        except (ValueError, TypeError):
            return appearance.strip()[:400] if appearance.strip() else ""
    if not isinstance(appearance, dict):
        return ""
    orden = [("piel", "piel"), ("ojos_color", "ojos"), ("ojos_forma", None),
             ("rostro", "rostro"), ("cabello_color", "cabello"),
             ("cabello_largo", None), ("cabello_textura", None),
             ("mechas", "mechas"), ("cuerpo", "cuerpo"), ("ropa", "ropa"),
             ("genero", None), ("edad", "edad")]
    partes = []
    for k, etiqueta in orden:
        v = appearance.get(k)
        if isinstance(v, str) and v.strip():
            partes.append(f"{etiqueta or k}: {v.strip()}")
    return ", ".join(partes)[:400]


def _flatten_visual(image_prompt) -> str:
    """Descripción visual desde el image_prompt de la escena (dict o str)."""
    if isinstance(image_prompt, str):
        return image_prompt.strip()[:400]
    if not isinstance(image_prompt, dict):
        return ""
    partes = []
    subj = image_prompt.get("subjects")
    if isinstance(subj, list) and subj:
        partes.append("; ".join(str(s) for s in subj if s))
    for fld in ("environment", "lighting", "composition", "style"):
        v = image_prompt.get(fld)
        if isinstance(v, str) and v.strip():
            partes.append(v.strip())
        elif isinstance(v, list) and v:
            partes.append("; ".join(str(x) for x in v if x))
    return " | ".join(p for p in partes if p)[:400]


def _contexto_creativo(row) -> dict:
    """Reúne, en SOLO LECTURA, los datos creativos ya existentes que S1
    necesita (nombre del personaje + descripción visual del avatar). Nunca
    escribe: scenes/projects/avatars quedan intactos."""
    ctx: dict = {}
    try:
        proj = db.get_project(row["project_id"])
        aid = (proj or {}).get("avatar_id")
        avatar = db.get_avatar(aid) if aid else None
        if avatar:
            ctx["character_name"] = (avatar.get("name") or "").strip()
            ctx["descripcion_visual"] = _flatten_appearance(
                avatar.get("appearance"))
    except Exception:  # noqa: BLE001 — fail-closed sin romper la capa
        pass
    if not ctx.get("descripcion_visual"):
        try:
            escenas = db.get_scenes(row["project_id"])
            no = int(row["scene_number"])
            sc = next((s for s in escenas
                       if int(s.get("idx", 0)) + 1 == no), None)
            if sc:
                ctx["descripcion_visual"] = _flatten_visual(
                    sc.get("image_prompt"))
        except Exception:  # noqa: BLE001
            pass
    return ctx


# ── VALIDAR → REGISTRAR: el ciclo completo sobre un job fallido ──────────────

def procesar_fallo_job(job_id: str) -> dict | None:
    """Ciclo operacional completo sobre un job de VIDEO que quedó dead.

    OBSERVAR (evidencia del job) → CLASIFICAR (A-I V1.1 solo con evidencia,
    prioridad ④) → ADAPTAR (S1 solo con F identidad Y datos existentes) →
    REINTENTAR
    (única reencola extra) → REGISTRAR (ledger JSONL). Devuelve la decisión
    (o None si el job no es elegible). NUNCA lanza hacia la cola."""
    con = db.connect()
    try:
        row = con.execute(
            "SELECT * FROM flow_jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["kind"] != "video" or row["status"] != "dead":
            return None
        p1 = row["prompt"] or ""
        evidencia = row["error"] or ""
        ya_adaptado = bool(row["prompt_adapted"])
        escena = int(row["scene_number"] or 0)
        intentos = int(row["attempts"] or 0)
    finally:
        con.close()

    # [observability v1.1] ③④: la marca de ventana LOCAL viene del TEXTO del
    # veredicto (watchdog:/timeout-local:/lease — composeEvidence), NO se
    # asume para todo job dead: un error explícito de Flow sin causa es B
    # (reintento limitado), no A. Sin texto → I (sin evidencia).
    cls = clasificar(evidencia, "video",
                     {"transitorio": False,
                      "ventana_agotada": bool(_WATCHDOG_RE.search(evidencia or "")),
                      "resultado_valido": False})
    decision = decidir_reintento(cls["clase"], intentos, "video",
                                 ya_adaptado=ya_adaptado,
                                 grants_previos=_grants_previos(job_id))
    registro = {
        "job_id": job_id, "kind": "video", "escena": escena,
        "prompt_original": p1,          # P1 queda registrado y intacto
        "evidencia_observada": cls.get("evidencia"),   # ⑩ capa CRUDA
        "evidencia_estructura": cls.get("evidencia_estructura"),  # ⑩ capas
        "clasificacion": cls["clase"], "codigo": cls["codigo"],
        "motivo_clasificacion": cls["motivo"],
        "classification_confidence": cls.get("classification_confidence"),
        "fuente_evidencia": cls.get("fuente_evidencia"),
        "transformacion": None, "prompt_adaptado": None,
        "resultado": None, "retry": decision, "otorgado": False,
    }

    if decision.get("reintentar"):
        estrategia = decision.get("adaptar")
        adaptado = None
        if estrategia in ("S1", "S2"):
            ctx = _contexto_creativo(row) if estrategia == "S1" else {}
            adaptado = adaptar_prompt(p1, cls["clase"], ctx)
        if estrategia in ("S1", "S2") and adaptado and adaptado["aplicada"]:
            from services import flow_jobs  # import perezoso (evita ciclo)
            r_set = flow_jobs.set_adapted_prompt(
                job_id, adaptado["p2"], motivo=cls["codigo"])
            r_rq = flow_jobs.requeue_for_adaptation(job_id)
            if r_set and r_rq:
                decision["accion"] = "reencolar_con_p2"
                decision["otorgado"] = True
                registro.update(transformacion=adaptado["transformacion"],
                                prompt_adaptado=adaptado["p2"],
                                resultado="pendiente (reencolado con P2)",
                                otorgado=True)
            else:
                decision["reintentar"] = False
                decision["accion"] = "detener"
                decision["reporte"] = FLOW_ADAPTATION_REQUIRED
                registro["resultado"] = (
                    "FLOW_ADAPTATION_REQUIRED (P2 ya existía o job no "
                    "elegible)")
        elif estrategia in ("S1", "S2"):
            # la estrategia existe pero no hubo datos seguros → fail-closed
            decision["reintentar"] = False
            decision["adaptar"] = None
            decision["accion"] = "detener"
            decision["reporte"] = FLOW_ADAPTATION_REQUIRED
            decision["motivo_no_adaptacion"] = (adaptado or {}).get("motivo")
            registro["resultado"] = FLOW_ADAPTATION_REQUIRED
        else:
            from services import flow_jobs  # A/G: reintento limitado con P1
            r_rq = flow_jobs.requeue_for_adaptation(job_id)
            if r_rq:
                decision["accion"] = "reencolar_sin_cambio"
                decision["otorgado"] = True
                registro["resultado"] = "pendiente (reencolado con P1)"
                registro["otorgado"] = True
            else:
                decision["accion"] = "detener"
                registro["resultado"] = "no se pudo reencolar"
    else:
        decision["accion"] = "detener" if decision.get("reporte") else \
            "sin_reintento"
        registro["resultado"] = decision.get("reporte") or \
            "sin reintento según política"

    _registrar(registro)
    return decision

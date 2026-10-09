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
  - NO inventa causas: la taxonomía A-G se asigna SOLO con evidencia
    observada (texto del rechazo/tiempo agotado). Sin evidencia → G UNKNOWN.
  - NO degrada silenciosamente el contenido creativo: si no existe una
    adaptación segura y determinista, reporta FLOW_ADAPTATION_REQUIRED y
    se detiene (política de escape del mandato).

P1 / P2 (separación inequívoca):
  P1 = prompt creativo original (flow_jobs.prompt, fuente única
       build_script_json) — NUNCA se sobrescribe.
  P2 = prompt adaptado SOLO para ejecución operacional en Flow
       (flow_jobs.prompt_adapted) — un único intento extra por job.

Memoria operacional (ledger JSONL, append-only): cada retry registra
  prompt_original, evidencia observada, clasificación, transformación,
  prompt_adaptado, resultado y retry. Sirve para priorizar adaptación,
  evitar estrategias ya fallidas y diagnosticar tendencias. Las
  observaciones son EVIDENCIA OPERACIONAL, no reglas universales: un fallo
  no demuestra "Flow nunca acepta esta palabra" ni un éxito "siempre la
  acepta". NO modifica Creative Engine, Niche Blueprint, narrativa ni
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

# Taxonomía del mandato (SOLO con evidencia; sin evidencia → G):
CLASES = {
    "A": "TRANSIENT_GENERATION_ERROR",
    "B": "GENERATION_TIMEOUT",
    "C": "CONTENT_POLICY_REJECTION",
    "D": "IDENTITY_OR_LIKENESS_RESTRICTION",
    "E": "COPYRIGHT_OR_PROTECTED_CONTENT_RESTRICTION",
    "F": "PROMPT_INTERPRETATION_PROBLEM",
    "G": "UNKNOWN_FLOW_FAILURE",
}

# Patrones operacionales observados en textos de rechazo de Flow. Son
# EVIDENCIA OPERACIONAL acumulable (el ledger permite extenderlos con datos
# reales), NO reglas universales. Matching case-insensitive por subcadena.
_PATRONES = {
    "C": ("politica", "política", "policy", "infringement",
          "bloqueo de politicas", "bloqueo de políticas", "content policy",
          "no permitido", "viola nuestras"),
    "D": ("persona real", "personas reales", "identidad", "likeness",
          "derechos de imagen", "imagen de una persona",
          "figura publica", "figura pública", "celebridad",
          "rostro de una persona"),
    "E": ("copyright", "derechos de autor", "material protegido",
          "marca registrada", "contenido protegido",
          "propiedad intelectual"),
    "F": ("no se pudo interpretar", "no pudimos interpretar",
          "interpretar el prompt", "interpretacion del prompt",
          "interpretación del prompt", "reformular", "reformula el prompt",
          "instruccion no clara", "instrucción no clara",
          "prompt no valido", "prompt no válido"),
}
# Prioridad de clasificación cuando el texto tocara varias clases:
_PRIORIDAD = ("C", "D", "E", "F")

# Patrones S2 (formulación de cámara/enfoque facial): solo se reescribe la
# CLÁUSULA de enfoque, preservando sujeto/orientación/acción/composición.
_S2_ENFOQUE_RE = re.compile(
    r"(enfoqu\w*|enfoca\w*|primer plano (del|de la|de el|de)?\s*(rostro|cara)"
    r"|close-?up|plano detalle|acerc\w+ (al|a el|hacia el|hacia la)\s*(rostro|cara))",
    re.IGNORECASE)
_S2_ROSTRO_RE = re.compile(r"(rostro|cara|semblante|facial)", re.IGNORECASE)
_S2_REEMPLAZO = "Plano medio estable, cámara fija, sujeto encuadrado de forma natural"

# Política de retry por clase (LÍMITES del mandato: ni DEAD inmediato ni
# retry infinito). `max_extra` = reencolas OTORGADAS por esta capa por job
# (en total, cualquier clase: el guardián es _grants_previos ≤ MAX_EXTRA_GRANTS).
RETRY_POLICY = {
    "A": {"reintentar": True, "adaptar": None, "motivo":
          "error transitorio de generación: reintento limitado con P1"},
    "B": {"reintentar": False, "adaptar": None, "motivo":
          "timeout de ventana: manda la ventana de video (el lease y "
          "recover_expired gestionan el requeue; no se concede extra)"},
    "C": {"reintentar": False, "adaptar": None, "motivo":
          "rechazo de política de contenido: no existe estrategia segura y "
          "determinista que no toque contenido creativo → reportar"},
    "D": {"reintentar": True, "adaptar": "S1", "motivo":
          "restricción de identidad/likeness: S1 reencuadra identidad → "
          "descripción visual del avatar (datos creativos existentes)"},
    "E": {"reintentar": False, "adaptar": None, "motivo":
          "restricción de copyright/contenido protegido: no existe "
          "estrategia segura y determinista → reportar"},
    "F": {"reintentar": True, "adaptar": "S2", "motivo":
          "problema de interpretación de formulación: S2 reescribe SOLO la "
          "cláusula de enfoque/cámara, preservando sujeto/orientación"},
    "G": {"reintentar": True, "adaptar": None, "motivo":
          "fallo desconocido: registrar + reintento limitado SIN inventar causa"},
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

def clasificar(evidencia: str, kind: str = "video",
               contexto: dict | None = None) -> dict:
    """Clasifica un fallo de Flow según la EVIDENCIA observada.

    contexto: {transitorio: bool (intento fallido con generación aún activa),
               ventana_agotada: bool, resultado_valido: bool}.
    Orden determinista: 1) texto explícito C/D/E/F por prioridad,
    2) timeout (B), 3) transitorio genérico (A), 4) desconocido (G).
    Un resultado válido NO es un fallo: {clase: None}."""
    ctx = contexto or {}
    texto = (evidencia or "").lower()
    if ctx.get("resultado_valido"):
        return {"clase": None, "codigo": "SUCCESS",
                "motivo": "hay resultado válido: no es un fallo",
                "evidencia": (evidencia or "")[:300]}
    for k in _PRIORIDAD:  # 1) evidencia textual explícita
        if any(pat in texto for pat in _PATRONES[k]):
            return {"clase": k, "codigo": CLASES[k],
                    "motivo": f"evidencia textual de clase {k} ({CLASES[k]})",
                    "evidencia": (evidencia or "")[:300]}
    if "timeout" in texto or "watchdog" in texto or "lease" in texto \
            or not texto:  # 2) tiempo agotado / sin texto
        return {"clase": "B", "codigo": CLASES["B"],
                "motivo": "ventana/tiempo agotado sin resultado y sin texto "
                          "de rechazo específico",
                "evidencia": (evidencia or "")[:300]}
    if ctx.get("transitorio"):  # 3) intento aislado, generación aún activa
        return {"clase": "A", "codigo": CLASES["A"],
                "motivo": "tile de error aislado con generación en curso y "
                          "sin texto clasificable",
                "evidencia": (evidencia or "")[:300]}
    # 4) hay texto pero no casa ningún patrón → jamás se inventa causa
    return {"clase": "G", "codigo": CLASES["G"],
            "motivo": "evidencia presente sin patrón conocido: causa "
                      "desconocida (no se inventa)",
            "evidencia": (evidencia or "")[:300]}


# ── ADAPTAR (mínima, determinista, trazable, reversible) ─────────────────────

def _s1_identidad_a_visual(p1: str, contexto: dict) -> dict:
    """S1 — restricción de identidad/likeness (clase D).

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
    """S2 — formulación de cámara/enfoque facial (clase F).

    Reescribe SOLO la cláusula de enfoque facial por una formulación
    genérica de composición, preservando sujeto, acción, orientación y
    continuidad (ej. mandato: 'enfoca directamente el rostro...' →
    'plano medio, cámara estable' + el resto verbatim)."""
    texto = (p1 or "").strip()
    if not texto:
        return {"aplicada": False, "motivo": "S2 sin P1 que adaptar"}
    partes = re.split(r"(?<=[.;\n])\s+", texto)
    salida, reemplazos = [], 0
    for parte in partes:
        if _S2_ENFOQUE_RE.search(parte) and _S2_ROSTRO_RE.search(parte):
            nueva = _S2_ENFOQUE_RE.sub(
                _S2_REEMPLAZO + " ", parte, count=1)
            # la cola de la cláusula enfocada (hasta la 1ª coma/punto) se
            # elimina; el resto de la frase (orientación, sujeto) queda.
            nueva = re.sub(
                _S2_REEMPLAZO + r" [^,.;]*", _S2_REEMPLAZO, nueva, count=1)
            salida.append(nueva)
            reemplazos += 1
        else:
            salida.append(parte)
    if not reemplazos:
        return {"aplicada": False, "motivo":
                "S2 sin cláusula de enfoque facial reconocible en P1: no se "
                "reescribe a ciegas (FLOW_ADAPTATION_REQUIRED)"}
    return {"aplicada": True, "estrategia": "S2", "p2": " ".join(salida),
            "transformacion": (f"{reemplazos} cláusula(s) de enfoque facial → "
                               "formulación genérica de composición"),
            "motivo": "preserva sujeto/orientación/composición/continuidad; "
                      "solo reformula la instrucción de cámara"}


def adaptar_prompt(p1: str, clase: str, contexto: dict | None = None) -> dict:
    """Punto único de adaptación: SOLO si la clase tiene estrategia segura
    (D→S1, F→S2). NUNCA preventiva: sin clase con evidencia → no aplica."""
    ctx = contexto or {}
    if clase == "D":
        return _s1_identidad_a_visual(p1 or "", ctx)
    if clase == "F":
        return _s2_camara_generica(p1 or "", ctx)
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

    Orden de evaluación (v1.1, auditoría v3-audit-backend): 1) clases sin
    estrategia (C/E) emiten reporte FLOW_ADAPTATION_REQUIRED SIEMPRE —
    independiente de los grants; 2) si P2 ya se usó y falló → reporte SIEMPRE
    (la única adaptación se quemó); 3) recién entonces el límite de grants;
    4) política de la clase."""
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
    if not pol.get("reintentar"):  # C/E: sin estrategia segura → reporte siempre
        if clase in ("C", "E"):
            base["reporte"] = FLOW_ADAPTATION_REQUIRED
        return base
    if ya_adaptado and pol.get("adaptar"):
        # D/F con P2 ya usado: la única adaptación se quemó → detener y
        # reportar (ANTES del límite de grants, para no perder la señal)
        base["motivo"] = (base["motivo"] + " — P2 ya se usó y falló: una "
                          "sola adaptación por job → reportar")
        base["reporte"] = FLOW_ADAPTATION_REQUIRED
        return base
    if grants_previos >= MAX_EXTRA_GRANTS:
        base["motivo"] = (base["motivo"] + " — LÍMITE: ya se concedió el "
                          "reencolar extra permitido para este job")
        if clase in ("C", "E", "G"):
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

    OBSERVAR (evidencia del job) → CLASIFICAR (A-G solo con evidencia) →
    ADAPTAR (S1/S2 solo si la clase lo permite Y hay datos) → REINTENTAR
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

    cls = clasificar(evidencia, "video",
                     {"transitorio": False, "ventana_agotada": True,
                      "resultado_valido": False})
    decision = decidir_reintento(cls["clase"], intentos, "video",
                                 ya_adaptado=ya_adaptado,
                                 grants_previos=_grants_previos(job_id))
    registro = {
        "job_id": job_id, "kind": "video", "escena": escena,
        "prompt_original": p1,          # P1 queda registrado y intacto
        "evidencia_observada": cls.get("evidencia"),
        "clasificacion": cls["clase"], "codigo": cls["codigo"],
        "motivo_clasificacion": cls["motivo"],
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

"""
Execution Contract V1.0 — spec de ejecución versionado por unidad de video.

Cierra el agujero documentado por la auditoría: `duration_target = 8` en el
Production JSON sobrevive al adapter y a flow_export, pero se PERDÍA al
construir el flow job (enqueue_project solo leía prompt/título) → la extensión
solo recibía el prompt → Flow conservaba su estado de UI (p. ej. 5s) → podía
generar 5s y el backend aceptaba el asset.

Este módulo define la TERCERA CAPA del contrato (junto a P1 prompt original
inmutable y P2 adaptación operacional):

    execution_spec = {"schema_version": "1.0", ...}

Reglas de oro (mandato FASE 7):
  - NO SE INVENTAN VALORES: si la fuente no especifica un control, queda
    `requested=None, required=False` (jamás un default cosmético).
  - El spec es una petición al proveedor, NUNCA una edición del prompt:
    P1 vive intacto en `flow_jobs.prompt` y este módulo jamás lo toca.
  - ERROR DE CONFIGURACIÓN != ADAPTACIÓN DE PROMPT: los veredictos
    CONFIG_UNSUPPORTED / CONFIG_UNVERIFIABLE / CONFIG_MISMATCH son terminales
    (ver flow_adaptation.py clases J/K/L).
  - JAMÁS se acepta estado heredado de la UI de Flow: para generar con un
    control `required=True` la última observación debe ser VERIFIED con el
    valor pedido (config_gate); si no, NO SE GENERA.
  - JAMÁS se marca DONE un job cuyo asset incumple el contrato
    (validate_asset_contract → CONTRACT_VIOLATION → ASSET_INVALID terminal).

Validación de asset (REQUESTED vs OBSERVED FLOW vs ACTUAL ASSET):
  - duration: |actual − requested| ≤ tolerance_seconds + TRANSPORT_EPSILON_S.
    El epsilon absorbe el redondeo del contenedor/ffprobe (un MP4 de 8s
    son 7.96–8.04s reales); NO es una política de tolerancia adicional:
    `tolerance_seconds` del spec manda (default 0, como pide el mandato).
  - aspect_ratio: comparación de w/h del asset contra el ratio pedido con
    tolerancia relativa 2% (dimensiones no cuadradas siempre redondean).
  - outputs/audio: se REGISTRAN (requested/observed/actual) sin gate duro:
    el transporte ya limita a 1 asset por job, y el audio nativo de Flow es
    OBSERVABLE, no exigible (observability V1.1: nunca asumir audio).

Consumidores: flow_jobs.enqueue_project (construcción), flow_jobs.complete
(validación contractual), flow_adaptation (clasificación J/K/L), extensión
(lectura del spec vía job JSON), tests deterministas.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.0"

# Absorbe redondeo de contenedor/ffprobe (ver docstring). Constante de
# transporte, no de política: `tolerance_seconds` del spec manda encima.
TRANSPORT_EPSILON_S = 0.25

# Tolerancia relativa para el ratio w/h del asset (rounding de dimensiones).
ASPECT_REL_TOLERANCE = 0.02

# Veredictos de configuración por control (espejo de hands.flow_controls).
VERIFIED = "VERIFIED"
SUPPORTED = "SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"
UNVERIFIABLE = "UNVERIFIABLE"
MISMATCH = "MISMATCH"

# Decisiones del gate.
ALLOW_GENERATE = "ALLOW_GENERATE"
CONFIG_UNSUPPORTED = "CONFIG_UNSUPPORTED"
CONFIG_UNVERIFIABLE = "CONFIG_UNVERIFIABLE"
CONFIG_MISMATCH = "CONFIG_MISMATCH"

# Veredictos contractuales del asset.
CONTRACT_OK = "CONTRACT_OK"
CONTRACT_VIOLATION = "CONTRACT_VIOLATION"
CONTRACT_UNVERIFIABLE = "CONTRACT_UNVERIFIABLE"

# Controles con presencia en el spec (orden de prioridad del gate).
CONTROLS = ("duration", "model", "aspect_ratio", "outputs", "audio",
            "resolution")

_RATIOS = {"9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1.0, "4:3": 4 / 3,
           "3:4": 3 / 4, "21:9": 21 / 9}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _control(requested: Any, required: bool) -> dict:
    return {"requested": requested, "required": bool(required)}


def _norm_ratio(v: Any) -> str | None:
    """Normaliza el formato del proyecto a un ratio 'W:H' conocido."""
    if not isinstance(v, str):
        return None
    s = v.strip().lower()
    if s in _RATIOS:
        return s
    if s in ("short", "vertical", "reel"):
        return "9:16"
    if s in ("long", "horizontal"):
        return "16:9"
    m = s.replace("aspect_ratio", "").replace("aspectratio", "").strip()
    return m if m in _RATIOS else None


def build_execution_spec(scene_entry: dict, *, kind: str,
                         project_format: Any = None) -> dict:
    """Construye el execution_spec de UN job desde la entrada de
    build_script_json (fuente única del transporte).

    - kind='video': duration.requested = entry["duration"] (resuelta por
      flow_export: production_unit.duration_target → duración de escena →
      VIDEO_SECONDS del export; es el valor TRANSPORTADO, no un invento).
    - kind='image': duration.requested = None (una imagen no tiene duración).
    - aspect_ratio: derivado del format del PROYECTO (short→9:16, long→16:9);
      required=True — el pipeline consume vertical para shorts; si el formato
      es desconocido queda None/required=False (honesto).
    - outputs.requested = 1: el pipeline consume EXACTAMENTE un asset por job
      (flow_jobs.complete guarda un solo Escena_NN_*; es un hecho del
      transporte, no una expectativa inventada).
    - model/resolution/audio: sin fuente en el Production JSON → None/false.
      (El audio del production_unit pertenece a la capa de audio FINAL del
      proyecto (TTS/ASMR), NO al audio nativo de Flow — §14 del mandato.)
    - references: lista transportada tal cual ([] si no hay — §15: transportar
      no es ejecutar; la configuración/observación real vive en capabilities).
    - start_frame/end_frame: sin contrato explícito → None.
    """
    kind = "video" if kind == "video" else "image"
    dur = None
    if kind == "video":
        try:
            d = float(scene_entry.get("duration"))
            dur = d if d > 0 else None
        except (TypeError, ValueError):
            dur = None

    ratio = _norm_ratio(project_format)
    refs = scene_entry.get("references")
    if not isinstance(refs, list):
        refs = []

    return {
        "schema_version": SCHEMA_VERSION,
        "duration": {
            "requested": dur,
            "required": kind == "video" and dur is not None,
            "tolerance_seconds": 0,
        },
        "model": _control(None, False),
        "aspect_ratio": _control(ratio, ratio is not None),
        "outputs": _control(1, True),
        "audio": _control(None, False),
        "resolution": _control(None, False),
        "references": refs,
        "start_frame": None,
        "end_frame": None,
        "compatibility_policy": {
            # §6: PROHIBIDO generar con estado heredado de la UI de Flow.
            "allow_inherited_state": False,
            "generate_requires_verified": True,
            # §10: un error de configuración jamás se "resuelve" reintentando
            # idéntico ni adaptando el prompt.
            "retry_on_config_error": False,
        },
        "verification": {
            "duration": {"method": "ffprobe", "tolerance_seconds": 0,
                         "transport_epsilon_s": TRANSPORT_EPSILON_S},
            "aspect_ratio": {"method": "ffprobe",
                             "relative_tolerance": ASPECT_REL_TOLERANCE},
            "audio": {"method": "ffprobe", "gate": "register_only"},
            "outputs": {"method": "transport"},
        },
    }


# ── gate de configuración (§6/§7/§8) ─────────────────────────────────────────

def _verdict_of(control_results: dict, control: str) -> str | None:
    r = control_results.get(control)
    if isinstance(r, dict):
        v = r.get("verdict")
        return v if isinstance(v, str) else None
    if isinstance(r, str):
        return r
    return None


def _norm_value(v: Any) -> str:
    """Normaliza un valor de control para comparación ('8s' ≈ 8, ' 9:16 ' ≈
    '9:16'). La UI de Flow suele renderizar unidades ('8s') donde el spec
    lleva el número puro — comparar SIN normalizar fabricaría MISMATCH
    falsos (exactamente lo que §6 prohíbe: el valor SÍ es el pedido)."""
    if v is None:
        return ""
    s = str(v).strip().lower()
    if s.endswith("s") and s[:-1].replace(".", "", 1).isdigit():
        s = s[:-1]
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else str(f)
    except ValueError:
        return s


def config_gate(spec: dict, capabilities: dict | None = None,
                control_results: dict | None = None) -> dict:
    """Decide si se puede generar según el spec y la evidencia de control.

    Regla (§6): para cada control `required=True` del spec, la ÚLTIMA
    observación debe ser VERIFIED con el valor pedido. En otro caso:
      UNSUPPORTED (el control no existe/no es editable) → CONFIG_UNSUPPORTED
      UNVERIFIABLE (no pudo releerse)               → CONFIG_UNVERIFIABLE
      MISMATCH (releído ≠ solicitado)               → CONFIG_MISMATCH
    Los controles required=False se REGISTRAN sin bloquear (§14/§15: no fingir
    ejecución; requested=None jamás exige configuración).

    `capabilities` y `control_results` llegan de la capa mecánica (extensión
    vía bridge, o hands.flow_controls.ConfigGate sobre un FlowControlAdapter).
    """
    caps = capabilities if isinstance(capabilities, dict) else {}
    results = control_results if isinstance(control_results, dict) else {}
    fallos: list[str] = []
    detalle: dict[str, dict] = {}
    for control in CONTROLS:
        c = spec.get(control)
        if not isinstance(c, dict):
            continue
        requested = c.get("requested")
        required = bool(c.get("required"))
        registro: dict[str, Any] = {
            "requested": requested, "required": required,
            "capability": (caps.get(control)
                           if isinstance(caps.get(control), dict) else None),
        }
        if requested is None:
            # Nada solicitado → nada que verificar (no se inventa exigencia).
            registro["verdict"] = VERIFIED if not required else UNVERIFIABLE
            if required and requested is None:
                # required sin requested no ocurre por construcción del spec;
                # si apareciera, es UNVERIFIABLE honesto, no un bloqueo falso.
                registro["verdict"] = UNVERIFIABLE
            detalle[control] = registro
            continue
        v = _verdict_of(results, control)
        registro["verdict"] = v or UNVERIFIABLE
        registro["observed"] = (results.get(control) or {}).get("observed") \
            if isinstance(results.get(control), dict) else None
        # Controles cuya verificación NO es pre-generación: outputs se
        # valida por transporte (1 asset por job, §13) y audio se REGISTRA
        # (register_only, §14 — el audio nativo de Flow es observable, no
        # exigible). Sin resultado en contra → REGISTERED, no bloquean.
        metodo = ((spec.get("verification") or {}).get(control) or {}) \
            .get("method")
        if metodo in ("transport", "register_only") \
                and v not in (MISMATCH, UNSUPPORTED):
            registro["verdict"] = v or "REGISTERED"
            detalle[control] = registro
            continue
        if required:
            if v == VERIFIED:
                obs = registro.get("observed")
                if obs is not None and _norm_value(obs) != _norm_value(requested):
                    # VERIFIED pero con valor distinto al pedido → MISMATCH
                    # (defensa en profundidad: la capa mecánica jamás debería
                    # declarar VERIFIED con otro valor).
                    registro["verdict"] = MISMATCH
                    fallos.append(f"{control}: CONFIG_MISMATCH "
                                  f"(requested={requested!r}, "
                                  f"observed={obs!r})")
                    detalle[control] = registro
                    continue
                detalle[control] = registro
                continue
            if v == UNSUPPORTED:
                fallos.append(f"{control}: CONFIG_UNSUPPORTED "
                              f"(requested={requested!r})")
            elif v == MISMATCH:
                obs = registro.get("observed")
                fallos.append(f"{control}: CONFIG_MISMATCH "
                              f"(requested={requested!r}, observed={obs!r})")
            else:
                registro["verdict"] = UNVERIFIABLE
                fallos.append(f"{control}: CONFIG_UNVERIFIABLE "
                              f"(requested={requested!r}, verdict={v!r})")
        detalle[control] = registro

    decision = ALLOW_GENERATE
    if fallos:
        import re as _re
        if any(_re.search(r"CONFIG_UNSUPPORTED", f) for f in fallos):
            decision = CONFIG_UNSUPPORTED
        elif any(_re.search(r"CONFIG_MISMATCH", f) for f in fallos):
            decision = CONFIG_MISMATCH
        else:
            decision = CONFIG_UNVERIFIABLE
    return {"decision": decision, "detail": "; ".join(fallos),
            "control_results": detalle}


def gate_error_prefix(decision: str) -> str:
    """Prefijo de error estructurado para bridgeFail/fail() — el texto que
    flow_adaptation.clasificar() reconoce como clase J/K/L (§10)."""
    return f"{decision}: "


# ── validación contractual del asset (§13) ───────────────────────────────────

def _ratio_from_wh(w: Any, h: Any) -> float | None:
    try:
        w_f, h_f = float(w), float(h)
        if w_f <= 0 or h_f <= 0:
            return None
        return w_f / h_f
    except (TypeError, ValueError):
        return None


def validate_asset_contract(spec: dict, *, actual: dict,
                            observed: dict | None = None,
                            outputs_count: int | None = None) -> dict:
    """Compara REQUESTED vs OBSERVED FLOW vs ACTUAL ASSET tras la descarga.

    - `actual`: medición REAL del asset con ffprobe
      ({"duration": float|None, "width": int|None, "height": int|None,
        "has_audio": bool|None}). duration None/0 → check UNVERIFIABLE
      (probe_duration() devuelve 0.0 en fallo: nunca se interpreta como 0s).
    - `observed`: última observación de Flow (evidencia de configuración,
      p. ej. {"duration": "8s", "aspect_ratio": "9:16"}); se REGISTRA y
      participa en el informe, pero el gate duro es el asset real (§13).
    - `outputs_count`: nº de assets recibidos para el job (transporte).

    Devuelve contract_result (JSON serializable, persistido en
    flow_jobs.contract_result) con veredicto global CONTRACT_OK /
    CONTRACT_VIOLATION / CONTRACT_UNVERIFIABLE. UNVERIFIABLE global solo si
    un check REQUIRED no pudo medirse; un check opcional no medido se
    registra sin bloquear.
    """
    checks: dict[str, Any] = {}
    violaciones: list[str] = []
    no_verificados: list[str] = []
    obs = observed if isinstance(observed, dict) else {}

    # ── duration ─────────────────────────────────────────────────────────
    dur_spec = spec.get("duration") or {}
    req = dur_spec.get("requested")
    if req is not None:
        tol = float(dur_spec.get("tolerance_seconds") or 0)
        actual_d = actual.get("duration")
        try:
            actual_f = float(actual_d) if actual_d is not None else None
        except (TypeError, ValueError):
            actual_f = None
        if actual_f is None or actual_f <= 0:
            checks["duration"] = {
                "requested": req, "observed_flow": obs.get("duration"),
                "actual": actual_d, "tolerance_seconds": tol,
                "verdict": UNVERIFIABLE,
                "detail": "ffprobe no pudo medir la duración del asset",
            }
            if dur_spec.get("required"):
                no_verificados.append("duration")
        else:
            margen = tol + TRANSPORT_EPSILON_S
            delta = abs(actual_f - float(req))
            ok = delta <= margen
            checks["duration"] = {
                "requested": req, "observed_flow": obs.get("duration"),
                "actual": actual_f, "tolerance_seconds": tol,
                "transport_epsilon_s": TRANSPORT_EPSILON_S, "delta": round(delta, 3),
                "verdict": VERIFIED if ok else MISMATCH,
                "detail": "" if ok else
                f"duración real {actual_f:.2f}s != solicitada {req}s "
                f"(margen {margen:.2f}s)",
            }
            if not ok:
                violaciones.append(f"duration: {actual_f:.2f}s != {req}s")
    else:
        checks["duration"] = {"requested": None, "verdict": "NOT_REQUESTED"}

    # ── aspect_ratio ─────────────────────────────────────────────────────
    asp_spec = spec.get("aspect_ratio") or {}
    req_ratio = asp_spec.get("requested")
    if req_ratio:
        target = _RATIOS.get(str(req_ratio))
        w, h = actual.get("width"), actual.get("height")
        asset_ratio = _ratio_from_wh(w, h)
        if target is None or asset_ratio is None:
            checks["aspect_ratio"] = {
                "requested": req_ratio, "actual": [w, h],
                "verdict": UNVERIFIABLE,
                "detail": "dimensiones del asset no medibles",
            }
            if asp_spec.get("required"):
                no_verificados.append("aspect_ratio")
        else:
            rel = abs(asset_ratio - target) / target
            ok = rel <= ASPECT_REL_TOLERANCE
            checks["aspect_ratio"] = {
                "requested": req_ratio,
                "observed_flow": obs.get("aspect_ratio"),
                "actual": {"width": w, "height": h,
                           "ratio": round(asset_ratio, 4)},
                "relative_delta": round(rel, 4),
                "verdict": VERIFIED if ok else MISMATCH,
                "detail": "" if ok else
                f"ratio del asset {asset_ratio:.4f} != {req_ratio} "
                f"({target:.4f})",
            }
            if not ok:
                violaciones.append(
                    f"aspect_ratio: {asset_ratio:.4f} != {req_ratio}")
    else:
        checks["aspect_ratio"] = {"requested": None, "verdict": "NOT_REQUESTED"}

    # ── outputs (registro; el transporte ya limita a 1 asset/job) ────────
    out_spec = spec.get("outputs") or {}
    if out_spec.get("requested") is not None:
        n = outputs_count if outputs_count is not None else 1
        ok = n == int(out_spec["requested"])
        checks["outputs"] = {
            "requested": out_spec["requested"], "actual": n,
            "verdict": VERIFIED if ok else MISMATCH,
            "detail": "" if ok else f"assets recibidos {n} != "
                                    f"{out_spec['requested']}",
        }
        if not ok:
            violaciones.append(f"outputs: {n} != {out_spec['requested']}")

    # ── audio: registro sin gate (requested None ⇒ nunca exigido) ────────
    checks["audio"] = {
        "requested": (spec.get("audio") or {}).get("requested"),
        "observed_flow": obs.get("audio"),
        "asset_native_audio": actual.get("has_audio"),
        "final_project_audio": None,  # capa final (TTS/render), fuera del job
        "verdict": "REGISTERED",
    }

    # ── referencias: registro honesto (§15: transportadas ≠ ejecutadas) ──
    checks["references"] = {
        "requested": len(spec.get("references") or []),
        "configured": None, "observed": None, "validated": None,
        "verdict": (VERIFIED if not (spec.get("references") or [])
                    else UNVERIFIABLE),
        "detail": "" if not (spec.get("references") or []) else
        "referencias transportadas; Flow no expone verificación determinista "
        "de su uso (no se fingir ejecución)",
    }

    if violaciones:
        verdict = CONTRACT_VIOLATION
    elif no_verificados:
        verdict = CONTRACT_UNVERIFIABLE
    else:
        verdict = CONTRACT_OK
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": verdict,
        "checked_at": _now_iso(),
        "requested": {c: (spec.get(c) or {}).get("requested")
                      for c in CONTROLS},
        "observed_flow": dict(obs),
        "actual_asset": {k: actual.get(k) for k in
                         ("duration", "width", "height", "has_audio")},
        "checks": checks,
        "violations": violaciones,
        "unverifiable": no_verificados,
        "summary": ("CONTRACT_VIOLATION: " + "; ".join(violaciones))
                   if violaciones else
                   ("CONTRACT_UNVERIFIABLE: " + "; ".join(no_verificados))
                   if no_verificados else "CONTRACT_OK",
    }


def probe_asset(path) -> dict:
    """Medición REAL del asset con ffprobe (video_qa._ffprobe_json).

    Devuelve {"duration", "width", "height", "has_audio"}; los valores no
    medibles son None (nunca 0 — un probe fallido es UNVERIFIABLE, no cero:
    `probe_duration()` del pipeline devuelve 0.0 en fallo y aquí jamás se
    interpreta como "0 segundos de video").
    """
    data = None
    try:
        from services.video_qa import _ffprobe_json
        data = _ffprobe_json(str(path))
    except Exception:  # noqa: BLE001 — un probe fallido es honesto: None
        data = None
    if not isinstance(data, dict):
        return {"duration": None, "width": None, "height": None,
                "has_audio": None}
    duration = None
    try:
        duration = float((data.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    vstream = astream = None
    for st in data.get("streams") or []:
        ct = st.get("codec_type")
        if ct == "video" and vstream is None:
            vstream = st
        elif ct == "audio" and astream is None:
            astream = st
    return {
        "duration": duration,
        "width": (vstream or {}).get("width"),
        "height": (vstream or {}).get("height"),
        "has_audio": (True if astream else False) if vstream is not None
                     else None,
    }


def contract_error_prefix(result: dict) -> str:
    """Prefijo de error estructurado para fail()/clasificar (ASSET_INVALID)."""
    return f"ASSET_INVALID: {result.get('summary', 'CONTRACT_VIOLATION')} " \
           f"[{result.get('verdict')}]"


# ── máquina de estados finos (§9) ────────────────────────────────────────────

EXEC_STATE_QUEUED = "QUEUED"
EXEC_STATE_CLAIMED = "CLAIMED"
EXEC_STATE_TAB_READY = "FLOW_TAB_READY"
EXEC_STATE_CAPS = "CAPABILITIES_CAPTURED"
EXEC_STATE_CONFIGURED = "CONTROLS_CONFIGURED"
EXEC_STATE_VERIFIED = "CONTROLS_VERIFIED"
EXEC_STATE_SUBMITTED = "GENERATION_SUBMITTED"
EXEC_STATE_OBSERVED = "GENERATION_OBSERVED"
EXEC_STATE_DOWNLOADED = "ASSET_DOWNLOADED"
EXEC_STATE_ASSET_OK = "ASSET_VALIDATED"
EXEC_STATE_CONTRACT_OK = "CONTRACT_VALIDATED"
EXEC_STATE_DONE = "DONE"

# Terminales (§9): el job NO continúa; jamás pasan a DONE.
EXEC_STATE_CONFIG_UNSUPPORTED = "CONFIG_UNSUPPORTED"
EXEC_STATE_CONFIG_UNVERIFIABLE = "CONFIG_UNVERIFIABLE"
EXEC_STATE_CONFIG_MISMATCH = "CONFIG_MISMATCH"
EXEC_STATE_PROVIDER_FAILURE = "PROVIDER_FAILURE"
EXEC_STATE_ASSET_INVALID = "ASSET_INVALID"
EXEC_STATE_DEAD = "DEAD"

TERMINAL_EXEC_STATES = {
    EXEC_STATE_CONFIG_UNSUPPORTED, EXEC_STATE_CONFIG_UNVERIFIABLE,
    EXEC_STATE_CONFIG_MISMATCH, EXEC_STATE_PROVIDER_FAILURE,
    EXEC_STATE_ASSET_INVALID, EXEC_STATE_DEAD,
}

# Progreso lineal permitido (desde → hacia). El progreso NUNCA retrocede
# (un informe antiguo de un intento previo jamás rebobina el estado — §12:
# evidencia por intento, sin mezcla).
_EXEC_PROGRESO = {
    None: {EXEC_STATE_QUEUED, EXEC_STATE_TAB_READY, EXEC_STATE_CAPS,
           EXEC_STATE_CONFIGURED, EXEC_STATE_VERIFIED, EXEC_STATE_SUBMITTED,
           EXEC_STATE_OBSERVED, EXEC_STATE_DOWNLOADED, EXEC_STATE_ASSET_OK},
    EXEC_STATE_QUEUED: {EXEC_STATE_CLAIMED, EXEC_STATE_TAB_READY,
                        EXEC_STATE_CAPS, EXEC_STATE_CONFIGURED,
                        EXEC_STATE_VERIFIED, EXEC_STATE_SUBMITTED},
    EXEC_STATE_CLAIMED: {EXEC_STATE_TAB_READY},
    EXEC_STATE_TAB_READY: {EXEC_STATE_CAPS},
    EXEC_STATE_CAPS: {EXEC_STATE_CONFIGURED, EXEC_STATE_VERIFIED,
                      EXEC_STATE_SUBMITTED},
    EXEC_STATE_CONFIGURED: {EXEC_STATE_VERIFIED, EXEC_STATE_SUBMITTED},
    EXEC_STATE_VERIFIED: {EXEC_STATE_SUBMITTED},
    EXEC_STATE_SUBMITTED: {EXEC_STATE_OBSERVED, EXEC_STATE_DOWNLOADED,
                           EXEC_STATE_ASSET_OK},
    EXEC_STATE_OBSERVED: {EXEC_STATE_DOWNLOADED, EXEC_STATE_ASSET_OK},
    EXEC_STATE_DOWNLOADED: {EXEC_STATE_ASSET_OK},
    EXEC_STATE_ASSET_OK: set(),
    EXEC_STATE_CONTRACT_OK: {EXEC_STATE_DONE},
}

# Estados finos válidos para informe de progreso desde la extensión.
REPORTABLE_EXEC_STATES = set(_EXEC_PROGRESO) | {
    EXEC_STATE_CONFIG_UNSUPPORTED, EXEC_STATE_CONFIG_UNVERIFIABLE,
    EXEC_STATE_CONFIG_MISMATCH, EXEC_STATE_PROVIDER_FAILURE,
}


def progress_allowed(current: str | None, target: str) -> bool:
    """¿Es legal reportar `target` estando en `current`?

    Permite saltos hacia adelante (la extensión puede reportar tarde, p. ej.
    CAPABILITIES_CAPTURED→GENERATION_SUBMITTED) y estados terminales de
    configuración/fallo desde CUALQUIER estado no terminal. Jamás retrocede.
    """
    if target in TERMINAL_EXEC_STATES or target == EXEC_STATE_DEAD:
        return True
    if current in TERMINAL_EXEC_STATES:
        return False
    permitidos = _EXEC_PROGRESO.get(current, set())
    # Regla lineal: el índice del target debe ser MAYOR que el actual.
    orden = [EXEC_STATE_QUEUED, EXEC_STATE_CLAIMED, EXEC_STATE_TAB_READY,
             EXEC_STATE_CAPS, EXEC_STATE_CONFIGURED, EXEC_STATE_VERIFIED,
             EXEC_STATE_SUBMITTED, EXEC_STATE_OBSERVED, EXEC_STATE_DOWNLOADED,
             EXEC_STATE_ASSET_OK, EXEC_STATE_CONTRACT_OK, EXEC_STATE_DONE]
    if target not in orden or current not in orden + [None]:
        return False
    idx_cur = orden.index(current) if current else -1
    idx_tgt = orden.index(target)
    return idx_tgt > idx_cur and (target in permitidos or idx_tgt > 0)


def is_config_terminal(exec_state: str | None) -> bool:
    """True para los 3 estados terminales de configuración (§10: jamás se
    convierten en adaptación de prompt ni en reintentos)."""
    return exec_state in (EXEC_STATE_CONFIG_UNSUPPORTED,
                          EXEC_STATE_CONFIG_UNVERIFIABLE,
                          EXEC_STATE_CONFIG_MISMATCH)


def spec_summary(spec: dict | None) -> str:
    """Resumen de una línea para logs/errores (jamás sustituye al spec crudo)."""
    if not isinstance(spec, dict):
        return "execution_spec: null"
    d = (spec.get("duration") or {}).get("requested")
    a = (spec.get("aspect_ratio") or {}).get("requested")
    o = (spec.get("outputs") or {}).get("requested")
    return (f"execution_spec v{spec.get('schema_version')} "
            f"duration={d} aspect={a} outputs={o}")

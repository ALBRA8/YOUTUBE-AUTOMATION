"""
MemoryDV — memoria aislada del dominio YOUTUBE-AUTOMATION (§8–§9 del contrato).

Almacén JSONL append-only por TIPO de memoria (EPISODIC / SEMANTIC /
PROCEDURAL / FACTUAL) más ``candidates.jsonl`` (candidatos de aprendizaje
pendientes de validación/promoción), todo bajo ``backend/data/memorydv/``.

Ciclo de vida (§9 — consolidación):
    observación (EPISODIC, provenance="observed")
      → consolidate() agrupa por (scope, causa normalizada = primeros 60
        caracteres de content en minúsculas); un grupo con >= min_pattern
        miembros y confianza media >= min_confidence genera un learning
        candidate (SKILL_CANDIDATE|SEMANTIC_CANDIDATE) y marca sus
        observaciones como status="candidate" (jamás se borran).
      → validate_candidate("valid", regression_test=...) promueve a memoria
        SEMANTIC (o PROCEDURAL si el candidato es SKILL_CANDIDATE) con
        provenance="promoted", truth_level="verified" y confidence=0.9,
        SOLO si la prueba de regresión existe bajo tests/ (§11).
      → validate_candidate("invalid") retira el candidato y devuelve las
        observaciones a status="active" sin crear promoción.

Aislamiento (§8):
  · DOMAIN_TAG fuerza ``domain="youtube_automation"`` en TODA memoria,
    ignore lo que intente escribir el llamador (parámetro extra incluido).
  · Esta memoria está AISLADA al dominio YOUTUBE-AUTOMATION: NO sirve como
    memoria general de otros agentes ni de otros dominios.

Límite duro (§11):
  · MemoryDV solo OBSERVA y propone; NUNCA escribe código ni configura el
    pipeline ni toca proveedores. Toda promoción SEMANTIC/PROCEDURAL sin
    evidencia de regresión exige aprobación humana (needs_human_approval).

Storage y tolerancia:
  · Escritura = append de una línea JSON (ensure_ascii=False). Las
    actualizaciones (utilidad, decaimiento, estados) reescriben el fichero
    conservando verbatim cualquier línea corrupta: una línea rota jamás
    tumba una consulta y stats() la cuenta como "corrupted_lines".

Parcheabilidad (tests herméticos): el directorio se resuelve SIEMPRE dentro
de las funciones vía _dir() leyendo el atributo de módulo MEMORY_DIR;
reasignar ``memorydv.MEMORY_DIR`` antes de la primera llamada redirige todo
el storage (el valor de import es solo el default, nunca queda ligado).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "DOMAIN_TAG", "AGENT_ID", "MEMORY_DIR", "TYPES", "SCOPES",
    "PROVENANCES", "TRUTH_LEVELS", "STATUSES", "CONTRACT_FIELDS",
    "record_episode", "record_observation", "record_fact", "query",
    "candidates", "consolidate", "validate_candidate",
    "needs_human_approval", "apply_decay", "stats",
]

# ── Contrato (§8): constantes del dominio ──────────────────────────────
DOMAIN_TAG = "youtube_automation"   # TODA memoria pertenece a ESTE dominio
AGENT_ID = "youtube-automation"

# Default de import; los tests reasignan este atributo (parche hermético).
MEMORY_DIR = Path(__file__).resolve().parent.parent / "data" / "memorydv"

TYPES = ("EPISODIC", "SEMANTIC", "PROCEDURAL", "FACTUAL")
SCOPES = ("production", "provider", "qa", "publish", "queue", "system")
PROVENANCES = ("observed", "recorded", "promoted", "manual")
TRUTH_LEVELS = ("observed_once", "pattern", "verified", "canonical")
STATUSES = ("active", "candidate", "retired", "superseded")

# Los 18 campos del contrato presentes en TODA memoria.
CONTRACT_FIELDS = (
    "memory_id", "agent_id", "domain", "type", "content", "source",
    "evidence", "provenance", "confidence", "truth_level", "created_at",
    "updated_at", "last_verified", "relevance", "utility", "decay",
    "scope", "status",
)

_FILES = {
    "EPISODIC": "episodic.jsonl",
    "SEMANTIC": "semantic.jsonl",
    "PROCEDURAL": "procedural.jsonl",
    "FACTUAL": "factual.jsonl",
}
_CANDIDATES_FILE = "candidates.jsonl"

_REPO_ROOT = Path(__file__).resolve().parents[2]   # …/yt_automation_v2
_UMBRAL_RETIRO = 0.05                              # relevance < umbral → retired

# Heurística: causa con verbos de acción → candidato de habilidad (PROCEDURAL).
_SKILL_RE = re.compile(
    r"\b(usar|usa|configur\w*|reintent\w*|retry|fallback|esperar|pausa\w*|"
    r"limitar|reducir|aumentar|evitar|aplicar|cambiar|activar|desactivar|"
    r"pasos?|primero|luego|despu[eé]s)\b",
    re.IGNORECASE,
)


# ═══════════════════════════ helpers internos ══════════════════════════
def _dir() -> Path:
    """Directorio de storage resuelvo EN CALL TIME (parcheable por tests)."""
    return Path(MEMORY_DIR)


def _now() -> str:
    """Timestamp ISO-8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def _f(valor, default: float = 0.0) -> float:
    """float defensivo: nunca lanza por basura del llamador o del disco."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        return default


def _clamp01(valor, default: float) -> float:
    """Clampa a [0, 1] con default si el valor no es numérico."""
    return round(min(1.0, max(0.0, _f(valor, default))), 6)


def _causa_normalizada(contenido: str) -> str:
    """Causa normalizada (§9): primeros 60 chars de content en minúsculas."""
    return contenido.lower().strip()[:60]


def _norm_evidence(evidence) -> list:
    """Normaliza evidencia a lista de {kind, ref, observed_at} (defensivo)."""
    if evidence is None:
        return []
    items = evidence if isinstance(evidence, (list, tuple)) else [evidence]
    out = []
    for ev in items:
        if not isinstance(ev, dict):
            continue
        e = dict(ev)
        e["kind"] = str(e.get("kind") or "ref")
        e["ref"] = str(e.get("ref") or "")
        e.setdefault("observed_at", _now())
        out.append(e)
    return out


def _evidencia_agregada(miembros: list) -> list:
    """Une la evidencia de un grupo sin duplicados (clave kind+ref)."""
    vistas = set()
    out = []
    for m in miembros:
        for ev in (m.get("evidence") or []):
            if not isinstance(ev, dict):
                continue
            clave = (str(ev.get("kind")), str(ev.get("ref")))
            if clave in vistas:
                continue
            vistas.add(clave)
            out.append(dict(ev))
    return out


def _new_memory(tipo: str, contenido, *, source, scope, evidence,
                provenance, confidence, truth_level, decay: float = 0.98,
                relevance: float = 1.0, status: str = "active") -> dict:
    """Fabrica un registro con los 18 campos del contrato (§8)."""
    ahora = _now()
    return {
        "memory_id": uuid.uuid4().hex[:16],
        "agent_id": AGENT_ID,
        "domain": DOMAIN_TAG,                 # §8: forzado, inmune al llamador
        "type": tipo if tipo in TYPES else "EPISODIC",
        "content": str(contenido if contenido is not None else ""),
        "source": str(source).strip() if source else "manual",
        "evidence": _norm_evidence(evidence),
        "provenance": provenance if provenance in PROVENANCES else "recorded",
        "confidence": _clamp01(confidence, 1.0),
        "truth_level": (truth_level if truth_level in TRUTH_LEVELS
                        else "observed_once"),
        "created_at": ahora,
        "updated_at": ahora,
        "last_verified": ahora,
        "relevance": _clamp01(relevance, 1.0),
        "utility": 0.0,
        "decay": _clamp01(decay, 0.98),
        "scope": scope if scope in SCOPES else "system",
        "status": status if status in STATUSES else "active",
    }


def _read_path(ruta: Path):
    """Lee un JSONL tolerante: (registros, lineas_corruptas_verbatim)."""
    registros: list = []
    corruptas: list = []
    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return registros, corruptas
    for linea in texto.splitlines():
        limpio = linea.strip()
        if not limpio:
            continue
        try:
            obj = json.loads(limpio)
        except ValueError:
            corruptas.append(limpio)
            continue
        if isinstance(obj, dict):
            registros.append(obj)
        else:
            corruptas.append(limpio)
    return registros, corruptas


def _read(tipo: str):
    return _read_path(_dir() / _FILES[tipo])


def _read_candidates():
    return _read_path(_dir() / _CANDIDATES_FILE)


def _append(tipo: str, record: dict) -> None:
    """Escritura del contrato: append de UNA línea JSON (ensure_ascii=False)."""
    ruta = _dir() / _FILES[tipo]
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_all(tipo: str, registros: list, corruptas: list) -> None:
    """Reescritura (solo para updates) preservando líneas corruptas verbatim."""
    ruta = _dir() / _FILES[tipo]
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as fh:
        for r in registros:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        for linea in corruptas:
            fh.write(linea + "\n")


def _write_candidates(registros: list, corruptas: list) -> None:
    ruta = _dir() / _CANDIDATES_FILE
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as fh:
        for r in registros:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        for linea in corruptas:
            fh.write(linea + "\n")


def _set_observations(ids, *, status: str, truth_level=None) -> int:
    """Actualiza status/truth_level de observaciones por memory_id. → nº tocadas."""
    if not ids:
        return 0
    buscados = {str(i) for i in ids if i}
    registros, corruptas = _read("EPISODIC")
    ahora = _now()
    n = 0
    for r in registros:
        if r.get("memory_id") in buscados:
            r["status"] = status
            if truth_level:
                r["truth_level"] = truth_level
            r["updated_at"] = ahora
            n += 1
    if n:
        _write_all("EPISODIC", registros, corruptas)
    return n


def _exigir_regresion(ref) -> str:
    """§11: la regresión debe existir y vivir bajo tests/ — si no, ValueError."""
    texto = str(ref or "").strip()
    if not texto:
        raise ValueError("promoción exige regresión: regression_test vacío")
    ruta = Path(texto)
    if not ruta.is_absolute():
        ruta = _REPO_ROOT / ruta
    ruta = ruta.resolve()
    raiz_tests = (_REPO_ROOT / "tests").resolve()
    if ruta != raiz_tests and raiz_tests not in ruta.parents:
        raise ValueError(
            f"promoción exige regresión: '{texto}' debe vivir bajo tests/ "
            f"(recibido fuera del árbol de pruebas)")
    if not ruta.exists():
        raise ValueError(
            f"promoción exige regresión: la prueba '{texto}' no existe "
            f"(no se promueve memoria verificada sin regresión real)")
    return str(ruta)


# ═══════════════════════════ API pública ═══════════════════════════════
def record_episode(content, *, source, scope="production", evidence=None,
                   confidence=1.0, extra=None) -> dict:
    """Registra una EJECUCIÓN CONCRETA (EPISODIC, provenance="recorded").

    Para ejecuciones puntuales de la fábrica: production_id, execution_id,
    step, error, result… se pasan en ``extra`` (dict fusionado; los campos
    nucleares del contrato — memory_id/domain/type/created_at — son
    inmunes al llamador, §8).
    """
    rec = _new_memory("EPISODIC", content, source=source, scope=scope,
                      evidence=evidence, provenance="recorded",
                      confidence=confidence, truth_level="observed_once")
    if isinstance(extra, dict):
        for clave, valor in extra.items():
            if clave in ("memory_id", "domain", "type", "created_at"):
                continue
            rec[clave] = valor
    rec["domain"] = DOMAIN_TAG            # refuerzo final del aislamiento §8
    _append("EPISODIC", rec)
    return dict(rec)


def record_observation(content, *, source, scope="provider", evidence=None,
                       confidence=0.6) -> dict:
    """Registra una OBSERVACIÓN cruda (EPISODIC, provenance="observed").

    Es la materia prima de consolidate(): fallos de proveedor, comportamientos
    repetidos, señales débiles. Confianza por defecto 0.6 (no es un hecho).
    """
    rec = _new_memory("EPISODIC", content, source=source, scope=scope,
                      evidence=evidence, provenance="observed",
                      confidence=confidence, truth_level="observed_once")
    _append("EPISODIC", rec)
    return dict(rec)


def record_fact(content, *, source, scope="system", evidence=None) -> dict:
    """Registra un HECHO verificable de proveedor/formato/error (FACTUAL)."""
    rec = _new_memory("FACTUAL", content, source=source, scope=scope,
                      evidence=evidence, provenance="recorded",
                      confidence=1.0, truth_level="observed_once")
    _append("FACTUAL", rec)
    return dict(rec)


def query(mem_type=None, scope=None, text=None, limit=20) -> list:
    """Recupera memorias ACTIVAS ordenadas por relevancia (desc).

    Filtros combinables: tipo (EPISODIC|SEMANTIC|PROCEDURAL|FACTUAL), scope
    y substring de texto sobre content (case-insensitive). ``limit`` acota
    el resultado (None = sin límite). Toda memoria devuelta cuenta como
    recuperada Y usada → utility += 1.0 persistido en el JSONL.
    """
    tipos = list(_FILES)
    if mem_type is not None:
        t = str(mem_type).strip().upper()
        if t not in _FILES:
            return []
        tipos = [t]
    if limit is None:
        limite = None
    else:
        try:
            limite = max(0, int(limit))
        except (TypeError, ValueError):
            limite = 20
    texto_busqueda = str(text).casefold() if text is not None else None
    scope_busqueda = str(scope) if scope is not None else None

    por_tipo: dict = {}
    encontrados: list = []
    for tipo in tipos:
        registros, corruptas = _read(tipo)
        por_tipo[tipo] = (registros, corruptas)
        for r in registros:
            if r.get("status") != "active":
                continue
            if scope_busqueda and r.get("scope") != scope_busqueda:
                continue
            if (texto_busqueda
                    and texto_busqueda not in str(r.get("content") or "").casefold()):
                continue
            encontrados.append((tipo, r))
    encontrados.sort(key=lambda tr: (
        -_f(tr[1].get("relevance"), 0.0),
        -_f(tr[1].get("utility"), 0.0),
        str(tr[1].get("created_at") or ""),
    ))
    if limite is not None:
        encontrados = encontrados[:limite]

    # Bump de utilidad persistido (la memoria sirvió: retrieved AND used).
    usados = {r.get("memory_id") for _, r in encontrados}
    for tipo, (registros, corruptas) in por_tipo.items():
        cambio = False
        for r in registros:
            if r.get("memory_id") in usados:
                r["utility"] = round(_f(r.get("utility"), 0.0) + 1.0, 6)
                r["updated_at"] = _now()
                cambio = True
        if cambio:
            _write_all(tipo, registros, corruptas)
    return [dict(r) for _, r in encontrados]


def candidates() -> list:
    """Devuelve todos los learning candidates del fichero (cualquier status)."""
    cands, _ = _read_candidates()
    return [dict(c) for c in cands]


def consolidate(min_pattern=3, min_confidence=0.75) -> dict:
    """Consolidación (§9): observaciones repetidas → learning candidate.

    Agrupa EPISODIC con provenance="observed" (aún en truth_level
    "observed_once", status active|candidate) por (scope, causa normalizada).
    Si un grupo alcanza ``min_pattern`` miembros y confianza media >=
    ``min_confidence`` crea UN candidato en candidates.jsonl y marca sus
    observaciones como status="candidate" (nunca se borran). Idempotente:
    no duplica candidato si ya existe uno ACTIVO con la misma causa.
    """
    try:
        min_pat = max(1, int(min_pattern))
    except (TypeError, ValueError):
        min_pat = 3
    try:
        min_conf = float(min_confidence)
    except (TypeError, ValueError):
        min_conf = 0.75

    registros, corruptas = _read("EPISODIC")
    cands, cor_cands = _read_candidates()
    causas_activas = {c.get("cause") for c in cands
                      if isinstance(c, dict) and c.get("status") == "candidate"}

    grupos: dict = {}
    for r in registros:
        if r.get("type") != "EPISODIC" or r.get("provenance") != "observed":
            continue
        if r.get("truth_level") != "observed_once":
            continue                      # ya elevada a pattern/verified
        if r.get("status") not in ("active", "candidate"):
            continue
        causa = _causa_normalizada(str(r.get("content") or ""))
        clave = (str(r.get("scope") or "provider"), causa)
        grupos.setdefault(clave, []).append(r)

    creados: list = []
    ahora = _now()
    for (scope_grupo, causa), miembros in grupos.items():
        if len(miembros) < min_pat:
            continue
        conf_media = (sum(_f(m.get("confidence"), 0.0) for m in miembros)
                      / len(miembros))
        if conf_media < min_conf:
            continue
        if causa in causas_activas:
            continue            # idempotencia: candidato activo ya existente
        cid = uuid.uuid4().hex[:16]
        nuevo = {
            "memory_id": cid,
            "candidate_id": cid,
            "kind": ("SKILL_CANDIDATE" if _SKILL_RE.search(causa)
                     else "SEMANTIC_CANDIDATE"),
            "cause": causa,
            "scope": scope_grupo if scope_grupo in SCOPES else "system",
            "occurrences": [m.get("memory_id") for m in miembros],
            "occurrences_count": len(miembros),
            "mean_confidence": round(conf_media, 4),
            "evidence": _evidencia_agregada(miembros),
            "domain": DOMAIN_TAG,
            "agent_id": AGENT_ID,
            "status": "candidate",
            "created_at": ahora,
            "updated_at": ahora,
        }
        cands.append(nuevo)
        causas_activas.add(causa)
        creados.append(cid)
        for m in miembros:                # no se borran: se marcan
            m["status"] = "candidate"
            m["updated_at"] = ahora

    if creados:
        _write_all("EPISODIC", registros, corruptas)
        _write_candidates(cands, cor_cands)
    return {"ok": True, "groups_scanned": len(grupos),
            "min_pattern": min_pat, "min_confidence": min_conf,
            "candidates_created": creados}


def validate_candidate(candidate_id, verdict, *, verified_by="human",
                       regression_test=None) -> dict:
    """Valida un learning candidate (§9 → §11).

    verdict="invalid"  → candidato status="retired"; las observaciones fuente
    vuelven a status="active" (no se promueve nada).
    verdict="valid"    → exige regression_test que EXISTA bajo tests/
    (ValueError "promoción exige regresión…" si falta o no existe). Promueve
    a memoria SEMANTIC/PROCEDURAL con provenance="promoted",
    truth_level="verified", confidence=0.9 y evidencia + regression_test;
    el candidato queda "retired" con promoted_to=<memory_id> y las
    observaciones vuelven a "active" con truth_level="pattern".
    """
    veredicto = str(verdict or "").strip().lower()
    if veredicto not in ("valid", "invalid"):
        return {"ok": False, "error": "verdict debe ser 'valid' o 'invalid'"}
    cands, corruptas = _read_candidates()
    cand = None
    for c in cands:
        if isinstance(c, dict) and candidate_id in (
                c.get("candidate_id"), c.get("memory_id")):
            cand = c
            break
    if cand is None:
        return {"ok": False, "error": f"candidate {candidate_id} no encontrado"}

    ahora = _now()
    cand["updated_at"] = ahora
    cand["verified_by"] = str(verified_by or "human")

    if veredicto == "invalid":
        cand["status"] = "retired"
        cand["retired_at"] = ahora
        restauradas = _set_observations(cand.get("occurrences"),
                                        status="active")
        _write_candidates(cands, corruptas)
        return {"ok": True, "verdict": "invalid",
                "candidate_id": cand.get("candidate_id"),
                "status": "retired",
                "observations_restored": restauradas}

    # verdict="valid" → promoción que EXIGE regresión (§11, fail-closed).
    ref = regression_test
    if not ref:
        for ev in cand.get("evidence") or []:
            if isinstance(ev, dict) and ev.get("kind") == "regression_test":
                ref = ev.get("ref")
                break
    if not ref:
        raise ValueError(
            "promoción exige regresión: un candidato solo se promueve a "
            "memoria SEMANTIC/PROCEDURAL verificada con un regression_test "
            "que exista bajo tests/ (§11: sin cambios estructurales "
            "automáticos)")
    _exigir_regresion(ref)

    tipo = "PROCEDURAL" if cand.get("kind") == "SKILL_CANDIDATE" else "SEMANTIC"
    evidencia = [dict(ev) for ev in (cand.get("evidence") or [])]
    evidencia.append({"kind": "regression_test", "ref": str(ref),
                      "observed_at": ahora})
    promovida = _new_memory(
        tipo, str(cand.get("cause") or ""), source="memorydv.consolidate",
        scope=cand.get("scope") if cand.get("scope") in SCOPES else "system",
        evidence=evidencia, provenance="promoted", confidence=0.9,
        truth_level="verified")
    promovida["candidate_id"] = cand.get("candidate_id")
    promovida["verified_by"] = cand["verified_by"]
    promovida["regression_test"] = str(ref)
    _append(tipo, promovida)

    cand["status"] = "retired"
    cand["retired_at"] = ahora
    cand["promoted_to"] = promovida["memory_id"]
    _set_observations(cand.get("occurrences"), status="active",
                      truth_level="pattern")
    _write_candidates(cands, corruptas)
    return {"ok": True, "verdict": "valid",
            "candidate_id": cand.get("candidate_id"),
            "promoted_to": promovida["memory_id"], "type": tipo,
            "promoted": dict(promovida)}


def needs_human_approval(record) -> bool:
    """True si una memoria SEMANTIC/PROCEDURAL carece de regresión (§11).

    MemoryDV nunca modifica estructura (código/pipeline/proveedores): una
    promoción de este tipo sin evidencia kind="regression_test" requiere
    ojos humanos antes de usarse como verdad canónica. Entrada basura →
    True (fail-closed: mejor pedir aprobación de más).
    """
    if not isinstance(record, dict):
        return True
    if record.get("type") not in ("SEMANTIC", "PROCEDURAL"):
        return False
    for ev in record.get("evidence") or []:
        if isinstance(ev, dict) and ev.get("kind") == "regression_test":
            return False
    return True


def apply_decay(factor=None, cycles=1) -> int:
    """Envejece la memoria: relevance *= factor**cycles y retira lo débil.

    Usa ``factor`` para todos los registros o, si es None, el ``decay``
    propio de cada uno (0.98 por ciclo por contrato). Los registros con
    relevance < 0.05 pasan a status="retired". Devuelve cuántos retiró en
    esta pasada. Siempre toca updated_at de los registros vivos.
    """
    try:
        ciclos = max(0, int(cycles))
    except (TypeError, ValueError):
        ciclos = 1
    factor_fijo = None
    if factor is not None:
        try:
            factor_fijo = min(1.0, max(0.0, float(factor)))
        except (TypeError, ValueError):
            factor_fijo = None

    retirados = 0
    for tipo in _FILES:
        registros, corruptas = _read(tipo)
        cambio = False
        for r in registros:
            if r.get("status") == "retired":
                continue
            factor_reg = factor_fijo
            if factor_reg is None:
                factor_reg = _clamp01(r.get("decay"), 0.98)
            relevancia = _f(r.get("relevance"), 1.0) * (factor_reg ** ciclos)
            r["relevance"] = round(min(1.0, max(0.0, relevancia)), 6)
            r["updated_at"] = _now()
            cambio = True
            if relevancia < _UMBRAL_RETIRO:
                r["status"] = "retired"
                retirados += 1
        if cambio:
            _write_all(tipo, registros, corruptas)
    return retirados


def stats() -> dict:
    """Snapshot del almacén: conteos por tipo/status, candidatos y corrupción."""
    por_tipo = {t: 0 for t in _FILES}
    por_status: dict = {}
    corruptas_total = 0
    total = 0
    for tipo in _FILES:
        registros, corruptas = _read(tipo)
        corruptas_total += len(corruptas)
        por_tipo[tipo] = len(registros)
        total += len(registros)
        for r in registros:
            estado = str(r.get("status") or "?") if isinstance(r, dict) else "?"
            por_status[estado] = por_status.get(estado, 0) + 1
    cands, cor_cands = _read_candidates()
    corruptas_total += len(cor_cands)
    activos = sum(1 for c in cands
                  if isinstance(c, dict) and c.get("status") == "candidate")
    return {
        "dir": str(_dir()),
        "total": total,
        "per_type": por_tipo,
        "per_status": por_status,
        "candidates_total": len(cands),
        "candidates_active": activos,
        "corrupted_lines": corruptas_total,
    }

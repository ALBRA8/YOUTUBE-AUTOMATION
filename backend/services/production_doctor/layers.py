"""
PRODUCTION DOCTOR V1.0 — capas de diagnóstico A-I (SOLO LECTURA).

Cada función mide hechos del sistema y devuelve Findings con evidencia;
NUNCA muta estado (las mutaciones viven exclusivamente en repairs.py, con
lista blanca cerrada). Todo lo que no se puede determinar se clasifica
UNKNOWN con «HUMAN INVESTIGATION REQUIRED» en lugar de inventar causas.

Capas (contrato del Doctor):
  A INPUT          — production.json por proyecto (parse, ejecución, paridad BD)
  B ADAPTER        — pérdida de campos del contrato (video_prompt, duration,
                     references, continuity) entre el original y el modelo g
  C FLOW_EXPORT    — video_prompt verbatim (P1) + duration_target + cola esperada
  D FLOW_JOBS      — estados de la cola: leases, duplicados, agotados,
                     huérfanos, zombies de pipeline
  E EXTENSION      — manifest/host_permissions/archivos del bridge + backend HTTP
  F GOOGLE_FLOW    — solo clasificable por evidencia: dead jobs, stalls
  G ASSET_VALIDATION — assets en disco vs mapping de escenas
  H QA             — informe forense de video_qa (modo deep)
  I RENDER         — ffmpeg/ffprobe, disco, música, proyectos atascados
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import config
import database as db

from .core import Clasificacion, REPO_ROOT, finding

EXTENSION_DIR = REPO_ROOT / "extension"
PROYECTOS_LIMITE = 200          # techo de proyectos auditados por pasada
JOBS_STALE_S = 6 * 3600         # job 'running' sin actividad > 6h → sospechoso

# archivos imprescindibles de la extensión (contrato 2.2.0)
EXT_FILES_REQUERIDOS = ("manifest.json", "background.js", "bridge.js",
                        "content.js", "injector.js", "parser.js",
                        "scanner.js", "popup.html", "popup.js")
HOST_PERMISOS_OBLIGATORIOS = ("http://localhost/*", "http://127.0.0.1/*")


# ── helpers comunes ──────────────────────────────────────────────────────────
def _ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _estilos_validos() -> set[str]:
    from services.themes import STYLES
    return {s["id"] for s in STYLES}


def _originales_en_disco() -> list[Path]:
    """production.json existentes bajo OUTPUT_DIR (ordenados, con techo)."""
    out = sorted(Path(config.OUTPUT_DIR).glob("*/production.json"))
    return out[:PROYECTOS_LIMITE]


def _parse_original(raw: bytes):
    """parse_payload del original; None si es ilegible (ya reportado en A)."""
    from services import production_json as pj
    try:
        return pj.parse_payload(raw)
    except (ValueError, TypeError):
        return None


def _proyectos_db() -> list[dict]:
    try:
        return db.list_projects(limit=PROYECTOS_LIMITE)
    except Exception:  # noqa: BLE001 — DB ausente no tumba el audit
        return []


# ── A. INPUT ─────────────────────────────────────────────────────────────────
def audit_input(**_kw) -> list:
    findings = []
    from services import production_json as pj
    estilos = _estilos_validos()
    for pfile in _originales_en_disco():
        pid = pfile.parent.name
        try:
            raw = pfile.read_bytes()
        except OSError as e:
            findings.append(finding(
                f"DOC-A-ILEGIBLE#{pid}", "A", "production_json",
                f"production.json no legible ({pid})", Clasificacion.DATA_ERROR,
                "error", {"proyecto": pid, "error": str(e)},
                "permisos de disco o archivo bloqueado"))
            continue
        try:
            data = pj.parse_payload(raw)
        except (ValueError, TypeError) as e:
            findings.append(finding(
                f"DOC-A-JSON-ILEGIBLE#{pid}", "A", "production_json",
                f"production.json corrupto ({pid})", Clasificacion.DATA_ERROR,
                "error",
                {"proyecto": pid, "bytes": len(raw), "error": str(e)[:300]},
                "escritura truncada o JSON inválido en la ingesta",
                validacion=["tests/test_production_json.py"]))
            continue
        # validación estructural del original almacenado
        try:
            g, _avisos, _norm = pj.validate(data, estilos)
        except ValueError as e:
            findings.append(finding(
                f"DOC-A-ESTRUCTURA#{pid}", "A", "production_json",
                f"production.json falla la validación estructural ({pid})",
                Clasificacion.CONTRACT_VIOLATION, "error",
                {"proyecto": pid, "error": str(e)[:300]},
                "el original fue editado a mano o quedó incompleto"))
            continue
        # unidades bloqueadas para ejecución (sin image_prompt no hay fábrica)
        rep = pj.validate_execution(data)
        bloqueadas = int(rep.get("unidades_bloqueadas") or 0)
        if bloqueadas:
            faltantes = [f"{it['unidad']}({it['id']}):{f['campo']}"
                         for it in rep.get("unidades_con_faltantes", [])
                         for f in it.get("faltantes", []) if f.get("bloqueante")]
            findings.append(finding(
                f"DOC-A-BLOQUEADAS#{pid}", "A", "production_json",
                f"{bloqueadas} unidad(es) sin image_prompt ({pid})",
                Clasificacion.DATA_ERROR, "error",
                {"proyecto": pid, "faltantes": faltantes,
                 "unidades_auditadas": rep.get("unidades_auditadas")},
                "el Creative Engine no proveyó image_prompt (el Adapter no "
                "inventa prompts — completar el Production JSON)",
                validacion=["tests/test_production_json.py",
                            "tests/test_lanzar_preflight.py"]))
        sin_vp = int(rep.get("unidades_sin_video_prompt") or 0)
        if sin_vp:
            findings.append(finding(
                f"DOC-A-SIN-VIDEO-PROMPT#{pid}", "A", "production_json",
                f"{sin_vp} unidad(es) sin video_prompt ({pid})",
                Clasificacion.DATA_ERROR, "info",
                {"proyecto": pid, "unidades_sin_video_prompt": sin_vp},
                "diseño del Adapter: esas unidades no generarán clips de "
                "video en Flow (solo imagen)"))
        # paridad sequence ↔ escenas en BD (estado derivado de la ingesta)
        proy = db.get_project(pid)
        if proy is not None:
            escenas_bd = db.get_scenes(pid)
            if len(escenas_bd) != len(g.get("escenas", [])):
                findings.append(finding(
                    f"DOC-A-PARIDAD#{pid}", "A", "production_json",
                    f"escenas en BD ({len(escenas_bd)}) ≠ sequence del "
                    f"original ({len(g.get('escenas', []))}) ({pid})",
                    Clasificacion.CONTRACT_VIOLATION, "error",
                    {"proyecto": pid, "escenas_bd": len(escenas_bd),
                     "sequence": len(g.get("escenas", []))},
                    "el original cambió tras la ingesta o la ingesta quedó "
                    "a medias (re-ingestar con submit_production_json)"))
    return findings


# ── B. ADAPTER ───────────────────────────────────────────────────────────────
def audit_adapter(**_kw) -> list:
    findings = []
    from services import production_json as pj
    estilos = _estilos_validos()
    for pfile in _originales_en_disco():
        pid = pfile.parent.name
        try:
            data = pj.parse_payload(pfile.read_bytes())
            g, _av, _norm = pj.validate(data, estilos)
        except (ValueError, TypeError):
            continue  # ya reportado en capa A
        seq = None
        project = data.get("project") if isinstance(data.get("project"), dict) else {}
        for k in ("sequence", "scenes", "escenas", "unidades"):
            if isinstance(data.get(k), list):
                seq = data[k]
                break
            if isinstance(project.get(k), list):
                seq = project[k]
                break
        if not isinstance(seq, list):
            continue
        punits = [e.get("meta", {}).get("production_unit") or {}
                  for e in g.get("escenas", [])]
        if len(punits) < len(seq):
            findings.append(finding(
                f"DOC-B-UNIDADES-PERDIDAS#{pid}", "B", "adapter",
                f"el modelo normalizado perdió unidades ({len(seq)}→"
                f"{len(punits)}) ({pid})", Clasificacion.CONTRACT_VIOLATION,
                "error", {"proyecto": pid, "original": len(seq),
                          "normalizado": len(punits)},
                "bug del adapter: validate devolvió menos escenas que "
                "unidades del original"))
            continue
        for i0, u in enumerate(seq):
            if not isinstance(u, dict):
                continue
            pu = punits[i0]
            # video_prompt (verbatim por contrato P1)
            orig_vp = pj._first(u, "video_prompt")
            tiene_vp = bool(isinstance(orig_vp, str) and orig_vp.strip())
            if isinstance(orig_vp, dict):
                tiene_vp = bool((orig_vp.get("motion") or "").strip())
            if tiene_vp and not (pu.get("video_prompt") or "").strip():
                findings.append(finding(
                    f"DOC-B-VP-PERDIDO#{pid}#{i0}", "B", "adapter",
                    f"adapter perdió video_prompt de sequence[{i0}] ({pid})",
                    Clasificacion.CONTRACT_VIOLATION, "error",
                    {"proyecto": pid, "unidad": i0,
                     "prompt_sources": pu.get("prompt_sources")},
                    "bug del adapter o alias no registrado: el original traía "
                    "video_prompt y el modelo g lo descartó"))
            # duration → duration_target
            if pj._first(u, "duration") is not None \
                    and pu.get("duration_target") is None:
                findings.append(finding(
                    f"DOC-B-DUR-PERDIDA#{pid}#{i0}", "B", "adapter",
                    f"adapter perdió duration de sequence[{i0}] ({pid})",
                    Clasificacion.CONTRACT_VIOLATION, "error",
                    {"proyecto": pid, "unidad": i0},
                    "bug del adapter: duration aliases no interpretados"))
            # references / continuity conservados tal cual (nunca interpretados)
            if pj._first(u, "references") and pu.get("references") is None:
                findings.append(finding(
                    f"DOC-B-REFS-PERDIDAS#{pid}#{i0}", "B", "adapter",
                    f"adapter perdió references de sequence[{i0}] ({pid})",
                    Clasificacion.CONTRACT_VIOLATION, "error",
                    {"proyecto": pid, "unidad": i0},
                    "las referencias debían conservarse verbatim"))
            if pj._first(u, "continuity") and pu.get("continuity") is None:
                findings.append(finding(
                    f"DOC-B-CONT-PERDIDA#{pid}#{i0}", "B", "adapter",
                    f"adapter perdió continuity de sequence[{i0}] ({pid})",
                    Clasificacion.CONTRACT_VIOLATION, "error",
                    {"proyecto": pid, "unidad": i0},
                    "la continuidad debía conservarse verbatim"))
        # continuity a nivel de proyecto
        cont = data.get("continuity")
        if cont is None and isinstance(project, dict):
            cont = project.get("continuity")
        if cont is not None and g.get("continuity") is None:
            findings.append(finding(
                f"DOC-B-CONT-PROYECTO#{pid}", "B", "adapter",
                f"adapter perdió continuity del proyecto ({pid})",
                Clasificacion.CONTRACT_VIOLATION, "error",
                {"proyecto": pid},
                "la continuidad de proyecto debía conservarse verbatim"))
    return findings


# ── C. FLOW_EXPORT ───────────────────────────────────────────────────────────
def audit_export(**_kw) -> list:
    findings = []
    from services import flow_jobs as fj
    from pipeline.flow_export import (DEFAULT_BRAND, _creative_video_prompt,
                                      _creative_duration_target,
                                      build_script_json)
    for proy in _proyectos_db():
        pid = proy["id"]
        scenes = db.get_scenes(pid)
        if not scenes:
            continue
        try:
            data = build_script_json(proy, scenes, fmt="transformacion",
                                     brand=DEFAULT_BRAND, character=None)
        except Exception as e:  # noqa: BLE001
            findings.append(finding(
                f"DOC-C-BUILD-FAIL#{pid}", "C", "flow_export",
                f"build_script_json revienta ({pid})", Clasificacion.BUG_CONFIRMED,
                "error", {"proyecto": pid, "error": f"{type(e).__name__}: {e}"[:300]},
                "excepción real del export (también rompería flow_encolar)",
                validacion=["tests/test_flow_contract_p1.py"]))
            continue
        exportadas = {int(s.get("scene_number") or 0): s
                      for s in data.get("scenes", [])}
        ultima = max(exportadas) if exportadas else 0
        for sc in scenes:
            no = int(sc.get("idx") or 0) + 1
            creative = _creative_video_prompt(sc)
            if creative:
                ent = exportadas.get(no)
                if no >= ultima:
                    continue  # última escena SOLO-imagen por diseño del método
                if not ent or not ent.get("video_prompt"):
                    findings.append(finding(
                        f"DOC-C-VP-AUSENTE#{pid}#{no}", "C", "flow_export",
                        f"export omitió video_prompt de la escena {no} ({pid})",
                        Clasificacion.CONTRACT_VIOLATION, "error",
                        {"proyecto": pid, "escena": no},
                        "P1 violado: el prompt del Creative Engine manda "
                        "SIEMPRE; flow_export nunca lo omite",
                        validacion=["tests/test_flow_contract_p1.py"]))
                else:
                    motion = (ent["video_prompt"] or {}).get("motion") or ""
                    if motion != creative:
                        findings.append(finding(
                            f"DOC-C-VP-ALTERADO#{pid}#{no}", "C",
                            "flow_export",
                            f"motion del export ≠ video_prompt creativo "
                            f"(escena {no}, {pid})",
                            Clasificacion.CONTRACT_VIOLATION, "error",
                            {"proyecto": pid, "escena": no,
                             "creative": creative[:160],
                             "exportado": motion[:160]},
                            "sanitización o alias alteró la intención "
                            "creativa (contrato P1: verbatim)",
                            validacion=["tests/test_flow_contract_p1.py"]))
            dt = _creative_duration_target(sc)
            if dt and not sc.get("duration"):
                ent = exportadas.get(no)
                if ent is not None:
                    dur_exp = float(ent.get("duration") or 0)
                    if abs(dur_exp - float(dt)) > 0.01:
                        findings.append(finding(
                            f"DOC-C-DUR-ALTERADA#{pid}#{no}", "C",
                            "flow_export",
                            f"duration exportada ({dur_exp}s) ≠ "
                            f"duration_target ({dt}s) escena {no} ({pid})",
                            Clasificacion.CONTRACT_VIOLATION, "error",
                            {"proyecto": pid, "escena": no,
                             "duration_target": dt, "exportada": dur_exp},
                            "la duración pedida por el Creative Engine no "
                            "llegó intacta al export"))
        # prompt vacío o placeholder en el export (sanitización que vacía)
        for no, ent in sorted(exportadas.items()):
            motion = ((ent.get("video_prompt") or {}).get("motion") or "") \
                if ent.get("video_prompt") else ""
            if ent.get("video_prompt") is not None and not motion.strip():
                findings.append(finding(
                    f"DOC-C-MOTION-VACIO#{pid}#{no}", "C", "flow_export",
                    f"motion exportado quedó VACÍO (escena {no}, {pid})",
                    Clasificacion.CONTRACT_VIOLATION, "error",
                    {"proyecto": pid, "escena": no},
                    "la sanitización vació el prompt (Flow recibiría basura)"))
    return findings


# ── D. FLOW_JOBS ─────────────────────────────────────────────────────────────
def audit_jobs(in_process: bool = False, **_kw) -> list:
    findings = []
    ahora = _ahora_iso()
    try:
        with db.connect() as con:
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM flow_jobs").fetchall()]
            jrows = [dict(r) for r in con.execute(
                "SELECT id, project_id, status, updated_at FROM jobs "
                "WHERE status='running'").fetchall()]
    except Exception as e:  # noqa: BLE001
        findings.append(finding(
            "DOC-D-DB-INACCESIBLE", "D", "flow_jobs",
            "no se pudo leer la cola (flow_jobs/jobs)",
            Clasificacion.ENVIRONMENT_ERROR, "critical",
            {"error": str(e)[:200]}, "SQLite bloqueado o schema ausente"))
        return findings

    def _ev(rs):
        return {"count": len(rs),
                "muestra": [{"id": r["id"], "proyecto": r["project_id"],
                             "kind": r["kind"], "escena": r["scene_number"],
                             "attempts": r["attempts"], "worker": r["worker"]}
                            for r in rs[:20]]}

    vencidos = [r for r in rows if r["status"] == "claimed"
                and r["lease_until"] and r["lease_until"] < ahora]
    if vencidos:
        findings.append(finding(
            "DOC-D-LEASE-VENCIDO", "D", "flow_jobs",
            f"{len(vencidos)} job(s) claimed con lease vencido",
            Clasificacion.DATA_ERROR, "warn", _ev(vencidos),
            "worker murió sin liberar el lease (recuperación perezosa aún "
            "no pasó por claim_next)", reparacion="recover_expired_leases",
            validacion=["tests/test_flow_bridge.py", "tests/test_chaos.py"]))

    invalidos = [r for r in rows if r["status"] == "claimed"
                 and (not r["lease_until"] or not r["job_token"])]
    if invalidos:
        findings.append(finding(
            "DOC-D-CLAIM-INVALIDO", "D", "flow_jobs",
            f"{len(invalidos)} job(s) claimed SIN lease/token",
            Clasificacion.BUG_CONFIRMED, "error", _ev(invalidos),
            "claim_next SIEMPRE pone lease+token: estado imposible por API "
            "(DB corrompida o escritura externa)",
            reparacion="requeue_invalid_claimed",
            validacion=["tests/test_flow_bridge.py"]))

    agotados = [r for r in rows if r["status"] == "queued"
                and int(r["attempts"] or 0) >= int(r["max_attempts"] or 2)]
    if agotados:
        findings.append(finding(
            "DOC-D-AGOTADO-EN-QUEUED", "D", "flow_jobs",
            f"{len(agotados)} job(s) queued con attempts agotados",
            Clasificacion.BUG_CONFIRMED, "error", _ev(agotados),
            "fail() debe mandar a dead al agotar max_attempts: queued+agotado "
            "es un estado imposible del contrato",
            reparacion="deaden_exhausted_queued",
            validacion=["tests/test_flow_bridge.py"]))

    grupos: dict[tuple, list[dict]] = {}
    for r in rows:
        if r["status"] == "done":
            continue
        grupos.setdefault((r["project_id"], r["kind"],
                           int(r["scene_number"] or 0),
                           int(r["part"] or 1)), []).append(r)
    dups = {k: v for k, v in grupos.items() if len(v) > 1}
    if dups:
        ev = {"count": len(dups),
              "muestra": [f"{k[0]}:{k[1]}:esc{k[2]}" for k in list(dups)[:20]]}
        findings.append(finding(
            "DOC-D-DUPLICADOS", "D", "flow_jobs",
            f"{len(dups)} clave(s) de job duplicada (no-done)",
            Clasificacion.BUG_CONFIRMED, "error", ev,
            "enqueue_project es idempotente: duplicados = escritura externa "
            "o carrera fuera de BEGIN IMMEDIATE",
            reparacion="dedupe_flow_jobs",
            validacion=["tests/test_concurrencia.py"]))

    proyectos = {p["id"] for p in _proyectos_db()}
    huerfanos = [r for r in rows if r["project_id"] not in proyectos]
    if huerfanos:
        findings.append(finding(
            "DOC-D-HUERFANOS", "D", "flow_jobs",
            f"{len(huerfanos)} job(s) de proyectos inexistentes",
            Clasificacion.DATA_ERROR, "warn", _ev(huerfanos),
            "quedaron filas tras borrar proyectos (estado derivado huérfano)",
            reparacion="delete_orphan_jobs"))

    done_sin_asset = [r for r in rows if r["status"] == "done"
                      and (not r["asset_path"]
                           or not Path(str(r["asset_path"])).exists())]
    if done_sin_asset:
        findings.append(finding(
            "DOC-D-DONE-SIN-ASSET", "D", "flow_jobs",
            f"{len(done_sin_asset)} job(s) done cuyo asset NO está en disco",
            Clasificacion.DATA_ERROR, "error", _ev(done_sin_asset),
            "el asset se borró tras completarse (remedio: re-encolar con "
            "MCP flow_encolar — vuelve a pasar por Google Flow)"))

    dead = [r for r in rows if r["status"] == "dead"]
    if dead:
        errores = sorted({(r.get("error") or "?")[:80] for r in dead})[:5]
        findings.append(finding(
            "DOC-D-DEAD", "D", "flow_jobs",
            f"{len(dead)} job(s) dead (attempts agotados tras fallos)",
            Clasificacion.EXTERNAL_SERVICE_ERROR, "warn",
            {"count": len(dead), "errores_muestra": errores},
            "Google Flow/proveedor falló repetidamente (remedio: revisar "
            "extensión y re-encolar con MCP flow_encolar)"))

    # cola esperada según el contrato P1 — MISMA fuente que enqueue_project:
    # build_script_json (la última escena es SOLO-imagen por diseño).
    from pipeline.flow_export import DEFAULT_BRAND as _db_brand
    from pipeline.flow_export import build_script_json as _bsj
    faltantes_cola: list[str] = []
    for proy in _proyectos_db():
        pid = proy["id"]
        scenes = db.get_scenes(pid)
        if not scenes:
            continue
        try:
            export = _bsj(proy, scenes, fmt="transformacion",
                          brand=_db_brand, character=None)
        except Exception:  # noqa: BLE001 — capa C ya reporta el build roto
            continue
        jobs_p = [r for r in rows if r["project_id"] == pid]
        claves = {(r["kind"], int(r["scene_number"] or 0)) for r in jobs_p}
        flow_dir = Path(config.OUTPUT_DIR) / pid / "flow"
        escenas_por_no = {int(sc.get("idx") or 0) + 1: sc for sc in scenes}
        for ent in export.get("scenes", []):
            no = int(ent.get("scene_number") or 0)
            if no <= 0 or no > len(scenes):
                continue
            if ("image", no) not in claves:
                sc = escenas_por_no.get(no) or {}
                if not sc.get("image_path") and not list(
                        flow_dir.glob(f"Escena_{no:02d}_flow.*")):
                    faltantes_cola.append(f"{pid}:image:{no}")
            if ent.get("video_prompt") and ("video", no) not in claves:
                faltantes_cola.append(f"{pid}:video:{no}")
    if faltantes_cola:
        findings.append(finding(
            "DOC-D-COLA-INCOMPLETA", "D", "flow_jobs",
            f"faltan {len(faltantes_cola)} job(s) del contrato "
            "(cola incompleta)", Clasificacion.DATA_ERROR, "error",
            {"count": len(faltantes_cola),
             "muestra": faltantes_cola[:20]},
            "unidades creativas sin job asociado (enqueue a medias o jobs "
            "borrados a mano)", reparacion="rebuild_job_queue",
            validacion=["tests/test_flow_bridge.py"]))

    # zombies del pipeline (jobs table) — solo juicio preciso in-process
    if jrows:
        if in_process:
            from pipeline import orchestrator
            zombies = [j for j in jrows
                       if not (orchestrator.JOBS.get(j["id"], {})
                               .get("task"))]
            if zombies:
                findings.append(finding(
                    "DOC-D-ZOMBIE-PIPELINE", "D", "orchestrator",
                    f"{len(zombies)} job(s) 'running' sin tarea viva",
                    Clasificacion.BUG_CONFIRMED, "error",
                    {"count": len(zombies),
                     "muestra": [j["id"] for j in zombies[:20]]},
                    "restos de un crash del servidor (mismo criterio que "
                    "orchestrator._zombie_job)",
                    reparacion="fail_zombie_pipeline_jobs",
                    validacion=["tests/test_chaos.py"]))
        else:
            viejos = []
            for j in jrows:
                try:
                    t = datetime.fromisoformat(j.get("updated_at")
                                               or j.get("created_at")
                                               or _ahora_iso())
                    edad = (datetime.now(timezone.utc) - t).total_seconds()
                except (ValueError, TypeError):
                    continue
                if edad > JOBS_STALE_S:
                    viejos.append({"id": j["id"], "proyecto": j["project_id"],
                                   "horas_sin_actividad": round(edad / 3600, 1)})
            if viejos:
                findings.append(finding(
                    "DOC-D-RUNNING-STALE", "D", "orchestrator",
                    f"{len(viejos)} job(s) 'running' sin actividad > "
                    f"{JOBS_STALE_S // 3600}h — HUMAN INVESTIGATION REQUIRED",
                    Clasificacion.UNKNOWN, "warn",
                    {"count": len(viejos), "muestra": viejos[:20]},
                    "fuera del proceso del servidor NO se puede saber si la "
                    "tarea vive (el doctor no inventa: requiere humano)"))
    return findings


# ── E. EXTENSION ─────────────────────────────────────────────────────────────
def _http_probe(url: str, timeout: float = 2.5) -> tuple[bool, str]:
    try:
        # v2.19 · anti-SSRF: backend_url llega por MCP/API (origen no
        # confiable). Sin guardia, un file:// o 169.254.169.254 se sondeaba.
        import security as _sec
        url = _sec.safe_url(url)
    except ValueError as e:
        return False, f"URL rechazada (guardia SSRF): {e}"[:160]
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(300).decode("utf-8", "replace")
            return resp.status == 200, f"HTTP {resp.status}: {body[:120]}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"[:160]


def audit_extension(probe_http: bool = True, **_kw) -> list:
    findings = []
    manifest = EXTENSION_DIR / "manifest.json"
    if not manifest.exists():
        findings.append(finding(
            "DOC-E-MANIFEST-AUSENTE", "E", "manifest",
            "extension/manifest.json NO existe", Clasificacion.CONFIG_ERROR,
            "critical", {"dir": str(EXTENSION_DIR)},
            "extensión incompleta: el bridge no puede cargarse"))
        return findings
    try:
        m = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError as e:
        findings.append(finding(
            "DOC-E-MANIFEST-JSON", "E", "manifest",
            "manifest.json no es JSON válido", Clasificacion.CONFIG_ERROR,
            "critical", {"error": str(e)[:200]},
            "edición manual rompe la carga de la extensión"))
        return findings
    if int(m.get("manifest_version") or 0) != 3:
        findings.append(finding(
            "DOC-E-MANIFEST-MV3", "E", "manifest",
            f"manifest_version={m.get('manifest_version')} (se requiere 3)",
            Clasificacion.CONFIG_ERROR, "critical",
            {"manifest_version": m.get("manifest_version")},
            "Chrome MV3 es requisito del bridge actual"))
    host_perms = list(m.get("host_permissions") or [])
    faltan = [h for h in HOST_PERMISOS_OBLIGATORIOS if h not in host_perms]
    if faltan:
        findings.append(finding(
            "DOC-E-HOST-PERMISSIONS", "E", "manifest",
            f"host_permissions sin {faltan}", Clasificacion.CONFIG_ERROR,
            "critical", {"actuales": host_perms, "faltan": faltan},
            "sin permisos localhost/127.0.0.1 el Service Worker del bridge "
            "no puede llamar al backend (contrato 2.2.0)"))
    faltan_files = [f for f in EXT_FILES_REQUERIDOS
                    if not (EXTENSION_DIR / f).exists()]
    if faltan_files:
        findings.append(finding(
            "DOC-E-ARCHIVOS", "E", "extension",
            f"archivos de la extensión ausentes: {faltan_files}",
            Clasificacion.CONFIG_ERROR, "critical",
            {"faltan": faltan_files, "dir": str(EXTENSION_DIR)},
            "extensión incompleta (parser/scanner/bridge rotos)"))
    bridge = EXTENSION_DIR / "bridge.js"
    if bridge.exists():
        texto = bridge.read_text(encoding="utf-8", errors="replace")
        # El bridge construye las URLs dinámicamente: se mide la ASIGNACIÓN
        # real de BRIDGE_API_BASE (regex) — no el texto del archivo, que
        # también menciona las URLs en comentarios (falso negativo).
        m = re.search(r"BRIDGE_API_BASE\s*=\s*['\"]([^'\"]+)['\"]", texto)
        base = m.group(1) if m else None
        base_ok = bool(base) and "api/extension/flow/jobs" in base
        rutas = ["/next", "/heartbeat", "/complete", "/fail"]
        faltan = [r for r in rutas if f"'{r}" not in texto
                  and f'"{r}' not in texto and f"`{r}" not in texto]
        if not base_ok:
            findings.append(finding(
                "DOC-E-BRIDGE-BASE", "E", "bridge",
                f"BRIDGE_API_BASE={base!r} no apunta a api/extension/flow/jobs",
                Clasificacion.CONTRACT_VIOLATION, "critical",
                {"asignacion_real": base,
                 "esperado": "'/api/extension/flow/jobs'"},
                "bridge desalineado con los endpoints reales del backend: "
                "la cola no funcionará"))
        elif faltan:
            findings.append(finding(
                f"DOC-E-BRIDGE-ENDPOINT#{faltan[0].strip('/')}", "E", "bridge",
                f"bridge.js no construye la ruta {faltan}",
                Clasificacion.CONTRACT_VIOLATION, "critical",
                {"rutas_ausentes": faltan},
                "bridge desalineado con los endpoints reales del "
                "backend: la cola no funcionará"))
    if probe_http:
        base = f"http://127.0.0.1:{config.PORT}"
        ok, detail = _http_probe(f"{base}/api/health")
        if not ok:
            findings.append(finding(
                "DOC-E-BACKEND-DOWN", "E", "backend",
                f"backend no respondió en {base}/api/health",
                Clasificacion.ENVIRONMENT_ERROR, "warn",
                {"url": f"{base}/api/health", "detalle": detail},
                "el servidor no está arrancado (en PREFLIGHT esto BLOQUEA)"))
    return findings


# ── F. GOOGLE FLOW (solo evidencia indirecta) ────────────────────────────────
def audit_external(**_kw) -> list:
    findings = []
    ahora = _ahora_iso()
    try:
        with db.connect() as con:
            rows = [dict(r) for r in con.execute(
                """SELECT id, project_id, kind, scene_number, status,
                          lease_until, worker FROM flow_jobs
                   WHERE status='claimed' AND kind='video'""").fetchall()]
    except Exception:  # noqa: BLE001
        return findings
    en_curso = [r for r in rows if r.get("lease_until")
                and r["lease_until"] >= ahora]
    if en_curso:
        findings.append(finding(
            "DOC-F-GENERACION-EN-CURSO", "F", "google_flow",
            f"{len(en_curso)} clip(es) en generación en Google Flow",
            Clasificacion.EXTERNAL_SERVICE_ERROR, "info",
            {"count": len(en_curso),
             "muestra": [f"{r['project_id']}:esc{r['scene_number']}"
                         for r in en_curso[:20]]},
            "la generación depende de Google Flow: si tarda más que el "
            "lease (15 min) el job vuelve a queued (no es fallo local)"))
    return findings


# ── G. ASSET VALIDATION ──────────────────────────────────────────────────────
def audit_assets(**_kw) -> list:
    findings = []
    for proy in _proyectos_db():
        pid = proy["id"]
        try:
            scenes = db.get_scenes(pid)
        except Exception:  # noqa: BLE001
            continue
        if not scenes:
            continue
        flow_dir = Path(config.OUTPUT_DIR) / pid / "flow"
        for sc in scenes:
            ip = sc.get("image_path")
            no = int(sc.get("idx") or 0) + 1
            if ip and not Path(str(ip)).exists():
                hay_candidato = bool(list(flow_dir.glob(
                    f"Escena_{no:02d}_flow.*")))
                findings.append(finding(
                    f"DOC-G-IMAGEN-PERDIDA#{pid}#{no}", "G", "assets",
                    f"scene.image_path apunta a archivo inexistente "
                    f"(escena {no}, {pid})", Clasificacion.DATA_ERROR,
                    "error",
                    {"proyecto": pid, "escena": no, "image_path": str(ip),
                     "candidato_en_flow": hay_candidato},
                    "asset movido/borrado tras mapearse (mapping derivado "
                    "desincronizado)" if hay_candidato else
                    "el asset original se perdió (remedio: re-encolar — "
                    "vuelve a pasar por Google Flow)",
                    reparacion="rebuild_asset_mapping" if hay_candidato
                    else None))
        # assets huérfanos en flow/ (info)
        if flow_dir.exists():
            referenciados = set()
            try:
                with db.connect() as con:
                    for r in con.execute(
                            "SELECT asset_path FROM flow_jobs "
                            "WHERE project_id=? AND asset_path IS NOT NULL",
                            (pid,)):
                        referenciados.add(Path(r["asset_path"]).name)
            except Exception:  # noqa: BLE001
                referenciados = None
            if referenciados is not None:
                huerfanos = [p.name for p in sorted(flow_dir.iterdir())
                             if p.is_file() and p.suffix.lower()
                             in (".png", ".jpg", ".webp", ".mp4")
                             and p.name not in referenciados]
                if huerfanos:
                    findings.append(finding(
                        f"DOC-G-HUERFANOS#{pid}", "G", "assets",
                        f"{len(huerfanos)} asset(s) en flow/ sin job done "
                        f"({pid})", Clasificacion.DATA_ERROR, "info",
                        {"proyecto": pid, "muestra": huerfanos[:10]},
                        "restos de re-encolas previas (no bloquean)"))
    return findings


# ── H. QA ────────────────────────────────────────────────────────────────────
def audit_qa(deep: bool = False, **_kw) -> list:
    if not deep:
        return []   # QA forense es caro (ffprobe por asset): solo en deep
    findings = []
    from services import video_qa as vqa
    for proy in _proyectos_db():
        pid = proy["id"]
        try:
            rep = vqa.qa_project(pid)
        except Exception:  # noqa: BLE001
            continue
        # v2.19 · fix de claves: qa_project devuelve «scenes» (cada escena con
        # «image» + «clips») — el código anterior iteraba «imagenes»/«videos»
        # (claves inexistentes) y los hallazgos por escena NUNCA subían.
        for sc in rep.get("scenes", []) or []:
            no = sc.get("scene", "?")
            bloques: list[tuple[str, dict]] = []
            if sc.get("image"):
                bloques.append(("imagen", sc["image"]))
            for clip in sc.get("clips") or []:
                bloques.append(("clip", clip))
            for tipo, item in bloques:
                for flag in item.get("flags", []) or []:
                    sev = flag.get("sev") or "warn"
                    if sev == "ok":
                        continue
                    findings.append(finding(
                        f"DOC-H-QA#{pid}#E{no}#{tipo}",
                        "H", "video_qa",
                        f"QA {sev} ({tipo} escena {no}): "
                        f"{flag.get('msg', '')[:120]}",
                        Clasificacion.DATA_ERROR, "warn" if sev == "warn"
                        else "error",
                        {"proyecto": pid, "escena": no, "tipo": tipo,
                         "path": item.get("path"), "flag": flag},
                        "asset generado por el proveedor con defectos "
                        "(remedio: re-encolar ese job)"))
            for flag in sc.get("clip_flags", []) or []:
                sev = flag.get("sev") or "warn"
                if sev == "ok":
                    continue
                findings.append(finding(
                    f"DOC-H-QA#{pid}#E{sc.get('scene', '?')}#pendiente",
                    "H", "video_qa",
                    f"QA {sev} (escena {sc.get('scene', '?')}): "
                    f"{flag.get('msg', '')[:120]}",
                    Clasificacion.DATA_ERROR, "warn",
                    {"proyecto": pid, "escena": sc.get("scene"), "flag": flag},
                    "clip esperado y ausente (job pendiente o en cola)"))
        final = rep.get("final") or {}
        for flag in final.get("flags", []) or []:
            if (flag.get("sev") or "ok") == "ok":
                continue
            findings.append(finding(
                f"DOC-H-QA-FINAL#{pid}", "H", "video_qa",
                f"QA del render final: {flag.get('msg', '')[:120]}",
                Clasificacion.DATA_ERROR, "error",
                {"proyecto": pid, "flag": flag},
                "el render final tiene defectos medidos (re-renderizar)"))
    return findings


# ── I. RENDER (+ entorno de render) ──────────────────────────────────────────
def audit_render(**_kw) -> list:
    findings = []
    from services import doctor as health  # reutiliza las sondas existentes
    v = health._probe_version(["ffmpeg", "-version"])
    if not v:
        findings.append(finding(
            "DOC-I-FFMPEG", "I", "render", "ffmpeg no responde",
            Clasificacion.ENVIRONMENT_ERROR, "critical",
            {"sonda": "ffmpeg -version"},
            "sin ffmpeg no hay render (instalar: apt install ffmpeg)"))
    v = health._probe_version(["ffprobe", "-version"])
    if not v:
        findings.append(finding(
            "DOC-I-FFPROBE", "I", "render", "ffprobe no responde",
            Clasificacion.ENVIRONMENT_ERROR, "critical",
            {"sonda": "ffprobe -version"},
            "sin ffprobe la validación de assets no funciona"))
    ok_dir, disk_ok, detail = health._disk_report(Path(config.OUTPUT_DIR))
    if not ok_dir or not disk_ok:
        findings.append(finding(
            "DOC-I-DISCO", "I", "render", f"OUTPUT_DIR en problema: {detail}",
            Clasificacion.ENVIRONMENT_ERROR, "critical",
            {"detalle": detail, "output_dir": str(config.OUTPUT_DIR)},
            "sin disco/escritura no hay assets ni renders"))
    music = Path(config.MUSIC_DIR)
    try:
        pistas = [p for p in music.glob("*.mp3")] if music.exists() else []
    except OSError:
        pistas = []
    if not pistas:
        findings.append(finding(
            "DOC-I-MUSICA", "I", "render",
            "data/music sin pistas mp3 (renders sin fondo musical)",
            Clasificacion.CONFIG_ERROR, "warn",
            {"music_dir": str(music), "pistas": 0},
            "los mp3 viven en el repo (git checkout/restaurar)"))
    return findings


# ── registro de capas ────────────────────────────────────────────────────────
AUDIT_CAPAS = {
    "A": audit_input, "B": audit_adapter, "C": audit_export, "D": audit_jobs,
    "E": audit_extension, "F": audit_external, "G": audit_assets,
    "H": audit_qa, "I": audit_render,
}


def auditar_capas(capas: list[str] | None = None, *, deep: bool = False,
                  in_process: bool = False, probe_http: bool = True) -> list:
    """Ejecuta las capas pedidas (todas por defecto) y junta Findings.
    Cada capa corre en try: una capa que revienta genera un Finding
    UNKNOWN (no tumba el resto del diagnóstico)."""
    findings = []
    pedidas = capas or list(AUDIT_CAPAS)
    for code in pedidas:
        fn = AUDIT_CAPAS.get(code)
        if fn is None:
            continue
        try:
            if code == "D":
                findings.extend(fn(in_process=in_process))
            elif code == "E":
                findings.extend(fn(probe_http=probe_http))
            elif code == "H":
                findings.extend(fn(deep=deep))
            else:
                findings.extend(fn())
        except Exception as e:  # noqa: BLE001
            findings.append(finding(
                f"DOC-{code}-AUDIT-FAIL", code, "doctor",
                f"la capa {code} revintió durante el audit",
                Clasificacion.UNKNOWN, "error",
                {"error": f"{type(e).__name__}: {e}"[:300]},
                "HUMAN INVESTIGATION REQUIRED: el propio diagnóstico falló"))
    return findings

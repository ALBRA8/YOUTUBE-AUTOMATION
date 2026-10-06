"""
PRODUCTION DOCTOR V1.0 — REAL FLOW PREFLIGHT (regla 8 del contrato).

Barrera de verificación ANTES de una prueba real con Google Flow. Si falla
UN SOLO requisito determinístico, la respuesta es REAL FLOW BLOCKED con la
lista exacta de motivos — el preflight NUNCA ejecuta Flow ni repara nada
(esperar/crear jobs es cosa del operador; reparar, cosa de DOCTOR FIX).

Checks bloqueantes mínimos (contrato):
  backend disponible · extensión STRUCTURAL READY (manifest MV3 + archivos +
  host_permissions + bridge alineado) · Production JSON válido ·
  image_prompt en TODAS las unidades · video_prompt en TODAS las unidades
  que generan clip — criterio contractual estricto: si el proyecto genera
  clips (2+ unidades), NINGUNA unidad que deba generar video puede carecer
  de video_prompt; NO basta con que exista al menos uno. La única exenta es
  la última (SOLO-imagen por diseño del export); con 0 unidades de video el
  criterio no aplica · duration_target válido · job creado correctamente ·
  project_id correcto · worker/claim posible (cola limpia, sin atascos) ·
  payload Flow correcto · directorios necesarios · herramientas de
  validación disponibles · estado del proyecto listo para ejecutar.

EXTENSION STRUCTURAL READY ≠ EXTENSION RUNTIME CONNECTED: la conexión
runtime (Chrome ↔ backend) NO es observable desde el backend — la única
evidencia válida es un job 'claimed' con worker y lease VIGENTE (mecanismo
de liveness del contrato). Sin evidencia se clasifica
NOT_DEMONSTRATED/UNKNOWN (ok=False, no bloqueante) y NUNCA como PASS.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import config
import database as db

from .core import REPO_ROOT
from .layers import (EXT_FILES_REQUERIDOS, HOST_PERMISOS_OBLIGATORIOS,
                     _http_probe, _ahora_iso)


def _check(checks: list, cid: str, ok: bool, detalle: str,
           bloqueante: bool = True, estado: str | None = None) -> None:
    item = {"id": cid, "ok": bool(ok), "detalle": detalle,
            "bloqueante": bloqueante}
    if estado:
        item["estado"] = estado
    checks.append(item)


def real_flow_preflight(project_id: str | None = None,
                        backend_url: str | None = None) -> dict:
    """Ejecuta todos los checks y devuelve el veredicto.
    Sin project_id: solo entorno/backend/extensión/herramientas.
    Con project_id: además contrato, cola y estado del proyecto."""
    checks: list[dict] = []

    # ── herramientas de validación disponibles ──────────────────────────
    from services import doctor as health
    v = health._probe_version(["ffmpeg", "-version"])
    _check(checks, "P-TOOLS-FFMPEG", bool(v),
           v or "ffmpeg no responde (sin él no hay render ni validación)")
    v = health._probe_version(["ffprobe", "-version"])
    _check(checks, "P-TOOLS-FFPROBE", bool(v),
           v or "ffprobe no responde (sin él no se validan assets)")
    try:
        import PIL  # noqa: F401
        _check(checks, "P-TOOLS-PIL", True, "PIL importable (validación PNG)")
    except ImportError:
        _check(checks, "P-TOOLS-PIL", False,
               "PIL no instalado (pip install pillow)")

    # ── directorios necesarios (existen + escribibles; NO se crean aquí) ──
    for attr, nombre in (("DATA_DIR", "data"), ("OUTPUT_DIR", "output"),
                         ("TMP_DIR", "tmp"), ("MUSIC_DIR", "music")):
        d = Path(getattr(config, attr))
        ok = d.exists() and d.is_dir()
        if ok:
            probe = d / ".preflight_probe"
            try:
                probe.write_bytes(b"ok")
                probe.unlink()
            except OSError:
                ok = False
        _check(checks, f"P-DIRS-{nombre.upper()}", ok,
               f"{d} escribible" if ok else f"{d} ausente o sin escritura")

    # ── backend disponible ───────────────────────────────────────────────
    base = (backend_url or f"http://127.0.0.1:{config.PORT}").rstrip("/")
    ok, detail = _http_probe(f"{base}/api/health", timeout=3.0)
    _check(checks, "P-BACKEND-HEALTH", ok,
           f"{base}/api/health → {detail}" if ok else
           f"backend NO disponible en {base} ({detail}) — arranca el "
           "servidor antes de la prueba real")

    # ── extensión disponible (manifest + archivos + permisos) ────────────
    manifest = REPO_ROOT / "extension" / "manifest.json"
    m = None
    if not manifest.exists():
        _check(checks, "P-EXT-MANIFEST", False,
               "extension/manifest.json NO existe")
    else:
        try:
            m = __import__("json").loads(manifest.read_text(encoding="utf-8"))
            _check(checks, "P-EXT-MANIFEST", True,
                   f"manifest {m.get('version', '?')} (MV3="
                   f"{m.get('manifest_version')})")
        except ValueError as e:
            _check(checks, "P-EXT-MANIFEST", False,
                   f"manifest.json no es JSON válido: {e}")
    if m is not None:
        host_perms = list(m.get("host_permissions") or [])
        faltan = [h for h in HOST_PERMISOS_OBLIGATORIOS if h not in host_perms]
        _check(checks, "P-EXT-HOST-PERMISSIONS", not faltan,
               "host_permissions localhost/127.0.0.1 OK" if not faltan
               else f"faltan host_permissions {faltan} (bridge no alcanzará "
                    "al backend)")
    faltan_files = [f for f in EXT_FILES_REQUERIDOS
                    if not (REPO_ROOT / "extension" / f).exists()]
    _check(checks, "P-EXT-ARCHIVOS", not faltan_files,
           "archivos de la extensión completos" if not faltan_files
           else f"archivos ausentes: {faltan_files}")

    # ── bridge disponible (alineado con los endpoints reales) ────────────
    bridge = REPO_ROOT / "extension" / "bridge.js"
    if not bridge.exists():
        _check(checks, "P-BRIDGE", False, "extension/bridge.js NO existe")
    else:
        import re as _re
        texto = bridge.read_text(encoding="utf-8", errors="replace")
        # se mide la ASIGNACIÓN real de BRIDGE_API_BASE (regex), no el texto
        # completo (los comentarios también citan las URLs)
        m = _re.search(r"BRIDGE_API_BASE\s*=\s*['\"]([^'\"]+)['\"]", texto)
        base_b = m.group(1) if m else None
        base_ok = bool(base_b) and "api/extension/flow/jobs" in base_b
        faltan_ep = [r for r in ("/next", "/heartbeat", "/complete", "/fail")
                     if f"'{r}" not in texto and f'"{r}' not in texto]
        _check(checks, "P-BRIDGE", base_ok and not faltan_ep,
               f"bridge.js alineado (BRIDGE_API_BASE={base_b})"
               if (base_ok and not faltan_ep) else
               f"bridge.js desalineado (BRIDGE_API_BASE={base_b!r}, "
               f"rutas ausentes: {faltan_ep})")

    # ── extensión RUNTIME (conexión viva Chrome ↔ backend) ───────────────
    # Diferencia contractual: los checks P-EXT-*/P-BRIDGE de arriba son
    # ESTRUCTURALES (la extensión está completa en disco). Que Chrome con la
    # extensión esté CONECTADO AHORA no es observable desde el backend: la
    # única evidencia válida es un job 'claimed' con worker y lease VIGENTE
    # (el lease se renueva por heartbeat y expira con worker muerto —
    # mecanismo de liveness del propio contrato). Sin evidencia → estado
    # NOT_DEMONSTRATED (≈ UNKNOWN), NUNCA PASS ni conexión inventada.
    evidencia_rt = None
    try:
        with db.connect() as con:
            _ev = con.execute(
                """SELECT id, project_id, worker, kind, lease_until
                   FROM flow_jobs
                   WHERE status='claimed' AND worker IS NOT NULL
                         AND lease_until IS NOT NULL AND lease_until >= ?
                   ORDER BY updated_at DESC LIMIT 1""",
                (_ahora_iso(),)).fetchone()
        if _ev:
            evidencia_rt = dict(_ev)
    except Exception:  # noqa: BLE001 — sin DB legible no hay evidencia
        evidencia_rt = None
    if evidencia_rt:
        _check(checks, "P-EXT-RUNTIME", True,
               f"EXTENSION RUNTIME CONNECTED — worker "
               f"'{evidencia_rt.get('worker')}' mantiene lease vigente "
               f"(job {evidencia_rt.get('id')}, proyecto "
               f"{evidencia_rt.get('project_id')}, vence "
               f"{evidencia_rt.get('lease_until')})",
               bloqueante=False, estado="PASS")
    else:
        _check(checks, "P-EXT-RUNTIME", False,
               "EXTENSION RUNTIME CONNECTED: NOT_DEMONSTRATED — el backend "
               "no puede observar Chrome: sin ningún job 'claimed' con "
               "worker y lease vigente NO hay evidencia de conexión viva; "
               "se clasifica NOT_DEMONSTRATED/UNKNOWN, NUNCA PASS (no "
               "bloquea: el operador confirma Chrome+extensión activos "
               "antes de gastar la prueba)",
               bloqueante=False, estado="NOT_DEMONSTRATED")

    # ── por proyecto: contrato + cola + estado ───────────────────────────
    if project_id:
        proy = db.get_project(project_id)
        _check(checks, "P-PROJ-EXISTS", proy is not None,
               f"proyecto {project_id} existe en BD" if proy else
               f"proyecto {project_id} NO existe (project_id incorrecto)")
        if proy is not None:
            scenes = db.get_scenes(project_id)
            _check(checks, "P-PROJ-SCENES", bool(scenes),
                   f"{len(scenes)} escena(s) en BD" if scenes else
                   "el proyecto no tiene escenas (nada que generar)")

            # sin pipeline activo que interfiera
            activo = db.active_job_for_project(project_id)
            if activo:
                try:
                    from pipeline import orchestrator
                    reg = orchestrator.JOBS.get(activo["id"])
                    vivo = bool(reg and reg.get("task"))
                except Exception:  # noqa: BLE001
                    vivo = True  # no se puede saber → no bloquear por rumor
                _check(checks, "P-PROJ-NO-ACTIVO", not vivo,
                       "sin pipeline activo que interfiera" if not vivo else
                       f"pipeline {activo['id']} EN EJECUCIÓN interferiría "
                       "con la prueba")

            # Production JSON válido (fuente de la cola y de Flow)
            pfile = Path(config.OUTPUT_DIR) / project_id / "production.json"
            if not pfile.exists():
                _check(checks, "P-PJSON-EXISTE", False,
                       f"{pfile} NO existe (sin contrato no hay cola P1)")
            else:
                try:
                    from services import production_json as pj
                    data = pj.parse_payload(pfile.read_bytes())
                    rep = pj.validate_execution(data)
                except (ValueError, TypeError) as e:
                    data = rep = None
                    _check(checks, "P-PJSON-PARSE", False,
                           f"production.json ilegible: {e}")
                if rep is not None:
                    _check(checks, "P-PJSON-PARSE", True,
                           "production.json parsea y valida")
                    bloqueadas = int(rep.get("unidades_bloqueadas") or 0)
                    _check(checks, "P-PJSON-IMAGE-PROMPT", bloqueadas == 0,
                           "image_prompt presente en TODAS las unidades"
                           if bloqueadas == 0 else
                           f"{bloqueadas} unidad(es) SIN image_prompt "
                           "(REAL FLOW no puede ejecutarlas)")
                    # criterio contractual EXPLÍCITO (video): si el
                    # proyecto genera clips, TODA unidad que deba generar
                    # video exige video_prompt — no basta con que exista
                    # al menos uno. Diseño del export (build_script_json):
                    # escena i = Imagen i + Video i; la ÚLTIMA es
                    # SOLO-imagen (revelación final) → única exenta.
                    sin_vp = int(rep.get("unidades_sin_video_prompt") or 0)
                    total = int(rep.get("unidades_auditadas") or 0)
                    seq_unid = None
                    for _k in pj._ALIASES["sequence"]:  # misma tabla de
                        # alias que validate_execution (una sola fuente de
                        # verdad; NO se duplica contrato)
                        if isinstance(data.get(_k), list):
                            seq_unid = data[_k]
                            break
                        _pr = data.get("project")
                        if isinstance(_pr, dict) \
                                and isinstance(_pr.get(_k), list):
                            seq_unid = _pr[_k]
                            break
                    sin_vp_idx: list[int] = []
                    for _i, _u in enumerate(seq_unid or []):
                        if not isinstance(_u, dict):
                            continue
                        # presencia por unidad con la API pública del
                        # contrato (validate_execution por unidad)
                        if int(pj.validate_execution(
                                {"sequence": [_u]}).get(
                                "unidades_sin_video_prompt") or 0):
                            sin_vp_idx.append(_i)
                    _exenta = total - 1  # última SOLO-imagen por diseño
                    _generan = max(0, total - 1)
                    if seq_unid is None and sin_vp:
                        faltan_lbl = ["sequence (no localizable para el "
                                      "criterio por unidad)"]  # fail-closed
                    else:
                        faltan_lbl = []
                        for _i in sin_vp_idx:
                            if _i == _exenta:
                                continue
                            _uid = ""
                            if isinstance(seq_unid[_i], dict):
                                _uid = str(seq_unid[_i].get("id") or "")
                            faltan_lbl.append(
                                f"sequence[{_i}]" + (f" (id {_uid})"
                                                     if _uid else ""))
                    if faltan_lbl:
                        if sin_vp >= total and total > 1:
                            det_vp = (f"NINGUNA unidad tiene video_prompt — "
                                      f"el criterio contractual exige "
                                      f"video_prompt en TODAS las unidades "
                                      f"que generan clip ({_generan}/{total}); "
                                      f"Google Flow no generaría clips del "
                                      f"Creative Engine")
                        else:
                            det_vp = (f"{len(faltan_lbl)} unidad(es) que DEBEN "
                                      f"generar video SIN video_prompt: "
                                      f"{', '.join(faltan_lbl[:6])} — "
                                      f"criterio: TODA unidad que genere clip "
                                      f"requiere video_prompt (solo la última "
                                      f"es SOLO-imagen por diseño)")
                        _check(checks, "P-PJSON-VIDEO-PROMPT", False, det_vp)
                    elif _generan == 0:
                        _check(checks, "P-PJSON-VIDEO-PROMPT", True,
                               "el proyecto genera 0 clips de video por "
                               "diseño (unidad única/última SOLO-imagen) — "
                               "el criterio video_prompt no aplica")
                    elif sin_vp == 0:
                        _check(checks, "P-PJSON-VIDEO-PROMPT", True,
                               f"video_prompt presente en TODAS las unidades "
                               f"({total}/{total})")
                    else:
                        _check(checks, "P-PJSON-VIDEO-PROMPT", True,
                               f"video_prompt presente en TODAS las unidades "
                               f"que generan video ({_generan}/{total}); la "
                               f"última es SOLO-imagen por diseño (exenta)")
                    sin_dur = int(
                        rep.get("unidades_con_faltantes_no_bloqueantes") or 0)
                    con_dur = total - sin_dur
                    _check(checks, "P-PJSON-DURATION", True,
                           f"{con_dur}/{total} unidad(es) con duration "
                           "explícita (las demás usan duración mecánica — "
                           "no bloqueante por diseño)")
                    # payload Flow correcto: rebuild en seco del export
                    try:
                        from pipeline.flow_export import (DEFAULT_BRAND,
                                                          build_script_json)
                        export = build_script_json(proy, scenes,
                                                   fmt="transformacion",
                                                   brand=DEFAULT_BRAND,
                                                   character=None)
                        escenas_ok = [s for s in export.get("scenes", [])
                                      if (s.get("image_prompt") or {}).get(
                                          "subjects") is not None
                                      or s.get("image_prompt")]
                        _check(checks, "P-PAYLOAD-FLOW",
                               bool(export.get("scenes")) and bool(escenas_ok),
                               f"payload Flow reconstruible: "
                               f"{len(export.get('scenes', []))} escena(s)"
                               if escenas_ok else
                               "payload Flow sin prompts de imagen válidos")
                    except Exception as e:  # noqa: BLE001
                        _check(checks, "P-PAYLOAD-FLOW", False,
                               f"build_script_json revienta: "
                               f"{type(e).__name__}: {e}")

            # cola limpia: nada atascado que interfiera
            try:
                with db.connect() as con:
                    rows = [dict(r) for r in con.execute(
                        """SELECT id, kind, scene_number, status, attempts,
                                  max_attempts, lease_until, job_token
                           FROM flow_jobs WHERE project_id=?""",
                        (project_id,)).fetchall()]
            except Exception as e:  # noqa: BLE001
                rows = None
                _check(checks, "P-QUEUE-LEIBLE", False,
                       f"no se pudo leer la cola: {e}")
            if rows is not None:
                ahora = _ahora_iso()
                dead = [r for r in rows if r["status"] == "dead"]
                vencidos = [r for r in rows if r["status"] == "claimed"
                            and r["lease_until"] and r["lease_until"] < ahora]
                invalidos = [r for r in rows if r["status"] == "claimed"
                             and (not r["lease_until"]
                                  or not r["job_token"])]
                agotados = [r for r in rows if r["status"] == "queued"
                            and int(r["attempts"] or 0)
                            >= int(r["max_attempts"] or 2)]
                problemas = []
                if dead:
                    problemas.append(f"{len(dead)} dead")
                if vencidos:
                    problemas.append(f"{len(vencidos)} lease vencido")
                if invalidos:
                    problemas.append(f"{len(invalidos)} claimed inválido")
                if agotados:
                    problemas.append(f"{len(agotados)} queued agotado")
                _check(checks, "P-QUEUE-LIMPIA", not problemas,
                       f"cola limpia ({len(rows)} job(s))"
                       if not problemas else
                       f"jobs atascados/incompatibles: {', '.join(problemas)} "
                       "— ejecuta DOCTOR FIX o re-encola antes de la prueba")
                pendientes = sum(1 for r in rows if r["status"] != "done")
                if not rows:
                    _check(checks, "P-JOBS-CREADOS", False,
                           "no hay jobs: encola con MCP flow_encolar antes "
                           "de la prueba real")
                else:
                    _check(checks, "P-JOBS-CREADOS", True,
                           f"{len(rows)} job(s) en cola "
                           f"({pendientes} pendiente(s), "
                           f"{len(rows) - pendientes} done)")

    # solo los checks BLOQUEANtes bloquean; un no-demostrado (p.ej.
    # P-EXT-RUNTIME NOT_DEMONSTRATED) se reporta pero no frena el veredicto
    blocked = [c["detalle"] for c in checks
               if not c["ok"] and c.get("bloqueante", True)]
    veredicto = "REAL FLOW PREFLIGHT PASS" if not blocked \
        else "REAL FLOW BLOCKED"
    _ids_structurales = ("P-EXT-MANIFEST", "P-EXT-HOST-PERMISSIONS",
                         "P-EXT-ARCHIVOS", "P-BRIDGE")
    structural_ok = not any(c["id"] in _ids_structurales and not c["ok"]
                            for c in checks)
    return {
        "doctor": "PRODUCTION DOCTOR",
        "version": "1.0",
        "modo": "preflight",
        "preflight": "REAL FLOW PREFLIGHT",
        "verdict": veredicto,
        "ok": not blocked,
        "project_id": project_id,
        "backend_url": base,
        # EXTENSION STRUCTURAL READY (en disco, verificable) ≠
        # EXTENSION RUNTIME CONNECTED (conexión viva, solo con evidencia)
        "extension_structural": "READY" if structural_ok else "NOT_READY",
        "extension_runtime": "CONNECTED" if evidencia_rt
        else "NOT_DEMONSTRATED",
        "extension_runtime_evidence": evidencia_rt,
        "blocked_reasons": blocked,
        "checks": checks,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "nota": ("el preflight NUNCA ejecuta Google Flow: solo verifica "
                 "listos. Reparaciones = DOCTOR FIX. EXTENSION STRUCTURAL "
                 "READY (manifest/archivos/permisos/bridge en disco) ≠ "
                 "EXTENSION RUNTIME CONNECTED (conexión viva Chrome↔"
                 "backend): sin evidencia de lease vigente la conexión se "
                 "clasifica NOT_DEMONSTRATED/UNKNOWN, jamás PASS."),
    }

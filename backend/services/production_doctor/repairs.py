"""
PRODUCTION DOCTOR V1.0 — reparaciones automáticas (LISTA BLANCA CERRADA).

Regla del contrato (sección 6): solo reparaciones DETERMINISTAS y de BAJO
RIESGO, cada una respaldada por una regla contractual YA EXISTENTE en el
repositorio (nunca lógica nueva que «arregle» el sistema):

  recover_expired_leases     → flow_jobs.recover_expired()          (regla existente)
  requeue_invalid_claimed    → claim SIEMPRE pone lease+token       (contrato claim_next)
  deaden_exhausted_queued    → fail() manda a dead al agotar        (contrato fail)
  dedupe_flow_jobs           → enqueue idempotente: 1 job por clave (contrato enqueue)
  delete_orphan_jobs         → proyectos borrados: filas derivadas   (FK lógica)
  rebuild_asset_mapping      → _apply_assets_to_scenes              (función existente)
  rebuild_job_queue          → enqueue_project idempotente          (función existente)
  ensure_directories         → rutas canónicas de config.py
  cleanup_tmp                → temporales conocidos (*.tmp/.part)
  fail_zombie_pipeline_jobs  → mismo criterio que orchestrator._zombie_job

PROHIBIDO para el Doctor (nunca estará en esta lista): tocar production.json,
prompts, duration_target, continuity, references, Niche Blueprints, la
arquitectura o contratos. Eso es HUMAN INVESTIGATION REQUIRED.

Cada reparación devuelve acciones con antes/después y el orquestador (fix)
las registra en el audit trail (core.AuditTrail).
"""
from __future__ import annotations

import time
from pathlib import Path

import config
import database as db

from .core import Finding

TEMP_PATTERNS = ("*.tmp", "*.tmp.mp4", "*.part")
TMP_MIN_EDAD_S = 3600          # solo temporales con >1h de antigüedad


# ── helpers ──────────────────────────────────────────────────────────────────
def _acc(repair: str, fids: list[str], cambio: str, antes: str,
         despues: str, detalles: dict | None = None) -> dict:
    return {"repair": repair, "finding_ids": fids, "cambio": cambio,
            "antes": antes, "despues": despues, "detalles": detalles or {}}


# ── 1. leases vencidos → queued (regla existente recover_expired) ────────────
def _r_recover_expired_leases(fids: list[str], _fs: list[Finding]) -> list[dict]:
    from services import flow_jobs as fj
    n = fj.recover_expired()
    return [_acc("recover_expired_leases", fids,
                 f"recover_expired() devolvió {n} job(s) re-encolado(s)",
                 "claimed con lease vencido", "queued (worker=NULL, lease=NULL)",
                 {"recuperados": n})]


# ── 2. claimed sin lease/token → queued (estado imposible por API) ───────────
def _r_requeue_invalid_claimed(fids: list[str], _fs: list[Finding]) -> list[dict]:
    with db.connect() as con:
        cur = con.execute(
            """UPDATE flow_jobs SET status='queued', worker=NULL,
               job_token=NULL, lease_until=NULL, updated_at=datetime('now')
               WHERE status='claimed'
                 AND (lease_until IS NULL OR job_token IS NULL)""")
        n = cur.rowcount
        con.commit()
    return [_acc("requeue_invalid_claimed", fids,
                 f"{n} job(s) claimed sin lease/token re-encolado(s)",
                 "claimed sin lease/token (no claimable ni completable)",
                 "queued limpio (puede ser reclamado de nuevo)",
                 {"reencolados": n})]


# ── 3. queued con attempts agotados → dead (contrato de fail) ────────────────
def _r_deaden_exhausted_queued(fids, _fs) -> list[dict]:
    # v2.19 · fix: el SQL tenía dos literales adyacentes (concatenación que
    # SQLite NO soporta) → OperationalError SIEMPRE; la deshonestidad del flag
    # reparado lo enmascaraba (finding marcado reparado con la reparación
    # revienta). Ahora el mensaje va por parámetro y la reparación funciona.
    with db.connect() as con:
        cur = con.execute(
            """UPDATE flow_jobs SET status='dead',
               error=?, worker=NULL, job_token=NULL, lease_until=NULL,
               updated_at=datetime('now')
               WHERE status='queued' AND attempts >= max_attempts""",
            ("PRODUCTION DOCTOR: attempts agotados en estado queued "
             "(inconsistencia según contrato de fail)",))
        n = cur.rowcount
        con.commit()
    return [_acc("deaden_exhausted_queued", fids,
                 f"{n} job(s) queued+agotado(s) pasado(s) a dead",
                 "queued con attempts >= max_attempts (invisible para fail)",
                 "dead (estado terminal correcto del contrato)",
                 {"a_dead": n})]


# ── 4. duplicados → conservar el más antiguo (enqueue idempotente) ───────────
def _r_dedupe_flow_jobs(fids, _fs) -> list[dict]:
    with db.connect() as con:
        rows = con.execute(
            """SELECT id, project_id, kind, scene_number, part, status,
                      created_at, rowid FROM flow_jobs
               WHERE status != 'done' ORDER BY created_at, rowid""").fetchall()
        vistos: set[tuple] = set()
        a_borrar: list[str] = []
        for r in rows:
            clave = (r["project_id"], r["kind"], int(r["scene_number"] or 0),
                     int(r["part"] or 1))
            if clave in vistos:
                a_borrar.append(r["id"])
            else:
                vistos.add(clave)
        n = 0
        for jid in a_borrar:
            cur = con.execute("DELETE FROM flow_jobs WHERE id=?", (jid,))
            n += cur.rowcount
        con.commit()
    return [_acc("dedupe_flow_jobs", fids,
                 f"{n} job(s) duplicado(s) eliminado(s) (se conservó el más "
                 "antiguo por clave proyecto:kind:escena:part)",
                 f"{len(vistos) + n} filas no-done con duplicados",
                 f"{len(vistos)} filas, una por clave",
                 {"borrados": n})]


# ── 5. huérfanos → borrar filas de proyectos inexistentes ────────────────────
def _r_delete_orphan_jobs(fids, _fs) -> list[dict]:
    with db.connect() as con:
        proyectos = {r["id"] for r in con.execute("SELECT id FROM projects")}
        fh = con.execute(
            """DELETE FROM flow_jobs WHERE project_id NOT IN
               (SELECT id FROM projects)""").rowcount
        # jobs de pipeline huérfanos QUE NO estén running (no tocar vivos)
        fj2 = con.execute(
            """DELETE FROM jobs WHERE project_id NOT IN
               (SELECT id FROM projects) AND status != 'running'""").rowcount
        con.commit()
    return [_acc("delete_orphan_jobs", fids,
                 f"eliminadas {fh} fila(s) de flow_jobs y {fj2} de jobs "
                 "de proyectos inexistentes",
                 "filas huérfanas de proyectos borrados",
                 "cola consistente con projects",
                 {"flow_jobs_borrados": fh, "jobs_borrados": fj2,
                  "proyectos_vivos": len(proyectos)})]


# ── 6. mapping derivado de assets (función existente _apply_assets_to_scenes) ─
def _r_rebuild_asset_mapping(fids, fs) -> list[dict]:
    from services import flow_jobs as fj
    pids = []
    for f in fs:
        pid = f.evidencia.get("proyecto")
        if pid and pid not in pids:
            pids.append(pid)
    acciones = []
    for pid in pids:
        try:
            with db.connect() as con:
                antes = con.execute(
                    """SELECT COUNT(*) c FROM scenes
                       WHERE project_id=? AND image_path IS NOT NULL
                       AND image_path != ''""", (pid,)).fetchone()["c"]
                all_have = fj._apply_assets_to_scenes(con, pid)
                con.commit()
                despues = con.execute(
                    """SELECT COUNT(*) c FROM scenes
                       WHERE project_id=? AND image_path IS NOT NULL
                       AND image_path != ''""", (pid,)).fetchone()["c"]
            acciones.append(_acc(
                "rebuild_asset_mapping", fids,
                f"mapeo flow/ → scenes.image_path re-aplicado ({pid})",
                f"{antes} escena(s) mapeada(s)",
                f"{despues} escena(s) mapeada(s) · renderable={all_have}",
                {"proyecto": pid, "antes": antes, "despues": despues}))
        except Exception as e:  # noqa: BLE001
            acciones.append(_acc(
                "rebuild_asset_mapping", fids,
                f"no se pudo re-aplicar el mapping de {pid}: {e}",
                "desconocido", "sin cambio", {"proyecto": pid, "error": str(e)}))
    return acciones


# ── 7. cola incompleta → enqueue_project idempotente (conserva done) ─────────
def _r_rebuild_job_queue(fids, fs) -> list[dict]:
    from services import flow_jobs as fj
    pids = []
    for f in fs:
        for m in f.evidencia.get("muestra", []) or []:
            if isinstance(m, str) and ":" in m:
                pid = m.split(":")[0]
                if pid not in pids:
                    pids.append(pid)
    acciones = []
    for pid in pids:
        try:
            res = fj.enqueue_project(pid)
            acciones.append(_acc(
                "rebuild_job_queue", fids,
                "enqueue_project() re-generó la cola (idempotente, conserva "
                f"los done) de {pid}",
                "cola incompleta respecto al contrato P1",
                f"cola completa: {res}",
                {"proyecto": pid, "resultado": res}))
        except (LookupError, ValueError) as e:
            acciones.append(_acc(
                "rebuild_job_queue", fids,
                f"no se pudo re-encolar {pid}: {e}",
                "cola incompleta", "sin cambio",
                {"proyecto": pid, "error": str(e)}))
    return acciones


# ── 8. directorios canónicos de config.py ────────────────────────────────────
def _r_ensure_directories(fids, _fs) -> list[dict]:
    from .core import doctor_dir
    rutas = [Path(config.DATA_DIR), Path(config.OUTPUT_DIR),
             Path(config.TMP_DIR), Path(config.MUSIC_DIR), doctor_dir()]
    creadas, escribibles = [], []
    for d in rutas:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            creadas.append(str(d))
        probe = d / ".doctor_probe"
        try:
            probe.write_bytes(b"ok")
            probe.unlink()
            escribibles.append(str(d))
        except OSError:
            pass
    return [_acc("ensure_directories", fids,
                 f"directorios canónicos verificados ({len(escribibles)}/"
                 f"{len(rutas)} escribibles)",
                 f"creadas: {creadas or 'ninguna'}",
                 f"escribibles: {len(escribibles)}/{len(rutas)}",
                 {"creadas": creadas, "escribibles": escribibles})]


# ── 9. temporales conocidos (>1h) ────────────────────────────────────────────
def _r_cleanup_tmp(fids, _fs) -> list[dict]:
    raices = [Path(config.OUTPUT_DIR), Path(config.TMP_DIR)]
    ahora = time.time()
    borrados, bytes_liberados = [], 0
    for raiz in raices:
        if not raiz.exists():
            continue
        for pat in TEMP_PATTERNS:
            for p in raiz.rglob(pat):
                try:
                    if not p.is_file() or ahora - p.stat().st_mtime < TMP_MIN_EDAD_S:
                        continue
                    bytes_liberados += p.stat().st_size
                    p.unlink()
                    borrados.append(str(p.relative_to(raiz)))
                except OSError:
                    continue
    return [_acc("cleanup_tmp", fids,
                 f"eliminados {len(borrados)} temporal(es) conocidos "
                 f"({bytes_liberados / 1e6:.1f} MB)",
                 f"{len(borrados)} temporales >1h", "limpios",
                 {"borrados": borrados[:20], "bytes": bytes_liberados})]


# ── 10. zombies del pipeline (solo in-process, criterio orchestrator) ────────
def _r_fail_zombie_pipeline_jobs(fids, _fs) -> list[dict]:
    from pipeline import orchestrator
    with db.connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT id, project_id FROM jobs WHERE status='running'").fetchall()]
        n = 0
        for j in rows:
            reg = orchestrator.JOBS.get(j["id"])
            if not (reg and reg.get("task")):
                con.execute(
                    """UPDATE jobs SET status='failed',
                       error='interrumpido por reinicio del servidor',
                       updated_at=datetime('now') WHERE id=?""", (j["id"],))
                n += 1
        con.commit()
    return [_acc("fail_zombie_pipeline_jobs", fids,
                 f"{n} job(s) zombie(s) marcado(s) failed",
                 "running sin tarea viva",
                 "failed (el proyecto puede relanzarse limpio)",
                 {"marcados": n})]


# ── registro de reparaciones seguras ─────────────────────────────────────────
SAFE_REPAIRS: dict[str, dict] = {
    "recover_expired_leases": {
        "descripcion": "leases vencidos → queued (flow_jobs.recover_expired)",
        "componente": "flow_jobs", "archivo": "backend/services/flow_jobs.py",
        "funcion": "recover_expired", "fn": _r_recover_expired_leases},
    "requeue_invalid_claimed": {
        "descripcion": "claimed sin lease/token → queued (estado imposible "
                       "según el contrato de claim_next)",
        "componente": "flow_jobs", "archivo": "backend/services/flow_jobs.py",
        "funcion": "claim_next (regla de lease)", "fn": _r_requeue_invalid_claimed},
    "deaden_exhausted_queued": {
        "descripcion": "queued con attempts agotados → dead (contrato fail)",
        "componente": "flow_jobs", "archivo": "backend/services/flow_jobs.py",
        "funcion": "fail (regla de attempts)", "fn": _r_deaden_exhausted_queued},
    "dedupe_flow_jobs": {
        "descripcion": "duplicados no-done → conservar el más antiguo "
                       "(enqueue idempotente)",
        "componente": "flow_jobs", "archivo": "backend/services/flow_jobs.py",
        "funcion": "enqueue_project (idempotencia)", "fn": _r_dedupe_flow_jobs},
    "delete_orphan_jobs": {
        "descripcion": "filas de proyectos inexistentes → borrar",
        "componente": "flow_jobs", "archivo": "backend/services/flow_jobs.py",
        "funcion": "integridad referencial (FK lógica)", "fn": _r_delete_orphan_jobs},
    "rebuild_asset_mapping": {
        "descripcion": "re-aplicar mapeo flow/ → scenes.image_path "
                       "(_apply_assets_to_scenes existente)",
        "componente": "flow_jobs", "archivo": "backend/services/flow_jobs.py",
        "funcion": "_apply_assets_to_scenes", "fn": _r_rebuild_asset_mapping},
    "rebuild_job_queue": {
        "descripcion": "cola incompleta → enqueue_project idempotente "
                       "(conserva done; NO toca prompts)",
        "componente": "flow_jobs", "archivo": "backend/services/flow_jobs.py",
        "funcion": "enqueue_project", "fn": _r_rebuild_job_queue},
    "ensure_directories": {
        "descripcion": "crear/verificar directorios canónicos de config.py",
        "componente": "doctor", "archivo": "backend/config.py",
        "funcion": "rutas canónicas", "fn": _r_ensure_directories},
    "cleanup_tmp": {
        "descripcion": "borrar temporales conocidos (*.tmp/*.part) con >1h",
        "componente": "doctor", "archivo": "backend/config.py",
        "funcion": "TMP_DIR/OUTPUT_DIR limpieza", "fn": _r_cleanup_tmp},
    "fail_zombie_pipeline_jobs": {
        "descripcion": "jobs 'running' sin tarea viva → failed (criterio "
                       "orchestrator._zombie_job; SOLO in-process)",
        "componente": "orchestrator", "archivo": "backend/pipeline/orchestrator.py",
        "funcion": "_zombie_job", "fn": _r_fail_zombie_pipeline_jobs},
}


def aplicar_reparaciones(findings: list[Finding]) -> tuple[list[dict], list[str]]:
    """Aplica las reparaciones seguras a los findings reparables.
    Devuelve (acciones, componentes_afectados). NO escribe el audit trail
    (eso lo hace el orquestador fix() con metadatos del registro)."""
    acciones: list[dict] = []
    componentes: list[str] = []
    reparables = [f for f in findings
                  if f.reparacion_disponible and f.reparacion_accion
                  and not f.reparado]
    por_repair: dict[str, list[Finding]] = {}
    for f in reparables:
        por_repair.setdefault(f.reparacion_accion, []).append(f)
    for rid, fs in por_repair.items():
        spec = SAFE_REPAIRS.get(rid)
        if spec is None:
            continue  # defensa: nunca ejecutar una reparación fuera de la lista
        fallo = False
        try:
            nuevas = spec["fn"]([f.id for f in fs], fs)
        except Exception as e:  # noqa: BLE001
            fallo = True
            nuevas = [_acc(rid, [f.id for f in fs],
                           f"la reparación revintió: {type(e).__name__}: {e}",
                           "desconocido", "sin cambio", {"error": str(e)[:200]})]
        for a in nuevas:
            a["archivo_afectado"] = spec["archivo"]
            a["funcion_afectada"] = spec["funcion"]
            a["componente"] = spec["componente"]
        acciones.extend(nuevas)
        if spec["componente"] not in componentes:
            componentes.append(spec["componente"])
        for f in fs:
            # v2.19 · honestidad del audit trail: si la reparación revintió,
            # el finding NO se marca reparado (antes se marcaba aunque la
            # acción registrara el error → VERIFY daba falso «resuelto»).
            f.reparado = not fallo
            f.detalle_reparacion = "" if fallo else "; ".join(
                a["cambio"] for a in nuevas if a.get("finding_ids"))[:300]
    return acciones, componentes

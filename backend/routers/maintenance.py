"""
P6.4 · ENTREGA 1 — Router de MANTENIMIENTO (backups + retención de medios).

Extracción desde backend/main.py (3.352 líneas → routers por dominio:
projects, media, flow, mcp, config, publish). Esta entrega solo mueve el
dominio autocontenido maintenance/ (backups v2.12.2 + retención P5.4 de
data/output). El resto de dominios migra en las siguientes entregas con la
suite verde entre cada una.

Los endpoints conservan EXACTamente las mismas rutas y respuestas (cero
ruptura para la UI y las baterías).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

import database as db
from services import backup as backup_svc

log = logging.getLogger("maintenance")

router = APIRouter(prefix="/api", tags=["maintenance"])


def _to_int(v, default: int, name: str) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"'{name}' debe ser un entero") from None


def _pid(pid: str) -> str:
    """C1 · formato canónico del project_id (misma política que main)."""
    import security
    try:
        return security.validate_project_id(pid)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


# ─────────────────────────── backups (v2.12.2 · resiliencia) ──
@router.get("/backups")
async def backups_list():
    """Backups disponibles (SOLO DB desde P0.1·C1: los secretos .env/
    token.json ya no se copian en claro) — el más nuevo primero."""
    return {"dir": str(backup_svc.BACKUP_DIR), "keep": backup_svc.KEEP,
            "interval_h": backup_svc.INTERVAL_H, "backups": backup_svc.list_backups()}


@router.post("/backups")
async def backups_create():
    """Crea un backup ahora mismo (manual)."""
    r = await asyncio.to_thread(backup_svc.create_backup, "manual")
    if not r:
        raise HTTPException(500, "el backup falló — revisa el log del servidor")
    return {"ok": True, "backup": r, "message": "Backup creado ✅"}


@router.post("/backups/restore")
async def backups_restore(body: dict):
    """Restaura un backup (antes deja uno de seguridad pre-restore)."""
    name = str((body or {}).get("name") or "")
    try:
        r = await asyncio.to_thread(backup_svc.restore_backup, name)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **r,
            "message": f"Restaurado {name} — reinicia el servidor para recargar todo"}


# ── [P5.4] política de RETENCIÓN de data/output (dry-run + acción explícita) ──
@router.get("/maintenance/output/plan")
async def maintenance_output_plan(n: int = 0):
    """Plan de retención de data/output (DRY-RUN: no borra nada).
    Conserva los N proyectos más recientes con medios (N = ?n= o
    OUTPUT_RETENTION_PROJECTS, default 10) + los marcados con meta.keep=true
    + los que tienen job activo; el resto aparece como borrable con tamaño."""
    from services import retention
    return await asyncio.to_thread(
        retention.plan, _to_int(n, 0, "n") or None)


@router.post("/maintenance/output/purge")
async def maintenance_output_purge(body: dict):
    """Limpieza EXPLÍCITA de medios según el plan de retención.
    P5.4: sin confirm=true responde con el plan (dry-run) y NO borra nada.
    Con confirm=true borra SOLO lo borrable (nunca meta.keep ni jobs activos)."""
    from services import retention
    n = (body or {}).get("n")
    confirm = bool((body or {}).get("confirm"))
    r = await asyncio.to_thread(
        retention.purge, _to_int(n, 0, "n") or None, confirm)
    if not r.get("ok"):
        return r  # dry-run informativo (no es error del servidor)
    return r


@router.post("/projects/{pid}/keep")
async def project_keep(pid: str, body: dict):
    """Marca/desmarca un proyecto como RETENIDO (meta.keep=true): la política
    de retención de data/output jamás purga los marcados."""
    _pid(pid)
    p = db.get_project(_pid(pid))
    if not p:
        raise HTTPException(404, "no existe")
    keep = bool((body or {}).get("keep", True))
    meta = dict(p.get("meta") or {})
    meta["keep"] = keep
    db.update_project(pid, meta=meta)
    return {"ok": True, "project_id": pid, "keep": keep}

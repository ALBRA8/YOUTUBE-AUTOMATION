"""
YOUTUBE AUTOMATION v2.0 — Política de RETENCIÓN de data/output (P5.4)

data/output crece sin límite (medido: 225,7 MB y creciendo): cada proyecto
deja su MP4 final, flow assets, contact sheets y words.json.

Regla del mandato: NUNCA se borra un medio del usuario de forma automática
y siempre con dry-run previo. Este módulo:
  · plan(n): INFORME (dry-run) — qué se conservaría y qué sería borrable,
    con tamaños. No toca disco.
  · purge(n, confirm): acción EXPLÍCITA (confirm=True obligatorio). Borra
    SOLO los directorios de salida de proyectos que:
        - NO están entre los N más recientes con medios, Y
        - NO están marcados (meta.keep=true), Y
        - NO tienen job activo,
    y deja constancia en la fila del proyecto (meta.media_purged=true,
    video_url="") para que la DB no apunte a un medio muerto.

Conservación configurable: config.LIMITS["OUTPUT_RETENTION_PROJECTS"]
(env OUTPUT_RETENTION_PROJECTS, default 10).
"""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

import database as db
from config import OUTPUT_DIR

log = logging.getLogger("retention")


def _default_n() -> int:
    from config import LIMITS
    try:
        return max(1, int(LIMITS.get("OUTPUT_RETENTION_PROJECTS", 10)))
    except (TypeError, ValueError):
        return 10


def _proyectos_con_medios() -> list[dict]:
    out = []
    for p in db.list_projects():
        pid = p.get("id")
        d = OUTPUT_DIR / str(pid)
        if pid and d.is_dir():
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            out.append({
                "id": pid,
                "title": p.get("title") or "",
                "created_at": p.get("created_at") or "",
                "updated_at": p.get("updated_at") or "",
                "keep": bool((p.get("meta") or {}).get("keep")),
                "active_job": bool(db.active_job_for_project(pid)),
                "media_size": size,
                "dir": str(d),
            })
    out.sort(key=lambda x: (x["updated_at"] or x["created_at"]), reverse=True)
    return out


def plan(n: int | None = None) -> dict:
    """DRY-RUN: clasifica los proyectos con medios en conservar/borrables.
    Nunca toca disco."""
    n = n or _default_n()
    proyectos = _proyectos_con_medios()
    conservar, borrables = [], []
    vistos = 0
    for p in proyectos:
        if p["keep"] or p["active_job"]:
            conservar.append({**p, "motivo": "marcado (meta.keep)" if p["keep"]
                              else "job activo"})
            continue
        vistos += 1
        if vistos <= n:
            conservar.append({**p, "motivo": f"reciente (top {n})"})
        else:
            borrables.append(p)
    total_borrable = sum(p["media_size"] for p in borrables)
    return {
        "ok": True,
        "n": n,
        "dry_run": True,
        "total_con_medios": len(proyectos),
        "conservar": conservar,
        "borrables": borrables,
        "liberables_bytes": total_borrable,
        "liberables_mb": round(total_borrable / (1024 * 1024), 1),
        "nota": "dry-run: nada se ha borrado. POST /api/maintenance/output/purge "
                "con confirm=true aplica (respeta meta.keep y jobs activos)",
    }


def purge(n: int | None = None, confirm: bool = False) -> dict:
    """Acción EXPLÍCITA de limpieza. Sin confirm=True no borra NADA (400).
    Devuelve lo borrado con tamaños reales."""
    if not confirm:
        return {"ok": False, "error": "confirm=false: política P5.4 — la "
                "limpieza es EXPLÍCITA. Consulta el plan en "
                "GET /api/maintenance/output/plan y repite con confirm=true",
                "dry_run": True, "plan": plan(n)}
    n = n or _default_n()
    p = plan(n)
    borrados, liberados = [], 0
    for item in p["borrables"]:
        pid = item["id"]
        d = Path(item["dir"])
        try:
            size = item["media_size"]
            shutil.rmtree(d, ignore_errors=False)
            liberados += size
            borrados.append({"project_id": pid, "liberados_bytes": size})
            proj = db.get_project(pid) or {}
            meta = dict(proj.get("meta") or {})
            meta["media_purged"] = True
            meta["media_purged_at"] = time.time()
            db.update_project(pid, video_url="", meta=meta)
            log.info("retención: medios de %s purgados (%.1f MB)",
                     pid, size / (1024 * 1024))
        except OSError as e:
            borrados.append({"project_id": pid, "error": str(e)[:160]})
    return {"ok": True, "n": n, "borrados": borrados,
            "liberados_bytes": liberados,
            "liberados_mb": round(liberados / (1024 * 1024), 1)}

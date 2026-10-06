"""
Métricas — observabilidad de un vistazo para la fábrica (Fase observabilidad).

Un único snapshot con TODO lo barato de contar (puras queries agregadas +
tamaño de disco, cero subprocess pesado):

  · proyectos por estado (draft → ready → published …)
  · cola Flow por estado (queued/claimed/done/dead) + dead por kind
  · jobs de pipeline por estado (running/done/failed/cancelled)
  · escenas totales y sin imagen (cuello de botella típico)
  · disco ocupado por data/output (y nº de archivos)

Pensado para el endpoint GET /api/metrics y para la tool MCP metricas().
Nada de suposiciones: si una tabla no existe aún devuelve 0s.
"""
from __future__ import annotations

from pathlib import Path

import database as db
from config import OUTPUT_DIR


def _group(con, table: str, col: str = "status") -> dict:
    """COUNT(*) GROUP BY tolerante a tabla ausente (0s en vez de 500)."""
    try:
        rows = con.execute(
            f"SELECT {col} k, COUNT(*) c FROM {table} GROUP BY {col}"
        ).fetchall()
        return {str(r["k"] or "null"): int(r["c"]) for r in rows}
    except Exception:  # noqa: BLE001  (tabla aún no creada / DB vieja)
        return {}


def _dir_stats(root: Path) -> dict:
    files = size = 0
    if root.exists():
        for p in root.rglob("*"):
            try:
                if p.is_file():
                    files += 1
                    size += p.stat().st_size
            except OSError:
                continue
    return {"files": files, "bytes": size,
            "mb": round(size / (1024 * 1024), 1)}


def snapshot() -> dict:
    with db.connect() as con:
        projects = _group(con, "projects")
        flow = _group(con, "flow_jobs")
        jobs = _group(con, "jobs")
        scenes_total = con.execute(
            "SELECT COUNT(*) c FROM scenes").fetchone()["c"]
        scenes_no_img = con.execute(
            "SELECT COUNT(*) c FROM scenes WHERE image_path IS NULL "
            "OR image_path=''").fetchone()["c"]
        flow_dead = con.execute(
            """SELECT kind, COUNT(*) c FROM flow_jobs WHERE status='dead'
               GROUP BY kind""").fetchall()
    return {
        "ok": True,
        "projects": {"by_status": projects,
                     "total": sum(projects.values())},
        "flow_queue": {"by_status": flow,
                       "total": sum(flow.values()),
                       "dead_by_kind": {str(r["kind"]): int(r["c"])
                                        for r in flow_dead}},
        "pipeline_jobs": {"by_status": jobs,
                          "total": sum(jobs.values())},
        "scenes": {"total": scenes_total, "without_image": scenes_no_img},
        "disk_output": _dir_stats(Path(OUTPUT_DIR)),
    }

"""
Métricas — observabilidad de un vistazo para la fábrica (Fase observabilidad).

Un único snapshot con TODO lo barato de contar (puras queries agregadas +
tamaño de disco, cero subprocess pesado):

  · proyectos por estado (draft → ready → published …)
  · cola Flow por estado (queued/claimed/done/dead) + dead por kind
  · jobs de pipeline por estado (running/done/failed/cancelled)
  · escenas totales y sin imagen (cuello de botella típico)
  · disco ocupado por data/output (y nº de archivos)
  · v2.19 · tasas §observabilidad: producción/pasos/reintentos/QA/publicación

Pensado para el endpoint GET /api/metrics y para la tool MCP metricas().
Nada de suposiciones: si una tabla no existe aún devuelve 0s; las tasas que
no se pueden medir localmente (latencia de cola, costo) quedan null HONESTAS.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import database as db
from config import DATA_DIR, OUTPUT_DIR

# persistencia de snapshots (JSONL, recortado a las últimas 500 líneas)
SNAPSHOTS_PATH = DATA_DIR / "metrics" / "snapshots.jsonl"


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


def _rates(con) -> dict:
    """Tasas §observabilidad computables con las tablas existentes.
    Las no medibles localmente quedan null (honestidad del informe)."""
    def _one(sql, *args):
        try:
            r = con.execute(sql, args).fetchone()
            return {k: r[k] for k in r.keys()}
        except Exception:  # noqa: BLE001 — tabla vieja
            return {}

    p = _one("""SELECT
        SUM(CASE WHEN status IN ('ready','published') THEN 1 ELSE 0 END) ok,
        SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) bad,
        COUNT(*) total FROM projects""")
    done = (p.get("ok") or 0) + (p.get("bad") or 0)
    prod_rate = round((p.get("ok") or 0) / done, 4) if done else None

    j = _one("""SELECT
        SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) ok,
        SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) bad,
        COUNT(*) total FROM jobs""")
    jdone = (j.get("ok") or 0) + (j.get("bad") or 0)
    step_rate = round((j.get("ok") or 0) / jdone, 4) if jdone else None

    f = _one("""SELECT
        SUM(CASE WHEN status='dead' THEN 1 ELSE 0 END) dead,
        SUM(COALESCE(attempts,0)) attempts, COUNT(*) total FROM flow_jobs""")
    retry_rate = (round((f.get("attempts") or 0) / f["total"], 4)
                  if f.get("total") else None)
    dead_rate = (round((f.get("dead") or 0) / f["total"], 4)
                 if f.get("total") else None)

    qa_bad = 0
    qa_total = 0
    try:
        for r in con.execute(
                "SELECT meta FROM projects WHERE meta LIKE '%qa_final%'"):
            qf = ((json.loads(r["meta"] or "{}").get("qa_final")) or {})
            worst = qf.get("worst")
            if worst:
                qa_total += 1
                if worst == "error":
                    qa_bad += 1
    except Exception:  # noqa: BLE001
        pass
    qa_rate = round(qa_bad / qa_total, 4) if qa_total else None

    pub = _one("""SELECT
        SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) bad, COUNT(*) total
        FROM jobs WHERE kind='publish'""")
    pub_rate = (round((pub.get("bad") or 0) / pub["total"], 4)
                if pub.get("total") else None)

    return {
        "production_success_rate": prod_rate,
        "step_success_rate": step_rate,
        "provider_failure_rate": dead_rate,       # proxy honesto: dead/total de la cola Flow
        "retry_rate": retry_rate,
        "recovery_rate": None,                    # no medible aún (se registraría con flow_events)
        "queue_latency": None,                    # no medible: faltan started_at/completed_at por job
        "render_time": None,                      # no medible aún (timestamps por etapa)
        "qa_failure_rate": qa_rate,
        "publish_failure_rate": pub_rate,
        "cost_per_production": 0.0,               # fábrica $0 (claves gratuitas/locales)
    }


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
        rates = _rates(con)
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
        "rates": rates,
    }


def persist_snapshot() -> dict:
    """Append del snapshot actual a data/metrics/snapshots.jsonl (JSONL,
    recortado a las últimas 500 líneas). Nunca lanza: la observabilidad
    jamás tumba el pipeline."""
    try:
        snap = snapshot()
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "rates": snap.get("rates"),
               "projects_total": snap["projects"]["total"],
               "flow_total": snap["flow_queue"]["total"]}
        SNAPSHOTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SNAPSHOTS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        # recorte (lee todas, reescribe últimas 500 — archivos pequeños)
        lines = SNAPSHOTS_PATH.read_text(encoding="utf-8").splitlines()
        if len(lines) > 500:
            SNAPSHOTS_PATH.write_text(
                "\n".join(lines[-500:]) + "\n", encoding="utf-8")
        return rec
    except Exception as e:  # noqa: BLE001
        from logging import getLogger
        getLogger("metrics").warning("persist_snapshot falló: %s", e)
        return {}

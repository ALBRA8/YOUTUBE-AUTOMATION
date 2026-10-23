# ─────────────────────────────────────────────────────────────────────
# YOUTUBE HARNESS — adapter.py
# ─────────────────────────────────────────────────────────────────────
# Adaptador: traduce operaciones del contrato → llamadas a la fábrica
# EXISTENTE (database / orchestrator / flow_jobs / production_json /
# production_doctor / video_qa / youtube_publish / niches / themes /
# security). Es una FACHADA DE DOMINIO: cero reescritura del motor,
# cero lógica nueva de negocio; SOLO invocación + normalización a
# diccionarios abstractos (nunca filas SQLite crudas, §8).
#
# Componentes de alto riesgo (§5): orchestrator, flow_jobs,
# execution_contract, production_doctor, database… se CONSUMEN tal cual;
# no se reestructuran.
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

import shutil
from typing import Any, Callable

import database as db
import security
from services import niches as niches_svc
from services import production_json as prod_svc
from services import video_qa as qa_svc
from services import youtube_publish
from services.themes import STYLES, get_style
from pipeline import orchestrator
from pipeline import video as video_pipeline

from .contracts import (ACCEPTED, BLOCKED, FAILED, PUBLISHED, READY,
                        RUNNING, HarnessValidationError, normalize_status)


class AdapterError(Exception):
    """Error de operación con código de contrato para el host."""

    def __init__(self, code: str, message: str, *,
                 status: str = FAILED, recoverable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.recoverable = recoverable


def _pid(raw: Any) -> str:
    """Valida id de proyecto (C1: fail-closed, formato canónico)."""
    try:
        return security.validate_project_id(str(raw or ""))
    except ValueError as exc:
        raise AdapterError("VALIDATION", f"project_id inválido: {exc}",
                           status=BLOCKED) from None


def _require(input: dict, key: str) -> Any:
    val = input.get(key)
    if val is None or (isinstance(val, str) and not val.strip()):
        raise AdapterError(
            "VALIDATION", f"input.{key} es obligatorio para esta operación",
            status=BLOCKED)
    return val


def _project_abstract(p: dict, *, include_scenes: bool = False) -> dict:
    """Fila SQLite → diccionario abstracto del contrato (§8)."""
    recoverable = False
    job = None
    if p.get("status") == "failed":
        # evidencia de recuperación: job activo o flow_jobs re-encolables
        job = db.active_job_for_project(p["id"])
        try:
            from services import flow_jobs
            counts = flow_jobs.status_for_project(p["id"]).get("counts", {})
            recoverable = bool(counts.get("queued") or counts.get("claimed"))
        except Exception:  # noqa: BLE001 — la evidencia es best-effort
            recoverable = False
    out = {
        "project_id": p["id"],
        "title": p.get("title"),
        "status": normalize_status(p.get("status"), recoverable=recoverable),
        "internal_status": p.get("status"),
        "step": p.get("step_label"),
        "progress": p.get("progress"),
        "format": p.get("format"),
        "style": p.get("style"),
        "niche": p.get("niche"),
        "platforms": p.get("platforms") or [],
        "video_ready": bool(p.get("video_url")),
        "youtube_id": p.get("youtube_id"),
        "error": (p.get("error") or "")[:300] or None,
        "updated_at": p.get("updated_at"),
    }
    if include_scenes:
        scenes = db.get_scenes(p["id"])
        out["scenes_count"] = len(scenes)
        out["scenes"] = [
            {"scene_id": s["id"], "idx": s.get("idx"),
             "status": s.get("status"), "title": s.get("title")}
            for s in scenes]
    if job is not None:
        out["job_id"] = job.get("id")
        out["job_status"] = normalize_status(job.get("status"), kind="job")
    return out


# ═══════════════════════════════ lectura ═════════════════════════════

def op_list_projects(input: dict) -> dict:
    limit = input.get("limit", 40)
    try:
        limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        limit = 40
    rows = db.list_projects(limit=limit)
    return {"projects": [_project_abstract(p) for p in rows],
            "count": len(rows)}


def op_project_status(input: dict) -> dict:
    pid = _pid(_require(input, "project_id"))
    p = db.get_project(pid)
    if not p:
        raise AdapterError("NOT_FOUND", f"no existe el proyecto {pid}")
    out = _project_abstract(p, include_scenes=True)
    try:
        from services import flow_jobs
        st = flow_jobs.status_for_project(pid)
        out["flow"] = {
            "counts": st.get("counts", {}),
            "jobs": [{"flow_job_id": j.get("id"), "scene_number": j.get("scene_number"),
                      "kind": j.get("kind"), "status": j.get("status"),
                      "external_status": normalize_status(j.get("status"), kind="flow"),
                      "attempts": j.get("attempts")}
                     for j in (st.get("jobs") or [])[:20]],
        }
    except Exception:  # noqa: BLE001 — flow es información adicional
        out["flow"] = None
    return out


def op_list_niches(input: dict) -> dict:
    tpls = niches_svc.list_templates()
    return {"niches": [{"id": t.get("id"), "name": t.get("name"),
                        "emoji": t.get("emoji"),
                        "description": t.get("description"),
                        "style": t.get("style"), "format": t.get("format")}
                       for t in tpls], "count": len(tpls)}


def op_list_styles(input: dict) -> dict:
    return {"styles": [{"id": s.get("id"), "name": s.get("name")}
                       for s in STYLES], "count": len(STYLES)}


def op_list_avatars(input: dict) -> dict:
    rows = db.list_avatars()
    return {"avatars": [{"id": a.get("id"), "name": a.get("name")}
                        for a in rows], "count": len(rows)}


def op_system_status(input: dict) -> dict:
    counts: dict[str, int] = {}
    try:
        for p in db.list_projects(limit=200):
            ext = normalize_status(p.get("status"))
            counts[ext] = counts.get(ext, 0) + 1
    except Exception:  # noqa: BLE001
        counts = {}
    from services import gemini_client, nvidia_client, whisper_service
    return {
        "harness": "youtube-harness",
        "providers": {
            "nvidia": bool(nvidia_client.available()),
            "gemini": bool(gemini_client.available()),
            "whisper": whisper_service.available(),
            "youtube_publish": youtube_publish.configured(),
        },
        "counters": counts,
    }


def op_flow_status(input: dict) -> dict:
    pid = _pid(_require(input, "project_id"))
    if not db.get_project(pid):
        raise AdapterError("NOT_FOUND", f"no existe el proyecto {pid}")
    from services import flow_jobs
    st = flow_jobs.status_for_project(pid)
    jobs = st.get("jobs") or []
    return {"project_id": pid,
            "counts": st.get("counts", {}),
            "jobs": [{"flow_job_id": j.get("id"),
                      "kind": j.get("kind"),
                      "scene_number": j.get("scene_number"),
                      "status": j.get("status"),
                      "external_status": normalize_status(j.get("status"),
                                                          kind="flow"),
                      "attempts": j.get("attempts"),
                      "lease_until": j.get("lease_until")}
                     for j in jobs[:50]]}


def op_flow_preflight(input: dict) -> dict:
    from services.production_doctor import preflight as pdoc_preflight
    pid = input.get("project_id")
    if pid:
        _pid(pid)
    rep = pdoc_preflight(pid)
    ok = bool(rep.get("ok") or rep.get("pass") or
              str(rep.get("status", "")).upper().endswith("PASS"))
    return {"preflight": "PASS" if ok else "BLOCKED", "report": rep}


def op_production_doctor(input: dict) -> dict:
    action = (input.get("action") or "audit").strip().lower()
    deep = bool(input.get("deep"))
    if action == "audit":
        from services.production_doctor import audit as pdoc_audit
        return {"action": "audit", "report": pdoc_audit(deep=deep, in_process=True)}
    if action == "fix":
        from services.production_doctor import fix as pdoc_fix
        return {"action": "fix",
                "report": pdoc_fix(deep=deep, in_process=True,
                                   ejecutar_tests=bool(input.get("ejecutar_tests", False)))}
    if action == "verify":
        from services.production_doctor import verify as pdoc_verify
        return {"action": "verify",
                "report": pdoc_verify(deep=deep, in_process=True,
                                      capas=input.get("capas"),
                                      componentes=input.get("componentes"),
                                      ejecutar_tests=bool(input.get("ejecutar_tests", False)))}
    if action == "report":
        from services.production_doctor import report as pdoc_report
        return {"action": "report", "report": pdoc_report()}
    raise AdapterError("VALIDATION",
                       f"production_doctor.action inválida: {action!r} "
                       "(audit|fix|verify|report)", status=BLOCKED)


def op_validate_production(input: dict) -> dict:
    payload = input.get("production_json")
    if payload is None:
        raise AdapterError("VALIDATION",
                           "input.production_json es obligatorio",
                           status=BLOCKED)
    try:
        data = prod_svc.parse_payload(payload)
        modelo, avisos, norms = prod_svc.validate(
            data, {s["id"] for s in STYLES})
    except ValueError as exc:
        return {"valid": False, "outcome": "VALIDATION_ERROR",
                "errors": [{"code": "VALIDATION", "message": str(exc)[:800]}],
                "warnings": [], "normalizations": []}
    return {"valid": True, "outcome": "OK",
            "errors": [],
            "warnings": [str(a)[:300] for a in avisos],
            "normalizations": [str(n)[:300] for n in norms],
            "unidades": len(modelo.get("escenas") or [])}


def op_video_qa(input: dict) -> dict:
    pid = _pid(_require(input, "project_id"))
    if not db.get_project(pid):
        raise AdapterError("NOT_FOUND", f"no existe el proyecto {pid}")
    rep = qa_svc.qa_project(pid)
    worst = (rep.get("worst") or "").lower() if isinstance(rep, dict) else ""
    return {"project_id": pid, "qa": rep,
            "external_status": READY if worst not in ("error",) else FAILED}


# ═══════════════════════════════ mutación ════════════════════════════

def op_create(input: dict) -> dict:
    """Crea proyecto draft (modo idea o nicho-plantilla). NO lanza.

    Semántica extraída de VÓRTICE (agent.py execute/create_video) pero
    SIN lanzamiento: crear y lanzar son operaciones separadas del
    contrato (§13) para que el host coordine explícitamente.
    """
    idea = str(input.get("idea") or "").strip()
    nicho = str(input.get("nicho") or "").strip()
    fmt = input.get("format") or ("short" if not nicho else None)
    style = str(input.get("style") or "auto").strip()[:40]
    platforms = input.get("platforms")
    if not idea and not nicho:
        raise AdapterError(
            "VALIDATION", "se requiere input.idea o input.nicho (plantilla)",
            status=BLOCKED)
    meta: dict = {"via": "harness"}
    title = idea[:60] or None
    if nicho:
        tpl = niches_svc.get_template(nicho)
        if not tpl:
            raise AdapterError("NOT_FOUND",
                               f"no existe la plantilla de nicho {nicho!r} "
                               "(usa youtube.list_niches)")
        style = tpl.get("style") or style
        fmt = tpl.get("format") or fmt
        composed = niches_svc.compose_idea(tpl, idea or None)
        meta.update({"idea": composed, "niche_template": tpl["id"],
                     "transitions": True, "style_reference": True,
                     "subtitle_style": tpl.get("subtitles") or "shorts"})
        title = title or f"Video {tpl.get('name') or nicho}"
        plats = platforms or ["youtube"]
    else:
        meta["idea"] = idea[:180]
        plats = platforms or ["youtube", "tiktok"]
    valid_plats = {"youtube", "tiktok", "instagram", "facebook"}
    plats = [str(x)[:20] for x in (plats or [])][:4]
    plats = [x for x in plats if x in valid_plats] or ["youtube"]
    p = db.create_project(title=title or "Producción arnés", mode="idea",
                          style=style, format=fmt or "short",
                          meta=meta, platforms=plats, niche=nicho or "")
    return {"project": _project_abstract(p)}


def _crear_production(g: dict) -> dict:
    """Callback de creación para prod_svc.ingest (idéntico al contrato
    A2A de main.py: mismo mode/meta/plataformas — sin duplicar motor)."""
    pmeta: dict = {"via": "harness"}
    if g.get("camara"):
        pmeta["camara"] = g["camara"]
    return db.create_project(
        title=(g.get("titulo") or "Producción arnés"),
        mode="production_json", style=g.get("estilo") or "auto",
        format=g.get("formato") or "short", voice=g.get("voz"),
        meta=pmeta, platforms=g.get("plataformas") or ["youtube"],
        niche=g.get("nicho"))


async def op_submit_production(input: dict, *, launch: bool) -> dict:
    payload = input.get("production_json")
    if payload is None:
        raise AdapterError("VALIDATION",
                           "input.production_json es obligatorio",
                           status=BLOCKED)
    try:
        rep = await prod_svc.ingest(
            payload, {s["id"] for s in STYLES}, _crear_production,
            auto_start_override=True if launch else None)
    except ValueError as exc:
        raise AdapterError("VALIDATION", str(exc), status=BLOCKED) from None
    return {"project_id": rep.get("project_id"),
            "job_id": rep.get("job_id"),
            "unidades": rep.get("unidades"),
            "unit_types": rep.get("unit_types"),
            "formato": rep.get("formato"), "estilo": rep.get("estilo"),
            "warnings": [str(a)[:300] for a in (rep.get("avisos") or [])],
            "production_file": rep.get("production_file")}


async def op_launch(input: dict, *, autopublish: bool = False) -> dict:
    pid = _pid(_require(input, "project_id"))
    p = db.get_project(pid)
    if not p:
        raise AdapterError("NOT_FOUND", f"no existe el proyecto {pid}")
    job_id = await orchestrator.start_pipeline(pid, autopublish=autopublish)
    return {"project_id": pid, "job_id": job_id,
            "status": RUNNING,
            "internal_status": "queued(pipeline)",
            "note": "sigue con youtube.project_status o "
                    "GET /api/harness/v1/executions (SSE interno del job)"}


def op_cancel(input: dict) -> dict:
    job_id = input.get("job_id")
    pid = input.get("project_id")
    if job_id:
        ok = orchestrator.cancel_job(str(job_id))
        if not ok:
            raise AdapterError("CONFLICT",
                               f"job {job_id} no cancelable (no existe o "
                               "ya terminó)")
        return {"job_id": str(job_id), "cancelled": True}
    pid = _pid(pid)
    job = db.active_job_for_project(pid)
    if not job:
        raise AdapterError("NOT_FOUND",
                           f"el proyecto {pid} no tiene job activo")
    orchestrator.cancel_job(job["id"])
    return {"project_id": pid, "job_id": job["id"], "cancelled": True}


def op_recover(input: dict) -> dict:
    from services import flow_jobs
    reencolados = flow_jobs.recover_expired()
    return {"recovered": int(reencolados),
            "meaning": "leases vencidas re-encoladas según contrato "
                       "(MAX_ATTEMPTS/MAX_LEASE_CYCLES intactos)"}


# ═══════════════════ efecto externo / destructivas ═══════════════════

def op_publish(input: dict) -> dict:
    """Espejo EXACTO de la ruta POST /api/publish (main.py): idempotencia,
    QA gate, job auditable. Sin HTTPException: AdapterError con códigos."""
    pid = _pid(_require(input, "project_id"))
    p = db.get_project(pid)
    if not p or not p.get("video_url"):
        raise AdapterError("NOT_FOUND", "video no disponible")
    if p.get("youtube_id"):
        raise AdapterError(
            "CONFLICT",
            f"ya publicado (idempotencia): youtube_id={p['youtube_id']}")
    meta = dict(p.get("meta") or {})
    qa = meta.get("qa_final") or {}
    if qa.get("worst") == "error":
        raise AdapterError(
            "CONFLICT", "QA del render final con errores — publicación "
            "bloqueada; re-renderiza el proyecto")
    if not youtube_publish.configured():
        raise AdapterError("PREFLIGHT_REFUSED",
                           "publicación YouTube no configurada "
                           "(client_secret.json)", status=BLOCKED)
    jid = db.create_job(pid, kind="publish")
    db.update_job(jid, status="running", step="publishing",
                  message="Subiendo a YouTube…")
    db.update_project(pid, meta={**meta, "publish_state": "PUBLISHING"})
    try:
        vid = youtube_publish.upload(
            p["video_url"], input.get("title") or p["title"],
            description=input.get("description", ""),
            tags=input.get("tags", []),
            private=bool(input.get("private", True)),
            publish_at=input.get("publish_at"),
        )
    except Exception as e:  # noqa: BLE001 — espejo de la ruta
        db.update_job(jid, status="failed", step="failed", error=str(e)[:500],
                      message=f"publish falló: {str(e)[:120]}")
        db.update_project(pid, meta={**(db.get_project(pid).get("meta") or {}),
                                     "publish_state": "FAILED"})
        raise AdapterError("PROVIDER_FAILURE",
                           f"publish falló: {str(e)[:300]}",
                           recoverable=True) from None
    db.update_job(jid, status="done", step="done", message=f"publicado {vid}")
    db.update_project(pid, status="published", youtube_id=vid,
                      meta={**(db.get_project(pid).get("meta") or {}),
                            "publish_state": "PUBLISHED"})
    # G-01 (P3-B): el éxito debe leerse como éxito. `_final_status`
    # resuelve youtube.publish desde external_status; sin esta clave el
    # envelope reportaba FAILED para una publicación real (harness.py).
    # PUBLISHED es estado canónico del contrato (contracts.py §9).
    return {"project_id": pid, "job_id": jid, "youtube_id": vid,
            "url": f"https://youtube.com/watch?v={vid}",
            "external_status": PUBLISHED}


def op_delete(input: dict) -> dict:
    """Espejo EXACTO de DELETE /api/projects/{pid} (C1/M9): id exacto,
    existencia, ruta contenida, cancelación de job activo, purga de
    flow_jobs vía db.delete_project."""
    pid = _pid(_require(input, "project_id"))
    if not db.get_project(pid):
        raise AdapterError("NOT_FOUND", f"no existe el proyecto {pid}")
    job = db.active_job_for_project(pid)
    if job:
        orchestrator.cancel_job(job["id"])
    shutil.rmtree(security.safe_project_output_dir(pid), ignore_errors=True)
    db.delete_project(pid)  # purga también flow_jobs (integridad)
    return {"project_id": pid, "deleted": True}


def op_cleanup(input: dict) -> dict:
    pid = _pid(_require(input, "project_id"))
    if not db.get_project(pid):
        raise AdapterError("NOT_FOUND", f"no existe el proyecto {pid}")
    freed = video_pipeline.cleanup_intermediates(pid)
    return {"project_id": pid, "freed_bytes": int(freed),
            "freed_mb": round(int(freed) / 1e6, 1)}


# ── despacho ────────────────────────────────────────────────────────
# nombre de operación → función adaptadora. Las que necesitan flags
# del contrato van con functools.partial en harness.py (launch/
# submit_production leen constraints).
OPS: dict[str, Callable[[dict], dict]] = {
    "youtube.list_projects": op_list_projects,
    "youtube.project_status": op_project_status,
    "youtube.list_niches": op_list_niches,
    "youtube.list_styles": op_list_styles,
    "youtube.list_avatars": op_list_avatars,
    "youtube.system_status": op_system_status,
    "youtube.flow_status": op_flow_status,
    "youtube.flow_preflight": op_flow_preflight,
    "youtube.production_doctor": op_production_doctor,
    "youtube.validate_production": op_validate_production,
    "youtube.video_qa": op_video_qa,
    "youtube.create": op_create,
    "youtube.cancel": op_cancel,
    "youtube.recover": op_recover,
    "youtube.publish": op_publish,
    "youtube.delete": op_delete,
    "youtube.cleanup": op_cleanup,
}

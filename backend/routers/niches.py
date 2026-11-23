"""
Router modular para el dominio Nichos (/api/niches).
Fase 1 del plan de modularización de backend/main.py.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

import database as db
from services import niches as niches_svc

router = APIRouter(prefix="/api/niches", tags=["niches"])


@router.get("")
async def niches_list():
    """Plantillas de nicho + nº de proyectos que usan cada una."""
    templates = niches_svc.list_templates()
    counts: dict[str, int] = {}
    for p in db.list_projects(limit=500):
        key = (p.get("niche") or "").strip().lower()
        if key:
            counts[key] = counts.get(key, 0) + 1
    out = []
    for t in templates:
        t = dict(t)
        t["projects"] = counts.get((t.get("name") or "").strip().lower(), 0)
        t["folder"] = niches_svc.folder_name(t)
        out.append(t)
    return out


@router.get("/templates")
async def niches_templates():
    return niches_svc.list_templates()


@router.post("/templates")
async def niches_template_save(body: dict):
    try:
        return niches_svc.upsert_template(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/templates/{tid}")
async def niches_template_delete(tid: str):
    if not niches_svc.delete_template(tid):
        raise HTTPException(404, "plantilla no encontrada")
    return {"ok": True}

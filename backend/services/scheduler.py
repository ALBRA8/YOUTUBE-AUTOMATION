"""
YOUTUBE AUTOMATION v2.0 — Modo FÁBRICA (la ventaja que Labsia NO tiene)
Cola + scheduler: N videos/día a horas programadas. Toma ideas de una lista
de espera (o las inventa según el nicho), ejecuta el pipeline completo y
opcionalmente autopublica en YouTube.
"""
import asyncio
import logging
from datetime import datetime

import database as db
from config import (FACTORY_AUTOPUBLISH, FACTORY_NICHE, FACTORY_TIMEZONE,
                    FACTORY_TIMES)
from pipeline import orchestrator

log = logging.getLogger("factory")

_config_key = "factory.config"
_running = False


def default_config() -> dict:
    return {
        "enabled": False,
        "times": FACTORY_TIMES,
        "timezone": FACTORY_TIMEZONE,
        "niche": FACTORY_NICHE,
        "style": "auto",
        "format": "short",
        "autopublish": FACTORY_AUTOPUBLISH,
        "voice": None,
        "tts_provider": None,
    }


def get_config() -> dict:
    cfg = db.kv_get(_config_key)
    if not cfg:
        cfg = default_config()
        db.kv_set(_config_key, cfg)
    return cfg


def save_config(**patch) -> dict:
    cfg = {**get_config(), **patch}
    db.kv_set(_config_key, cfg)
    reschedule()
    return cfg


def get_ideas() -> list[str]:
    return db.kv_get("factory.ideas", [])


def add_idea(idea: str) -> list[str]:
    ideas = get_ideas()
    if idea.strip() and idea not in ideas:
        ideas.append(idea.strip())
        db.kv_set("factory.ideas", ideas)
    return ideas


def pop_idea() -> str | None:
    ideas = get_ideas()
    idea = ideas.pop(0) if ideas else None
    db.kv_set("factory.ideas", ideas)
    return idea


# ── ejecución de un ciclo de fábrica ──────────────────────────────────────
async def run_one_cycle(reason: str = "manual") -> dict:
    cfg = get_config()
    idea = pop_idea()
    source_mode = "idea"
    if not idea:
        idea = await invent_idea(cfg["niche"])
        source_mode = "auto"
    if not idea:
        return {"ok": False, "error": "No se pudo generar una idea"}

    project = db.create_project(
        title=idea[:60], mode="idea", style=cfg["style"], format=cfg["format"],
        voice=cfg.get("voice"), tts_provider=cfg.get("tts_provider"),
        meta={"factory": True, "factory_reason": reason, "idea": idea,
              "autopublish": cfg.get("autopublish", False)},
    )
    log.info("FACTORÍA [%s] → proyecto %s «%s»", reason, project["id"], idea)
    job_id = await orchestrator.start_pipeline(project["id"], autopublish=cfg.get("autopublish", False))
    return {"ok": True, "project_id": project["id"], "job_id": job_id,
            "idea": idea, "source": source_mode}


async def invent_idea(niche: str) -> str | None:
    from services import gemini_client
    if not gemini_client.available():
        bank = [
            f"El caso criminal sin resolver más extraño de {datetime.now():%Y}",
            "3 inventos baratos que hicieron millonario a su creador",
            "La historia del deportista que lo perdió todo y volvió",
            "Qué pasa con tu cuerpo si caminas 30 minutos al día",
            "El error histórico que cambió el mapa del mundo",
        ]
        import random
        return random.choice(bank)
    try:
        out = await gemini_client.generate_json(
            f"Genera UNA idea de video corto viral para YouTube Shorts/TikTok del nicho "
            f"«{niche}». Responde JSON: {{\"idea\": \"título gancho (máx 60 caracteres)\"}}")
        return (out.get("idea") or "").strip() or None
    except Exception as e:  # noqa: BLE001
        log.error("invent_idea: %s", e)
        return None


# ── scheduler ─────────────────────────────────────────────────────────────
_scheduler = None


def _get_scheduler():
    global _scheduler
    if _scheduler is None:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        _scheduler = AsyncIOScheduler()
        for t in get_config()["times"]:
            hh, mm = t.split(":")
            _scheduler.add_job(
                _scheduled_tick, CronTrigger(hour=int(hh), minute=int(mm)),
                id=f"factory-{t}", replace_existing=True)
    return _scheduler


async def _scheduled_tick():
    cfg = get_config()
    if not cfg.get("enabled"):
        return
    try:
        await run_one_cycle(reason="cron")
    except Exception:  # noqa: BLE001
        log.exception("ciclo de fábrica falló")


def reschedule() -> None:
    """Relee configuración (horas) y reprograma los triggers."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.remove_all_jobs()
    sched = _get_scheduler()
    from apscheduler.triggers.cron import CronTrigger
    for t in get_config()["times"]:
        try:
            hh, mm = t.split(":")
            sched.add_job(_scheduled_tick, CronTrigger(hour=int(hh), minute=int(mm)),
                          id=f"factory-{t}", replace_existing=True)
        except ValueError:
            log.warning("hora de fábrica inválida: %s", t)
    if not sched.running:
        sched.configure(timezone=get_config().get("timezone") or FACTORY_TIMEZONE)
        sched.start()
        log.info("Fábrica programada en %s (tz %s)", get_config()["times"],
                 get_config().get("timezone"))


def status() -> dict:
    cfg = get_config()
    next_runs = []
    if _scheduler and _scheduler.running:
        for job in _scheduler.get_jobs():
            nt = job.next_run_time
            if nt:
                next_runs.append(nt.isoformat())
    return {**cfg, "pending_ideas": len(get_ideas()),
            "next_runs": sorted(next_runs),
            "running": _scheduler.running if _scheduler else False}

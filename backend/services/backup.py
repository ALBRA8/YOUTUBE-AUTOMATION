"""
YOUTUBE AUTOMATION v2.0 — Backups de la fábrica (v2.12.2)
Hallazgo #1 de la auditoría externa (pre-venta): la DB era el único punto
de verdad del sistema y moría sin réplica — un disco roto borraba 100% de
los proyectos, configuraciones y tokens.

Qué hace:
- create_backup(): copia CONSISTENTE de la SQLite con la API oficial
  sqlite3.Connection.backup() (segura aunque haya writers activos en WAL).
  [C1 · P0.1] YA NO copia token.json ni .env: eran secretos en CLARO
  (GEMINI_API_KEY, HF_TOKEN, OAuth de YouTube) acumulándose en
  data/backups/ y servibles por endpoints de media antes del candado.
  La restauración de secretos es manual bajo llave (ver abajo).
- list_backups() / restore_backup(name): restaurar ANTES deja un backup de
  seguridad "pre-restore" para que restaurar nunca sea destructivo.
- Rotación: se conservan los últimos BACKUP_KEEP (default 14) de arranque/
  automáticos; los manuales cuentan igual para no llenar el disco.
- Programación: backup al arrancar + cada BACKUP_INTERVAL_H (default 24).

Restaurar a mano (disaster recovery, otro PC):
  1. Copia backend/data/backups/<backup>.db → backend/data/yt_automation.db
     (borra también yt_automation.db-wal y .shm si existen)
  2. Secretos (token YouTube / .env): restaurarlos MANUALMENTE desde el
     gestor de contraseñas — NO viven en data/backups/ (C1).
  3. Arranca con launchers/start.sh / launchers/start.bat — proyectos y videos JSON intactos.
     (los MP4 en data/output/ NO se respaldan: regenerables o respaldo
     externo a criterio del operador)
"""
import asyncio
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import config

log = logging.getLogger("backup")

BACKUP_DIR = config.DATA_DIR / "backups"
KEEP = int(config.__dict__.get("BACKUP_KEEP", 0) or 14)
INTERVAL_H = float(config.__dict__.get("BACKUP_INTERVAL_H", 0) or 24.0)

_NAME_RE = re.compile(r"^yt_automation_\d{8}_\d{6}_(arranque|auto|manual|pre-restore)\.db$")


def _stamp(reason: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"yt_automation_{ts}_{reason}.db"


_LEGACY_SECRET_COPIES = ("token.json.bak", "env.bak")  # [C1 · P0.1] a purgar


def create_backup(reason: str = "manual") -> dict | None:
    """Backup consistente de la DB. Devuelve el registro.

    [C1 · P0.1] ya NO acompaña token.json/.env: eran secretos en claro.
    Además PURGA cualquier copia legada (env.bak/token.json.bak) que quede
    de versiones anteriores — el secreto no vuelve a reposar en claro."""
    if reason not in ("arranque", "auto", "manual", "pre-restore"):
        reason = "manual"
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        name = _stamp(reason)
        dest_path = BACKUP_DIR / name
        src = sqlite3.connect(str(config.DB_PATH), timeout=15)
        dst = sqlite3.connect(str(dest_path))
        with dst:
            src.backup(dst)          # API oficial: consistente con WAL activo
        dst.close()
        src.close()
        # [C1 · P0.1] purga de copias de secretos legadas (una vez por backup;
        # idempotente y silenciosa si ya no existen)
        for legacy in _LEGACY_SECRET_COPIES:
            try:
                (BACKUP_DIR / legacy).unlink(missing_ok=True)
            except OSError as e:
                log.warning("no se pudo purgar %s: %s", legacy, str(e)[:80])
        _rotate()
        return {"name": name, "size": dest_path.stat().st_size,
                "reason": reason, "ts": time.time()}
    except Exception as e:  # noqa: BLE001
        log.error("backup falló (%s): %s", reason, str(e)[:160])
        return None


def list_backups() -> list[dict]:
    """Backups disponibles, el más nuevo primero."""
    if not BACKUP_DIR.exists():
        return []
    out = []
    for f in sorted(BACKUP_DIR.glob("yt_automation_*.db"), reverse=True):
        m = _NAME_RE.match(f.name)
        out.append({
            "name": f.name,
            "size": f.stat().st_size,
            "reason": m.group(1) if m else "manual",
            "ts": f.stat().st_mtime,
        })
    return out


def _rotate() -> int:
    """Deja solo los últimos KEEP backups. Devuelve cuántos borró."""
    bks = list_backups()
    removed = 0
    for old in bks[KEEP:]:
        try:
            (BACKUP_DIR / old["name"]).unlink()
            removed += 1
        except Exception:  # noqa: BLE001
            pass
    return removed


def restore_backup(name: str) -> dict:
    """Restaura un backup. Primero crea uno de seguridad 'pre-restore'
    para que restaurar NUNCA sea destructivo.
    v2.12.2.1: usa la API sqlite3.backup() EN REVERSA (backup→vivo) en vez
    de copiar el archivo: copiar por encima del .db en caliente invalida los
    descriptores del servidor corriendo (disk I/O error). La API escribe las
    páginas con journaling correcto y es segura en vivo."""
    if not _NAME_RE.match(name or ""):
        raise ValueError("nombre de backup inválido")
    src = BACKUP_DIR / name
    if not src.exists():
        raise FileNotFoundError("backup no existe: " + name)
    safety = create_backup("pre-restore")
    src_con = sqlite3.connect(str(src), timeout=15)
    dst_con = sqlite3.connect(str(config.DB_PATH), timeout=15)
    try:
        with dst_con:
            src_con.backup(dst_con)   # sobrescribe la DB viva de forma segura
    finally:
        dst_con.close()
        src_con.close()
    return {"restored": name, "safety": safety["name"] if safety else None}


async def _auto_loop() -> None:
    """Backup automático cada INTERVAL_H horas (tarea en segundo plano).
    El primer disparo es al INTERVALO (el de arranque ya cubrió el boot).
    [M · P2.6] la SQLite se copia FUERA del event loop (to_thread): antes
    bloqueaba health/dashboard/jobs durante el volcado."""
    await asyncio.sleep(INTERVAL_H * 3600)
    while True:
        try:
            r = await asyncio.to_thread(create_backup, "auto")
            if r:
                log.info("backup automático: %s (%.1f KB)",
                         r["name"], r["size"] / 1024)
        except Exception as e:  # noqa: BLE001
            log.warning("backup automático falló: %s", str(e)[:120])
        await asyncio.sleep(INTERVAL_H * 3600)


_auto_task: asyncio.Task | None = None


def start_scheduler() -> asyncio.Task | None:
    """[M · P2.6] guarda la REFERENCIA de la tarea (el GC podía recolectarla:
    el backup automático moría en silencio) y devuelve el handle para
    cancelación limpia en shutdown. Idempotente: no duplica tareas."""
    global _auto_task
    if _auto_task is not None and not _auto_task.done():
        return _auto_task
    _auto_task = asyncio.get_event_loop().create_task(_auto_loop())
    return _auto_task

"""
YOUTUBE AUTOMATION v2.0 — Backups de la fábrica (v2.12.2)
Hallazgo #1 de la auditoría externa (pre-venta): la DB era el único punto
de verdad del sistema y moría sin réplica — un disco roto borraba 100% de
los proyectos, configuraciones y tokens.

Qué hace:
- create_backup(): copia CONSISTENTE de la SQLite con la API oficial
  sqlite3.Connection.backup() (segura aunque haya writers activos en WAL).
  Añade token.json de YouTube (re-vincular canales es un dolor) y .env
  (protege contra un guardado corrupto desde Ajustes). Todo local.
- list_backups() / restore_backup(name): restaurar ANTES deja un backup de
  seguridad "pre-restore" para que restaurar nunca sea destructivo.
- Rotación: se conservan los últimos BACKUP_KEEP (default 14) de arranque/
  automáticos; los manuales cuentan igual para no llenar el disco.
- Programación: backup al arrancar + cada BACKUP_INTERVAL_H (default 24).

Restaurar a mano (disaster recovery, otro PC):
  1. Copia backend/data/backups/<backup>.db → backend/data/yt_automation.db
     (borra también yt_automation.db-wal y .shm si existen)
  2. Copia token.json.bak → backend/data/token.json (si había canal)
  3. Copia env.bak → backend/.env
  4. Arranca con start.sh / start.bat — proyectos y videos JSON intactos.
     (los MP4 en data/output/ NO se respaldan: regenerables o respaldo
     externo a criterio del operador)
"""
import asyncio
import logging
import re
import shutil
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


def create_backup(reason: str = "manual") -> dict | None:
    """Backup consistente de la DB + token.json + .env. Devuelve el registro."""
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
        # compañeros de viaje (si existen)
        for src_f, dst_name in ((Path(config.YT_TOKEN_FILE), "token.json.bak"),
                                (config.ENV_PATH, "env.bak")):
            try:
                if Path(src_f).exists():
                    shutil.copy2(src_f, BACKUP_DIR / dst_name)
            except Exception as e:  # noqa: BLE001
                log.warning("backup de %s falló: %s", dst_name, str(e)[:80])
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
    El primer disparo es al INTERVALO (el de arranque ya cubrió el boot)."""
    await asyncio.sleep(INTERVAL_H * 3600)
    while True:
        try:
            r = create_backup("auto")
            if r:
                log.info("backup automático: %s (%.1f KB)",
                         r["name"], r["size"] / 1024)
        except Exception as e:  # noqa: BLE001
            log.warning("backup automático falló: %s", str(e)[:120])
        await asyncio.sleep(INTERVAL_H * 3600)


def start_scheduler() -> None:
    asyncio.get_event_loop().create_task(_auto_loop())

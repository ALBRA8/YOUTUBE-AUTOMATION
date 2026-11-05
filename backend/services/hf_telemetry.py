"""INT-089 · Telemetría por llamada HF (ZeroGPU) — sidecar por proyecto.

Cada intento real contra un Space de Hugging Face (lip-sync audio-driven
INT-072 y video-to-video INT-075 con LatentSync/Wav2Lip) deja UN registro en
``hf_telemetry.json`` dentro de la carpeta del proyecto (workspace canónico
INT-086 si existe, almacén legacy ``output/<pid>/`` como respaldo) y, como
respaldo global best-effort, en ``<DATA_DIR>/hf_telemetry.json``.

Registro:
    {
      "timestamp": "2026-11-05T09:12:33-05:00",
      "epoch": 1762345953.12,
      "motor": "v2v" | "lipsync_hf",
      "space": "ByteDance/LatentSync",
      "exito": false,
      "cuota_agotada": true,
      "segundos_solicitados": 60,
      "segundos_restantes": 42,
      "error": "… You have exceeded your GPU quota (60s requested / 42s left)…",
      "timeout_s": 300,
      "duracion_s": 8.41
    }

Reglas de oro:
  · La telemetría JAMÁS rompe el pipeline: cualquier error de escritura se
    traga (best-effort) y las funciones devuelven el registro igualmente.
  · Nunca se registra HF_TOKEN ni contenido de archivos — solo metadatos de
    la llamada y el mensaje de error recortado.
  · El sidecar guarda como máximo _MAX_RECORDS entradas (recorte FIFO).

`GET /api/projects/{pid}/hf-status` (main.py) devuelve el último registro
para que la UI pueda anticipar si el lip-sync va a chocar con la cuota.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("uvicorn.error")

_LOCK = threading.RLock()
_MAX_RECORDS = 50

# Mensaje real de ZeroGPU (gradio_client): «You have exceeded your GPU quota
# (60s requested / 42s left. Try again in 18s)» — variantes con decimales.
_RE_REQ = re.compile(r"(\d+(?:[.,]\d+)?)\s*s(?:ec(?:ond)?)?s?\s+requested", re.I)
_RE_LEFT = re.compile(r"(\d+(?:[.,]\d+)?)\s*s(?:ec(?:ond)?)?s?\s+left", re.I)
_RE_QUOTA = re.compile(r"gpu\s+quota", re.I)


def parse_cuota(msg: str) -> tuple[int | None, int | None]:
    """Extrae (segundos_solicitados, segundos_restantes) del mensaje de cuota
    de ZeroGPU. Devuelve (None, None) si el mensaje no habla de cuota."""
    msg = str(msg or "")
    m_req, m_left = _RE_REQ.search(msg), _RE_LEFT.search(msg)
    req = int(float(m_req.group(1).replace(",", "."))) if m_req else None
    left = int(float(m_left.group(1).replace(",", "."))) if m_left else None
    return req, left


def sidecar_path(project_dir: Path | str) -> Path:
    return Path(project_dir) / "hf_telemetry.json"


def _append_sidecar(path: Path, entry: dict) -> None:
    """Añade la entrada al sidecar con recorte FIFO (thread-safe)."""
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        data: list = []
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    data = loaded
            except Exception:  # sidecar corrupto → se reescribe desde cero
                data = []
        data.append(entry)
        path.write_text(
            json.dumps(data[-_MAX_RECORDS:], ensure_ascii=False, indent=2),
            encoding="utf-8")


def record(
    motor: str,
    space: str,
    exito: bool,
    error: str = "",
    project_dir: Path | str | None = None,
    timeout_s: float | None = None,
    duracion_s: float | None = None,
) -> dict[str, Any]:
    """Registra UNA llamada HF (éxito o fallo) y devuelve el entry escrito.

    Escritura best-effort: sidecar del proyecto (si hay contexto) + respaldo
    global en DATA_DIR. Nunca lanza — la telemetría no puede romper el render.
    """
    req, left = parse_cuota(error)
    entry: dict[str, Any] = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "epoch": round(time.time(), 3),
        "motor": str(motor or ""),
        "space": str(space or ""),
        "exito": bool(exito),
        "cuota_agotada": bool(req is not None or left is not None
                              or _RE_QUOTA.search(str(error or ""))),
        "segundos_solicitados": req,
        "segundos_restantes": left,
        "error": str(error or "")[:400],
        "timeout_s": float(timeout_s) if timeout_s is not None else None,
        "duracion_s": round(float(duracion_s), 2) if duracion_s is not None else None,
    }
    targets: list[Path] = []
    if project_dir:
        targets.append(sidecar_path(project_dir))
    try:
        import config as _c
        targets.append(Path(_c.DATA_DIR) / "hf_telemetry.json")
    except Exception:
        pass
    for t in targets:
        try:
            _append_sidecar(t, entry)
        except Exception as ex:  # best-effort: jamás romper el pipeline
            log.debug("[hf_telemetry] no se pudo escribir %s: %s", t, ex)
    return entry


def last_record(project_dir: Path | str) -> dict[str, Any] | None:
    """Último registro del sidecar del proyecto (None si no hay datos)."""
    try:
        p = sidecar_path(project_dir)
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            return data[-1]
    except Exception as ex:  # sidecar ilegible → sin telemetría
        log.debug("[hf_telemetry] sidecar ilegible: %s", ex)
    return None


def history(project_dir: Path | str, n: int = 10) -> list[dict[str, Any]]:
    """Últimos ``n`` registros del sidecar (más nuevos al final)."""
    try:
        p = sidecar_path(project_dir)
        if not p.is_file():
            return []
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data[-max(int(n), 0):]
    except Exception:
        pass
    return []

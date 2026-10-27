"""
YOUTUBE AUTOMATION v2.38 — NotebookLM Studio Bridge (INT-069)
Puente del backend hacia el panel Studio de NotebookLM vía el servidor MCP
`notebooklm-mcp` (paquete notebooklm-py, PIN v0.8.5): crea/prepara un
notebook, dispara un Audio Overview con el guion y baja el audio a exports.

FLUJO (todas las tools verificadas en el clon upstream v0.8.5,
/home/z/my-project/external/notebooklm-py, tag v0.8.5 — SOLO LECTURA):

  1. garantizar notebook  → tool `notebook_create(notebook: str = título)`
     (tools/notebooks.py:62) si no se dio notebook_id; respuesta aplanada
     {"status": "created", "notebook_id": ...} (#1540).
  2. añadir fuente de texto → tool `source_add(notebook, source_type="text",
     text, title, wait, timeout, interval)` (tools/sources.py:617);
     source_type Literal["url","text","file","drive","youtube"].
  3. generar Audio Overview → tool `studio_generate(notebook,
     artifact_type="audio", ...)` (tools/studio.py:223). No bloquea: devuelve
     task_id; artifact_type "audio" = podcast-style overview (audio_format
     deep-dive|brief|critique|debate).
  4. poll → tool `studio_status(notebook, task_id)` (tools/studio.py:407);
     stateless; devuelve status/url/error/is_complete/media_ready.
  5. descargar → tool `studio_download(notebook, artifact_type="audio",
     path=...)` (tools/studio.py:422; registry "audio" en downloads.py:158).
     ⚠ v0.8.5: el Audio Overview NO es MP3 — es AAC en contenedor MP4
     (#2034, downloads.py:156-162) → ficheros .m4a (se sirven igual).

NOTA DE COMPAT (v0.8.5): las tools nombran el parámetro `notebook` y FastMCP
rechaza kwargs desconocidos; mcp_manager.execute() espeja la clave legacy
`notebook_id` del §3 → `notebook` según el inputSchema real
(mcp_manager._mirror_notebook_arg). Aquí solo se envía `notebook_id`.

TODO el I/O MCP pasa por mcp_manager.execute (subprocess JSON-RPC stdio,
protocolo 2024-11-05). FAIL-CLOSED: si el MCP no está disponible se lanza
NLMStudioError con código estable (nunca se degrada a silencio).

Hermeticidad: toda la salida al MCP pasa por _exec() (parcheable en tests
con monkeypatch; cero red, cero subprocess reales). Los jobs en curso viven
en memoria (_JOBS/_TASKS): PoC de un solo proceso, como el resto del repo.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from services import mcp_manager as mcpm

log = logging.getLogger("nlm_studio")

# ── tools MCP usadas (nombres EXACTOS verificados en v0.8.5) ─────────────
TOOL_NOTEBOOK_CREATE = "notebook_create"    # tools/notebooks.py:62
TOOL_SOURCE_ADD = "source_add"              # tools/sources.py:617
TOOL_STUDIO_GENERATE = "studio_generate"    # tools/studio.py:223
TOOL_STUDIO_STATUS = "studio_status"        # tools/studio.py:407
TOOL_STUDIO_DOWNLOAD = "studio_download"    # tools/studio.py:422

# Patrón canónico de notebookId (el MISMO que valida mcp_manager.execute).
_ID_RE = mcpm._NOTEBOOK_ID_RE

# Extensiones válidas del audio descargado (v0.8.5 baja AAC/.m4a, #2034;
# se acepta .mp3 por si una versión futura restaura MP3).
_AUDIO_EXTS = (".m4a", ".mp3")

# Timeout fijo de la tool de descarga (el fichero se escribe localmente).
_DOWNLOAD_TIMEOUT = 180.0
_SOURCE_TIMEOUT = 180.0
_GENERATE_TIMEOUT = 120.0
_STATUS_TIMEOUT = 60.0


class NLMStudioError(Exception):
    """Error operacional del Studio Bridge con código estable para la UI."""

    def __init__(self, msg: str, code: str = "NLM_STUDIO_ERROR"):
        super().__init__(msg)
        self.code = code


# ──────────────────────────────── configuración (leída EN CALIENTE) ──
def enabled() -> bool:
    """Interruptor NLM_STUDIO_ENABLED (default "1"; "0" desactiva)."""
    return str(getattr(config, "NLM_STUDIO_ENABLED", "1") or "1").strip().lower() in (
        "1", "true", "yes", "on")


def _require_enabled() -> None:
    if not enabled():
        raise NLMStudioError(
            "NotebookLM Studio Bridge deshabilitado (NLM_STUDIO_ENABLED=0)",
            "STUDIO_DISABLED")


def export_root() -> Path:
    """Raíz de exports: NLM_STUDIO_EXPORT_DIR o DATA_DIR/exports/nlm_studio."""
    custom = str(getattr(config, "NLM_STUDIO_EXPORT_DIR", "") or "").strip()
    if custom:
        return Path(custom).resolve()
    return Path(config.DATA_DIR) / "exports" / "nlm_studio"


def _poll_timeout() -> float:
    try:
        return max(5.0, float(getattr(config, "NLM_STUDIO_POLL_TIMEOUT", 900)))
    except (TypeError, ValueError):
        return 900.0


# ──────────────────────────────── transporte MCP (parcheable) ──
async def _exec(tool: str, arguments: dict,
                timeout: float | None = None) -> dict:
    """Punto ÚNICO de salida al MCP de NotebookLM (parcheable en tests).
    Devuelve el dict de mcp_manager.execute: {"ok", "service", "tool",
    "text", "elapsed_s", ...}. Propaga MCPManagerError (fail-closed)."""
    return await mcpm.manager.execute("notebooklm", tool, arguments,
                                      timeout=timeout)


def _parse_json(text: str) -> dict:
    """Parsea la respuesta JSON de una tool MCP (tolerante: {} si no es JSON)."""
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# ──────────────────────────────── pasos del flujo ──
async def ensure_notebook(notebook_id: str | None = None,
                          title: str | None = None) -> dict:
    """Devuelve {"notebook_id", "created", "title"}. Con notebook_id válido lo
    reutiliza (created=False); si no, crea «ALBRA Studio <fecha>» vía
    notebook_create. Fail-closed ante MCP caído o respuesta ilegible."""
    _require_enabled()
    nb = (notebook_id or "").strip()
    if nb:
        if not _ID_RE.match(nb):
            raise NLMStudioError(
                f"notebook_id inválido: '{nb[:24]}' (patrón canónico de NotebookLM)",
                "INVALID_NOTEBOOK_ID")
        return {"notebook_id": nb, "created": False, "title": (title or "").strip()}
    t = (title or "").strip() or f"ALBRA Studio {datetime.now():%Y-%m-%d}"
    res = await _exec(TOOL_NOTEBOOK_CREATE, {"title": t}, timeout=_GENERATE_TIMEOUT)
    data = _parse_json(res.get("text") or "")
    nb = str(data.get("notebook_id") or data.get("id") or "").strip()
    if not nb:
        raise NLMStudioError(
            "notebook_create no devolvió notebook_id legible: "
            f"{(res.get('text') or '')[:160]}", "NOTEBOOK_CREATE_MALFORMED")
    log.info("[nlm-studio] notebook creado: %s («%s»)", nb, t)
    return {"notebook_id": nb, "created": True, "title": t}


async def add_text_source(notebook_id: str, text: str,
                          title: str | None = None) -> dict:
    """Añade el guion/contenido como fuente de TEXTO (source_add con
    source_type="text" y wait=True para que el backend la procese antes de
    generar). Devuelve {"source_id", "data"}."""
    _require_enabled()
    if not (text or "").strip():
        raise NLMStudioError("el texto de la fuente está vacío", "TEXT_REQUIRED")
    args = {"notebook_id": notebook_id, "source_type": "text",
            "text": text,
            "title": (title or "").strip() or "Guion ALBRA",
            "wait": True, "timeout": 120.0, "interval": 2.0}
    res = await _exec(TOOL_SOURCE_ADD, args, timeout=_SOURCE_TIMEOUT)
    data = _parse_json(res.get("text") or "")
    src = data.get("source") if isinstance(data.get("source"), dict) else {}
    sid = str(data.get("source_id") or src.get("id") or data.get("id") or "").strip()
    log.info("[nlm-studio] fuente añadida a %s (source_id=%s)", notebook_id, sid or "?")
    return {"source_id": sid, "data": data}


async def generate_audio_overview(notebook_id: str,
                                  instructions: str | None = None) -> str:
    """Dispara el Audio Overview (studio_generate, artifact_type="audio") y
    devuelve el task_id para el poll. No bloquea (el genera tarda minutos)."""
    _require_enabled()
    args: dict[str, Any] = {"notebook_id": notebook_id, "artifact_type": "audio"}
    if (instructions or "").strip():
        args["instructions"] = instructions.strip()
    res = await _exec(TOOL_STUDIO_GENERATE, args, timeout=_GENERATE_TIMEOUT)
    data = _parse_json(res.get("text") or "")
    task_id = str(data.get("task_id") or "").strip()
    if not task_id:
        raise NLMStudioError(
            "studio_generate no devolvió task_id: "
            f"{(res.get('text') or '')[:160]}", "NO_TASK_ID")
    log.info("[nlm-studio] Audio Overview disparado en %s (task_id=%s)",
             notebook_id, task_id)
    return task_id


async def poll_status(notebook_id: str, task_id: str,
                      timeout_s: float | None = None,
                      interval: float = 10.0) -> dict:
    """Poll stateless de studio_status hasta is_complete/media_ready.
    Timeout → NLMStudioError(GENERATION_TIMEOUT); error del backend de
    NotebookLM → GENERATION_FAILED. Devuelve el último status dict."""
    _require_enabled()
    deadline = time.monotonic() + (float(timeout_s) if timeout_s is not None
                                   else _poll_timeout())
    gap = max(0.5, float(interval))
    last: dict = {}
    while True:
        res = await _exec(TOOL_STUDIO_STATUS,
                          {"notebook_id": notebook_id, "task_id": task_id},
                          timeout=_STATUS_TIMEOUT)
        last = _parse_json(res.get("text") or "")
        if last.get("error"):
            raise NLMStudioError(
                f"la generación falló en NotebookLM: {str(last.get('error'))[:200]}",
                "GENERATION_FAILED")
        if last.get("is_complete") or last.get("media_ready"):
            return last
        if time.monotonic() >= deadline:
            raise NLMStudioError(
                f"timeout esperando el Audio Overview (task_id={task_id})",
                "GENERATION_TIMEOUT")
        await asyncio.sleep(gap)


async def download_audio(notebook_id: str, dest_path: Path | None = None) -> Path:
    """Baja el ÚLTIMO artifact de audio del notebook a exports con
    studio_download(artifact_type="audio", path=...) → <dest>/<ts>.m4a."""
    _require_enabled()
    if not _ID_RE.match(notebook_id or ""):
        raise NLMStudioError(
            f"notebook_id inválido: '{(notebook_id or '')[:24]}'",
            "INVALID_NOTEBOOK_ID")
    dest = Path(dest_path) if dest_path else (
        export_root() / notebook_id /
        f"albra_studio_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.m4a")
    dest.parent.mkdir(parents=True, exist_ok=True)
    await _exec(TOOL_STUDIO_DOWNLOAD,
                {"notebook_id": notebook_id, "artifact_type": "audio",
                 "path": str(dest)}, timeout=_DOWNLOAD_TIMEOUT)
    if not dest.is_file():
        raise NLMStudioError(
            f"studio_download no escribió el fichero en {dest}",
            "DOWNLOAD_EMPTY")
    log.info("[nlm-studio] audio descargado: %s (%.1f KB)",
             dest, dest.stat().st_size / 1024)
    return dest


# ──────────────────────────────── orquestación ──
async def run_audio_overview(notebook_id: str | None = None,
                             title: str | None = None,
                             text: str | None = None,
                             poll_interval: float = 10.0) -> dict:
    """Flujo COMPLETO síncrono (bloquea hasta tener el fichero):
    garantizar notebook → fuente de texto → studio_generate → poll → download.
    Devuelve {"notebook_id", "task_id", "file", "status", "created"}.
    FAIL-CLOSED: cualquier MCPManagerError se envuelve en NLMStudioError con
    el MISMO código estable (única superficie de error para la UI)."""
    try:
        ens = await ensure_notebook(notebook_id=notebook_id, title=title)
        nb = ens["notebook_id"]
        await add_text_source(nb, text or "")
        task_id = await generate_audio_overview(nb)
        st = await poll_status(nb, task_id, interval=poll_interval)
        path = await download_audio(nb)
    except NLMStudioError:
        raise
    except mcpm.MCPManagerError as e:
        raise NLMStudioError(str(e), code=e.code) from e
    return {"notebook_id": nb, "created": ens.get("created", False),
            "task_id": task_id, "file": str(path), "status": st}


# ── registro de jobs en memoria (PoC mono-proceso, patrón del repo) ──
_JOBS: dict[str, dict] = {}      # notebook_id → job view (serializable)
_TASKS: dict[str, asyncio.Task] = {}  # notebook_id → asyncio.Task viva

_JOB_KEYS = ("notebook_id", "state", "created", "notebook_title", "task_id",
             "file", "error", "created_at", "updated_at")


def _job_view(job: dict) -> dict:
    return {k: job.get(k, "" if k != "created" else False) for k in _JOB_KEYS}


async def _run_job(job: dict, poll_interval: float) -> None:
    nb = job["notebook_id"]
    try:
        res = await run_audio_overview(notebook_id=nb, title=job.get("notebook_title"),
                                       text=job.get("text"),
                                       poll_interval=poll_interval)
        job.update({"state": "ready", "task_id": res["task_id"],
                    "file": res["file"], "error": "",
                    "updated_at": time.time()})
        log.info("[nlm-studio] job listo: %s → %s", nb, res["file"])
    except (NLMStudioError, mcpm.MCPManagerError) as e:
        job.update({"state": "error", "error": f"[{getattr(e, 'code', 'ERROR')}] {e}",
                    "updated_at": time.time()})
        log.warning("[nlm-studio] job falló: %s — %s", nb, e)
    except Exception as e:  # noqa: BLE001 — el job NUNCA cuelga en silencio
        job.update({"state": "error", "error": str(e)[:300],
                    "updated_at": time.time()})
        log.warning("[nlm-studio] job crash: %s — %s", nb, e)
    finally:
        _TASKS.pop(nb, None)


async def start_audio_overview(notebook_id: str | None = None,
                               title: str | None = None,
                               text: str | None = None) -> dict:
    """Versión no bloqueante para REST: garantiza notebook + añade la fuente
    (rápido, síncrono) y lanza generate+poll+download como tarea de fondo.
    Devuelve el job con state="generating" (HTTP 202). Si ya hay una
    generación en curso para el notebook → GENERATION_IN_PROGRESS."""
    _require_enabled()
    body_text = (text or "").strip()
    if not body_text:
        raise NLMStudioError("campo 'text' requerido (guion/contenido)", "TEXT_REQUIRED")
    ens = await ensure_notebook(notebook_id=notebook_id, title=title)
    nb = ens["notebook_id"]
    prev = _JOBS.get(nb)
    if prev and prev.get("state") == "generating":
        raise NLMStudioError(
            f"ya hay una generación en curso para {nb}", "GENERATION_IN_PROGRESS")
    job = {"notebook_id": nb, "state": "generating",
           "created": bool(ens.get("created")),
           "notebook_title": ens.get("title") or "",
           "task_id": "", "file": "", "error": "",
           "created_at": time.time(), "updated_at": time.time(),
           "text": body_text}
    _JOBS[nb] = job
    _TASKS[nb] = asyncio.create_task(
        _run_job(job, poll_interval=max(0.5, _poll_timeout() / 90.0)))
    log.info("[nlm-studio] job arrancado: %s (creado=%s)", nb, job["created"])
    return _job_view(job)


def job_status(notebook_id: str) -> dict:
    """Estado del job del notebook ("idle" si nunca se lanzó). NUNCA lanza."""
    nb = (notebook_id or "").strip()
    job = _JOBS.get(nb)
    return _job_view(job) if job else {"notebook_id": nb, "state": "idle"}


def latest_audio(notebook_id: str) -> Path:
    """MP3/M4A más reciente del notebook en exports (para el FileResponse).
    Fail-closed: INVALID_NOTEBOOK_ID / NO_AUDIO con código estable."""
    nb = (notebook_id or "").strip()
    if not _ID_RE.match(nb):
        raise NLMStudioError(
            f"notebook_id inválido: '{nb[:24]}'", "INVALID_NOTEBOOK_ID")
    d = export_root() / nb
    if not d.is_dir():
        raise NLMStudioError(f"no hay audios exportados para {nb}", "NO_AUDIO")
    cands = [p for p in d.iterdir()
             if p.is_file() and p.suffix.lower() in _AUDIO_EXTS]
    if not cands:
        raise NLMStudioError(f"no hay audios exportados para {nb}", "NO_AUDIO")
    return max(cands, key=lambda p: p.stat().st_mtime)

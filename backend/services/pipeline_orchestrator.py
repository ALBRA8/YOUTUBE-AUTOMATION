"""
YOUTUBE AUTOMATION v2.22 — Pipeline Orchestrator (INT-023)
NotebookLM → Agent (guion) → Google Flow, coordinado con mcp_manager (INT-022).

REGLA DE ORO del mandato: aquí NO se reescribe NI se degrada la generación
de prompts/blueprints. El guion lo genera el mismo motor de SIEMPRE
(pipeline/script_gen.py — from_idea → build_result, con su sanitización
anti Safety-Policy intacta); este módulo solo:
  1) extrae el contexto de NotebookLM (Stage 1),
  2) lo ALIMENTA al generador existente como bíblia de investigación (Stage 2),
  3) despacha las escenas a Flow vía MCP con consistencia de personaje
     (mismo asset de referencia @{personaje} en todas las escenas) (Stage 3).

Pre-flight gatekeeper (§2 del mandato): si NotebookLM o Google Flow no están
Connected & Authenticated se aborta ANTES de gastar tokens del LLM.

Recuperación (§2): una escena que falla en Stage 3 NO tumba la corrida —
se registra scene_id, los assets previos quedan intactos y /api/pipeline/
retry-scenes re-despacha SOLO las escenas fallidas (sin repetir Stage 1/2).

Estado persistente: cada corrida vive en
  config.DATA_DIR/pipeline_runs/<run_id>/state.json (+ context.md,
  blueprint.json y assets Flow). El retry funciona tras reiniciar el backend.

Hermeticidad de baterías: manager y runs_dir se inyectan por constructor y
script_gen se referencia como módulo (parcheable) — cero red real en tests.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Callable

import config
from pipeline import script_gen
from services import asset_harvester as harv
from services import mcp_manager as mcpm
from services import video_assembler as vasm

log = logging.getLogger("pipeline_orchestrator")

# Etapas canónicas (la UI las pinta en orden)
ST_QUEUED = "queued"
ST_PREFLIGHT = "preflight"
ST_STAGE1 = "stage1_context"
ST_STAGE2 = "stage2_blueprint"
ST_STAGE3 = "stage3_dispatch"
ST_STAGE4 = "stage4_render"
ST_DONE = "done"
ST_ERROR = "error"

_STAGES_ACTIVE = {ST_QUEUED, ST_PREFLIGHT, ST_STAGE1, ST_STAGE2, ST_STAGE3,
                  ST_STAGE4}

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{6,80}$")
_NICHO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
MAX_NICHO_CONTEXT_BYTES = 64 * 1024  # 64 KB

# BH1: rutas de imagen/video que Flow devuelve en su texto — ahora CON
# espacios, tildes y unidad de Windows (p. ej.
# "D:\PROYECTOS\YOUTUBE AUTOMATION\…\ancla.jpg"). El patrón antiguo
# ([A-Za-z]:\\[^\s]+|/[^\s]+) cortaba en el primer espacio y perdía la ruta.
_MEDIA_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov")
_WIN_DRIVE_RE = re.compile(r"[A-Za-z]:[/\\]")
_UNIX_PATH_RE = re.compile(r"(?:^|[\s\"'=(])(/.+)$")

# ── BG2: puerta DECLARADA de blueprint externo (nunca oculta) ────────────
# POST /api/pipeline/run acepta "blueprint" {label, title, scenes}. La
# validación es EXTRICTA y cualquier caso inválido → INVALID_BLUEPRINT (sin
# reparación silenciosa ni truncado). Con blueprint válido la etapa 2 NO
# llama a Gemini: engine "external:<label>", gemini_model "" y
# blueprint_source "external" visible en /api/pipeline/status.
EXTERNAL_BLUEPRINT_MAX_BYTES = 20 * 1024          # payload total <=20 KB
_EXTERNAL_LABEL_RE = re.compile(r"[A-Za-z0-9 _.\-]{1,30}")
_EXTERNAL_BP_KEYS = {"label", "title", "scenes"}
_EXTERNAL_SCENE_KEYS = {"title", "narration", "image_prompt"}

_STEPS = (
    (ST_PREFLIGHT, "[0/3] Pre-flight: verificando sesión de ambos MCP…"),
    (ST_STAGE1, "[1/3] Reading NotebookLM…"),
    (ST_STAGE2, "[2/3] Generating Blueprint…"),
    (ST_STAGE3, "[3/3] Dispatching Scenes to Flow…"),
    (ST_STAGE4, "[4/4] Assembling Final Video (FFmpeg)…"),
)


class PipelineError(Exception):
    """Error operacional del pipeline con código estable para la UI."""

    def __init__(self, msg: str, code: str = "PIPELINE_ERROR"):
        super().__init__(msg)
        self.code = code


def _cfg(name: str, default: Any) -> Any:
    val = getattr(config, name, None)
    if val is not None and val != "":
        return val
    env_val = os.environ.get(name)
    if env_val is not None:
        return env_val
    return default


def _flow_warm_timeout() -> float:
    """BK1: timeout (segundos) del calentamiento Stage 3 de flow_list_assets.

    El connectOverCDP EN FRÍO tarda 32-120 s (BJ1) y el MCP server usa su
    PROPIO timeout FLOW_CDP_CONNECT_TIMEOUT_MS (120000 ms por defecto — misma
    constante y mismo default que tools/GoogleFlowMCP/src/chrome.js). El
    calentamiento debe dar margen a ESE connect más su propio margen de
    listado: (ms / 1000) + 30 → 150 s por defecto. Un valor no numérico,
    vacío, 0, negativo o NaN cae al default (misma política que el JS:
    Number.isFinite(n) && n > 0).
    """
    try:
        ms = float(_cfg("FLOW_CDP_CONNECT_TIMEOUT_MS", 120000))
    except (TypeError, ValueError):
        ms = 120000.0
    if not (ms > 0):  # cubre 0, negativos y NaN
        ms = 120000.0
    return ms / 1000.0 + 30.0


def _path_from_line(line: str) -> str:
    r"""BH1: extrae la ruta completa de imagen/video que contiene UNA línea
    de la respuesta de Flow. Acepta letra de unidad de Windows (X:\ o X:/)
    o barra inicial POSIX, CON espacios y tildes. Devuelve "" si la línea no
    contiene una ruta válida."""
    s = (line or "").strip().lstrip("- ").strip().strip('"').strip("'").strip()
    if not s or not s.lower().endswith(_MEDIA_EXTS):
        return ""
    cand = ""
    drives = list(_WIN_DRIVE_RE.finditer(s))
    if drives:
        cand = s[drives[-1].start():]          # desde la última unidad al final
    else:
        m = _UNIX_PATH_RE.search(s)
        if m:
            cand = m.group(1)
    cand = cand.strip().strip('"').strip().strip("'").strip()
    if len(cand) < 6:                           # mínimo: /a.png | X:\x.png
        return ""
    if cand.lower().startswith("//") or "://" in cand:
        return ""                               # URL, no ruta de disco
    if any(ch in cand for ch in '<>|'):
        return ""                               # inválidos en ruta
    return cand if cand.lower().endswith(_MEDIA_EXTS) else ""


def _last_path(text: str) -> str:
    """Extrae la última ruta de archivo de la respuesta textual de Flow.
    Los servidores GoogleFlowMCP responden con '…:\\n<ruta local>'.
    BH1: toma la ÚLTIMA línea no vacía que contenga una ruta completa
    terminada en extensión de imagen o video (.png .jpg .jpeg .webp .mp4
    .mov), con unidad de Windows o barra inicial, admitiendo espacios y
    tildes (antes se cortaba en el primer espacio)."""
    for line in reversed((text or "").strip().splitlines()):
        if not line.strip():
            continue
        p = _path_from_line(line)
        if p:
            return p
    return ""


def _recent_media_in_dir(out_dir: str | Path, t0: float) -> str:
    """BH1 respaldo: si el texto de Flow no trae ruta, usa el archivo MÁS
    RECIENTE de outDir con extensión de imagen/video válida y fecha posterior
    al inicio de la llamada (t0, con tolerancia de 2 s por granularidad del
    FS). "" si no hay nada que cumpla — el caller falla con su mensaje de
    siempre; jamás inventa una ruta."""
    try:
        rd = Path(out_dir)
        mejor, mejor_m = "", -1.0
        for p in rd.iterdir():
            if not p.name.lower().endswith(_MEDIA_EXTS):
                continue
            try:
                if not p.is_file():
                    continue
                m = p.stat().st_mtime
            except OSError:
                continue
            if m >= t0 - 2.0 and m >= mejor_m:
                mejor, mejor_m = str(p), m
        return mejor
    except OSError:
        return ""


def _asset_name_from_file(path_text: str) -> str:
    """Nombre de asset Flow para un archivo local generado (stem saneado).
    flow.js nombra los archivos sin caracteres raros; defensa extra igualmente.
    BI1/BJ4: ya NO se usa para derivar el startFrame — el asset real se
    identifica por la línea "Asset: <name> [id:<mediaId>]" de la salida de
    flow_generate_image (_parse_generated_asset); se conserva solo como
    utilidad de saneo para casos futuros."""
    stem = Path(path_text).stem.strip()
    stem = re.sub(r"[^A-Za-z0-9_\-]", "_", stem)[:64] or "frame"
    return stem


# ── BJ4: startFrame = "id:<mediaId>" del asset REAL en Flow ───────────────
# Flow nombra sus assets por el CONTENIDO del prompt (p. ej. "Red apple
# character peeking"), no por el archivo local descargado (que es una
# previsualización reducida, p. ej. 286x512). Desde BJ2 el tool
# flow_generate_image emite una línea "Asset: <name> [id:<mediaId>]" por
# imagen ANTES de las rutas: se parsea y el video se llama con
# startFrame="id:<mediaId>" — inequívoco aunque Flow repita nombres. Si la
# línea no viene, respaldo HONESTO: subir la copia local con nombre
# explícito único (copia reducida) y, si también falla, error claro sin
# adivinar.
_ASSET_LINE_RE = re.compile(
    r"^\s*Asset:\s*(?P<name>.+?)\s*\[id:\s*(?P<id>[^\]\s]+)\]\s*$",
    re.IGNORECASE)


def _parse_generated_asset(text: str) -> tuple[str, str]:
    """BJ4: extrae (nombre, mediaId) de la ÚLTIMA línea "Asset: <name>
    [id:<mediaId>]" de la salida de flow_generate_image (el orquestador
    siempre genera con count=1, pero si hubiera varias, la última es la más
    reciente). ("", "") si la salida no trae línea Asset: — el caller usa el
    respaldo de subida, JAMÁS adivina."""
    for line in reversed((text or "").splitlines()):
        m = _ASSET_LINE_RE.match(line)
        if m:
            return m.group("name").strip(), m.group("id").strip()
    return "", ""


def _asset_in_listing(name: str, aid: str,
                      listing: list[tuple[str, str | None]]) -> bool:
    """BJ4: ¿el start-frame (nombre, id) sigue existiendo en Flow?
    Si el listado trae ids (formato BJ2 real), el id MANDA cuando la escena
    lo tiene: un id ausente del listado significa que ESE asset ya no está
    aunque otro se llame igual (duplicados) → False. Si la escena no tiene
    id (respaldo de subida) o el listado no trae ids (compatibilidad), se
    coincide por nombre exacto. listing de _parse_asset_listing."""
    nombres = {n for n, _ in listing}
    ids = {a for _, a in listing if a}
    if ids and aid:
        return aid in ids
    return bool(name) and name in nombres


# ids inline en el LISTADO de assets (BJ2 real: "- <name> [id:<mediaId>]";
# se admite también la variante entre paréntesis por compatibilidad).
_ASSET_ID_RE = re.compile(r"\[id:\s*([^\]\s]+)\]|\(id:\s*([^)\s]+)\)",
                           re.IGNORECASE)


def _parse_asset_listing(text: str) -> list[tuple[str, str | None]]:
    """Parsea la salida de flow_list_assets → [(nombre, id|None), …].
    BJ2: el formato REAL del tool es "- <name> [id:<mediaId>]" por asset;
    siguen admitiéndose por compatibilidad: viñetas sin id ("- Nombre"),
    líneas planas, id inline entre paréntesis ("- Nombre (id: xyz)"),
    "(the project has no images yet)", "[]"/"{}" y JSON
    [{"name": …, "id": …}]. Un id inline se separa del nombre. Nunca
    inventa entradas."""
    t = (text or "").strip()
    if not t or "has no images yet" in t:
        return []
    if t.startswith("[") or t.startswith("{"):
        try:
            data = json.loads(t)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, list):
            out: list[tuple[str, str | None]] = []
            for it in data:
                if isinstance(it, str) and it.strip():
                    out.append((it.strip(), None))
                elif (isinstance(it, dict) and isinstance(it.get("name"), str)
                      and it.get("name").strip()):
                    aid = it.get("id")
                    out.append((it["name"].strip(),
                                aid.strip() if isinstance(aid, str)
                                and aid.strip() else None))
            return out
        if isinstance(data, dict):
            inner = data.get("assets")
            if isinstance(inner, list):
                return _parse_asset_listing(
                    json.dumps(inner, ensure_ascii=False))
            return []
    out = []
    for line in t.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("- "):
            line = line[2:].strip()          # prefijo ANTES del id: índices correctos
        if not line or set(line) <= {"-"}:   # vacía o viñeta sin texto
            continue
        m = _ASSET_ID_RE.search(line)
        aid = ""
        if m:
            aid = (m.group(1) or m.group(2) or "").strip()
            line = (line[:m.start()] + line[m.end():]).strip(" -(\"'").strip()
        if not line:
            continue
        out.append((line, aid or None))
    return out


def _strip_control_chars(s: str) -> str:
    """BG2: quita caracteres de control (categoría Unicode Cc) de un string.
    Normalización declarada de la puerta externa — nunca rechaza por ellos."""
    return "".join(c for c in s if unicodedata.category(c) != "Cc")


def validate_external_blueprint(bp: Any, max_scenes: int | None = None) -> dict:
    """BG2: valida y normaliza un blueprint externo (puerta declarada).
    Esquema EXACTO:
      {"label": str 1-30 [A-Za-z0-9 _.-], "title": str <=120,
       "scenes": [{"title" <=80, "narration" <=300, "image_prompt" <=1200}]}
    · 1..12 escenas; si hay más que max_scenes → rechazo (NUNCA truncar).
    · solo strings; los caracteres de control se QUITAN (normalización).
    · payload total <=20 KB.
    Cualquier otro caso inválido → PipelineError INVALID_BLUEPRINT."""
    def _invalid(msg: str) -> PipelineError:
        return PipelineError(
            f"blueprint externo inválido: {msg}", "INVALID_BLUEPRINT")

    if not isinstance(bp, dict):
        raise _invalid("debe ser un objeto JSON {label, title, scenes}")
    try:
        size = len(json.dumps(bp, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as e:
        raise _invalid(f"no serializable a JSON ({type(e).__name__})") from e
    if size > EXTERNAL_BLUEPRINT_MAX_BYTES:
        raise _invalid(f"payload {size} bytes supera el límite de "
                       f"{EXTERNAL_BLUEPRINT_MAX_BYTES} bytes")
    if set(bp.keys()) != _EXTERNAL_BP_KEYS:
        recibidas = ", ".join(sorted(str(k) for k in bp.keys())) or "(ninguna)"
        raise _invalid("claves exactas requeridas: label, title, scenes "
                       f"(recibidas: {recibidas})")
    label = bp.get("label")
    if not isinstance(label, str) or not _EXTERNAL_LABEL_RE.fullmatch(label):
        raise _invalid("label debe ser un string de 1-30 caracteres "
                       "[A-Za-z0-9 _.-]")
    title = bp.get("title")
    if not isinstance(title, str):
        raise _invalid("title debe ser un string")
    title = _strip_control_chars(title)
    if len(title) > 120:
        raise _invalid(f"title {len(title)} caracteres supera el máximo de 120")
    scenes_in = bp.get("scenes")
    if not isinstance(scenes_in, list):
        raise _invalid("scenes debe ser una lista")
    if not (1 <= len(scenes_in) <= 12):
        raise _invalid(f"{len(scenes_in)} escenas fuera del rango 1-12")
    if max_scenes is not None and len(scenes_in) > max_scenes:
        # BG2: rechazo explícito — NUNCA truncar en silencio
        raise _invalid(f"{len(scenes_in)} escenas superan max_scenes={max_scenes}")
    scenes_out: list[dict] = []
    for i, sc in enumerate(scenes_in):
        if not isinstance(sc, dict) or set(sc.keys()) != _EXTERNAL_SCENE_KEYS:
            raise _invalid(f"escena {i + 1}: claves exactas requeridas: "
                           "title, narration, image_prompt")
        clean: dict[str, str] = {}
        for k, lim in (("title", 80), ("narration", 300),
                       ("image_prompt", 1200)):
            v = sc.get(k)
            if not isinstance(v, str):
                raise _invalid(f"escena {i + 1}: '{k}' debe ser un string")
            v = _strip_control_chars(v)
            if len(v) > lim:
                raise _invalid(f"escena {i + 1}: '{k}' con {len(v)} caracteres "
                               f"supera el máximo de {lim}")
            clean[k] = v
        scenes_out.append(clean)
    return {"label": label, "title": title, "scenes": scenes_out}


class PipelineOrchestrator:
    """Coordina las 3 etapas y guarda el estado de cada corrida."""

    def __init__(self, manager: mcpm.MCPClientManager | None = None,
                 runs_dir: Path | None = None):
        self.manager = manager or mcpm.manager
        self.runs_dir = Path(runs_dir) if runs_dir else (
            Path(config.DATA_DIR) / "pipeline_runs")
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, asyncio.Task] = {}
        self._busy: str | None = None  # single-flight: Flow serializa en el Chrome
        self._render_busy: dict[str, bool] = {}  # Stage 4 por corrida

    # ──────────────────────────────── persistencia ──
    def _run_dir(self, run_id: str) -> Path:
        if not _RUN_ID_RE.match(run_id):
            raise PipelineError(f"run_id inválido: '{run_id[:40]}'", "RUN_NOT_FOUND")
        return self.runs_dir / run_id

    def _save(self, run: dict) -> None:
        d = self._run_dir(run["run_id"])
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "state.json.tmp"
        tmp.write_text(json.dumps(run, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, d / "state.json")  # atómico

    def _load(self, run_id: str) -> dict:
        try:
            f = self._run_dir(run_id) / "state.json"
            run = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise PipelineError(f"corrida no encontrada: {run_id}", "RUN_NOT_FOUND")
        # backfill INT-024: corridas creadas antes del Stage 4
        run.setdefault("render", {"status": "idle", "stage": "",
                                  "progress_pct": 0, "output": "",
                                  "error_code": "", "error_detail": "",
                                  "started_at": "", "finished_at": ""})
        run.setdefault("context_source", "")
        run.setdefault("nicho_id", None)
        # backfill BG2: corridas creadas antes de la puerta de blueprint externo
        run.setdefault("blueprint_source", "")
        run.setdefault("external_blueprint", None)
        return run

    def _load_local_context(self, nicho_id: str | None) -> str | None:
        """Carga el contexto local de respaldo en backend/data/nichos/<nicho_id>/contexto.md.
        Valida que nicho_id cumpla con ^[a-z0-9][a-z0-9_-]{0,40}$, previene traversal y symlinks,
        y lee hasta un máximo de 64 KB UTF-8."""
        if not nicho_id:
            return None
        nid = str(nicho_id).strip()
        if not _NICHO_ID_RE.match(nid):
            raise PipelineError(f"nicho_id inválido: '{nid[:40]}'", "INVALID_NICHO_ID")

        nichos_dir = (config.DATA_DIR / "nichos").resolve()
        target_dir = (nichos_dir / nid).resolve()
        target_file = (target_dir / "contexto.md").resolve()

        try:
            target_dir.relative_to(nichos_dir)
            target_file.relative_to(target_dir)
        except (ValueError, RuntimeError):
            raise PipelineError(f"nicho_id fuera de nichos: '{nid}'", "INVALID_NICHO_ID")

        if target_dir.is_symlink() or target_file.is_symlink():
            raise PipelineError(f"symlinks no permitidos en nicho_id: '{nid}'", "INVALID_NICHO_ID")

        if not target_file.is_file():
            return None

        try:
            content_bytes = target_file.read_bytes()
            if len(content_bytes) > MAX_NICHO_CONTEXT_BYTES:
                content_bytes = content_bytes[:MAX_NICHO_CONTEXT_BYTES]
            return content_bytes.decode("utf-8", errors="replace")
        except OSError as e:
            log.warning("[pipeline] Error leyendo contexto local de nicho '%s': %s", nid, e)
            return None

    # ──────────────────────────────── API pública ──
    def create_run(self, idea: str, notebook_id: str | None = None,
                   fmt: str = "short", style: str = "auto",
                   max_scenes: int | None = None,
                   nicho_id: str | None = None,
                   blueprint: dict | None = None) -> dict:
        idea = (idea or "").strip()
        if not idea:
            raise PipelineError("idea requerida para el pipeline", "IDEA_REQUIRED")
        if self._busy:
            raise PipelineError(
                f"ya hay un pipeline en marcha ({self._busy}) — espera su fin "
                f"o usa retry-scenes", "PIPELINE_BUSY")
        if max_scenes is not None:
            try:
                max_scenes = int(max_scenes)
            except (ValueError, TypeError) as e:
                raise PipelineError("max_scenes debe ser un entero entre 1 y 12", "INVALID_MAX_SCENES") from e
            if not (1 <= max_scenes <= 12):
                raise PipelineError("max_scenes debe ser un entero entre 1 y 12", "INVALID_MAX_SCENES")
        # BG2: blueprint externo (puerta declarada) — se valida EN LA CREACIÓN
        # para que un blueprint inválido jamás llegue a arrancar una corrida.
        external_bp = None
        if blueprint is not None:
            external_bp = validate_external_blueprint(blueprint, max_scenes)
        if nicho_id is not None:
            nicho_id = str(nicho_id).strip()
            if nicho_id:
                if not _NICHO_ID_RE.match(nicho_id):
                    raise PipelineError(f"nicho_id inválido: '{nicho_id[:40]}'", "INVALID_NICHO_ID")
            else:
                nicho_id = None
        now = time.strftime("%Y%m%d_%H%M%S")
        run_id = f"run_{now}_{uuid.uuid4().hex[:6]}"
        run = {
            "run_id": run_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "idea": idea[:500],
            "notebook_id": (notebook_id or "").strip(),
            "nicho_id": nicho_id,
            "context_source": "",
            "format": fmt if fmt in ("short", "long") else "short",
            "style": (style or "auto").strip()[:40] or "auto",
            "max_scenes": max_scenes,
            "stage": ST_QUEUED,
            "error_code": "",
            "error_detail": "",
            "steps": [{"stage": s, "label": lbl, "state": "pending", "detail": ""}
                      for s, lbl in _STEPS],
            "progress_pct": 0,
            "context_chars": 0,
            "blueprint_title": "",
            "engine": "",
            "gemini_model": "",
            "blueprint_source": "",             # BG2: "external" si blueprint externo
            "external_blueprint": external_bp,  # BG2: blueprint normalizado o None
            "scenes": [],
            "dispatched": 0,
            "done_count": 0,
            "failed_scene_ids": [],
            "reference_asset": "",
            "render": {"status": "idle", "stage": "", "progress_pct": 0,
                       "output": "", "error_code": "", "error_detail": "",
                       "started_at": "", "finished_at": ""},
        }
        self._save(run)
        return run

    def start_run(self, run_id: str) -> asyncio.Task:
        run = self._load(run_id)
        if run["stage"] != ST_QUEUED:
            raise PipelineError(
                "esa corrida ya está en marcha o terminó — crea una nueva",
                "PIPELINE_BUSY")
        if self._busy:
            raise PipelineError(
                f"ya hay un pipeline en marcha ({self._busy})", "PIPELINE_BUSY")
        self._busy = run_id
        run["stage"], run["error_code"], run["error_detail"] = ST_PREFLIGHT, "", ""
        for st in run["steps"]:
            st["state"] = "pending"
        run["progress_pct"] = 0
        self._save(run)
        task = asyncio.create_task(self._run(run_id))
        self._tasks[run_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(run_id, None))
        return task

    async def wait(self, run_id: str, timeout: float = 60.0) -> None:
        """Espera el fin de una corrida (tests y cierres ordenados)."""
        t = self._tasks.get(run_id)
        if t:
            await asyncio.wait_for(t, timeout=timeout)

    def get_status(self, run_id: str = "") -> dict:
        if not run_id:
            runs = sorted(self.runs_dir.glob("run_*/state.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
            if not runs:
                raise PipelineError("no hay corridas todavía", "RUN_NOT_FOUND")
            run_id = runs[0].parent.name
        return self._load(run_id)

    async def retry_scenes(self, run_id: str,
                           scene_ids: list[str] | None = None,
                           force: bool = False) -> dict:
        """Re-despacha SOLO escenas fallidas (o forzadas quirúrgicamente) de Stage 3 (§2 del mandato).
        Nunca repite Stage 1/2: usa el blueprint persistido."""
        run = self._load(run_id)
        # ST_QUEUED = creada y nunca lanzada: no está "en marcha"
        if run["stage"] in _STAGES_ACTIVE and run["stage"] != ST_QUEUED:
            raise PipelineError("el pipeline sigue en marcha", "PIPELINE_BUSY")
        if not run["scenes"]:
            raise PipelineError(
                "no hay blueprint persistido — relanza el pipeline completo",
                "RETRY_NO_BLUEPRINT")

        if force and scene_ids:
            all_ids = {s["scene_id"] for s in run["scenes"]}
            targets = set(scene_ids) & all_ids
            if not targets:
                raise PipelineError("las escenas indicadas no existen en la corrida",
                                    "NO_TARGET_SCENES")
            # Preparar las escenas objetivo para regeneración quirúrgica
            for s in run["scenes"]:
                if s["scene_id"] in targets:
                    if s["status"] == "done":
                        run["done_count"] = max(0, run["done_count"] - 1)
                    s["status"] = "pending"
                    s["detail"] = "Regeneración quirúrgica solicitada"
        else:
            failed = {s["scene_id"] for s in run["scenes"] if s["status"] == "failed"}
            targets = set(scene_ids or []) & failed if scene_ids else failed
            if not targets:
                raise PipelineError("no hay escenas fallidas que reintentar",
                                    "NO_FAILED_SCENES")
        if self._busy:
            raise PipelineError(
                f"ya hay un pipeline en marcha ({self._busy})", "PIPELINE_BUSY")
        if self._render_busy.get(run_id):
            raise PipelineError(
                f"la corrida {run_id} está renderizando (Stage 4) — espera su fin",
                "RENDER_BUSY")
        self._busy = run_id
        try:
            run["stage"], run["error_code"], run["error_detail"] = ST_STAGE3, "", ""
            self._set_step(run, ST_STAGE3, "running",
                           f"retry de {len(targets)} escena(s)")
            await self._stage3(run, only_scene_ids=targets)
            run["failed_scene_ids"] = [s["scene_id"] for s in run["scenes"]
                                        if s["status"] == "failed"]
            if run["failed_scene_ids"]:
                run["error_code"] = "PARTIAL_FAILURES"
                run["error_detail"] = ("aún fallan: "
                                       + ", ".join(run["failed_scene_ids"]))
                run["progress_pct"] = 95
            else:
                run["error_code"], run["error_detail"] = "", ""
                run["progress_pct"] = 100
            run["stage"] = ST_DONE
            self._set_step(run, ST_STAGE3,
                           "failed" if run["failed_scene_ids"] else "ok",
                           run["error_detail"] or
                           f"{run['done_count']}/{len(run['scenes'])} escenas OK")
            run["stage"] = ST_DONE   # _set_step fija la etapa en curso: re-fijar fin
        finally:
            self._busy = None
            self._save(run)
        return run

    # ─────────────────────── Stage 4: harvest + render ──
    def render_final(self, run_id: str,
                     force_placeholder_on_failed: bool = False,
                     dry_run: bool = False) -> dict:
        """Lanza Stage 3.5 (harvest + manifest) + Stage 4 (FFmpeg) en un hilo
        (NO bloquea el event loop). Gatekeeper del mandato §3:
        · corrida activa → PIPELINE_BUSY · ya renderizando → RENDER_BUSY
        · corrida sin Stage 3 terminado → RENDER_NOT_DONE
        · PARTIAL_FAILURES sin flag → RENDER_BLOCKED_PARTIAL_FAILURES
        · ffmpeg ausente sin dry_run → surfaced honesto desde el worker."""
        run = self._load(run_id)
        if run["stage"] in _STAGES_ACTIVE and run["stage"] != ST_QUEUED:
            raise PipelineError("el pipeline sigue en marcha", "PIPELINE_BUSY")
        if self._render_busy.get(run_id):
            raise PipelineError(
                f"la corrida {run_id} ya está renderizando", "RENDER_BUSY")
        if run["stage"] not in (ST_DONE, ST_ERROR):
            raise PipelineError(
                "Stage 3 no ha terminado — no hay assets que ensamblar",
                "RENDER_NOT_DONE")
        failed = list(run.get("failed_scene_ids") or [])
        if failed and not force_placeholder_on_failed:
            raise PipelineError(
                "escenas fallidas bloquean el render: " + ", ".join(failed)
                + " — usa retry-scenes o force_placeholder_on_failed=true",
                "RENDER_BLOCKED_PARTIAL_FAILURES")
        if not any(s.get("status") == "done" for s in run.get("scenes") or []):
            if not failed or not force_placeholder_on_failed:
                raise PipelineError(
                    "ninguna escena está lista — nada que ensamblar",
                    "RENDER_NOTHING_READY")
        self._render_busy[run_id] = True
        run["render"].update({"status": "running", "stage": "harvest",
                              "progress_pct": 0, "output": "",
                              "error_code": "", "error_detail": "",
                              "dry_run": bool(dry_run),
                              "force_placeholder": bool(failed) and bool(force_placeholder_on_failed),
                              "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                              "finished_at": ""})
        run["stage"] = ST_STAGE4
        self._set_step(run, ST_STAGE4, "running",
                       "harvest de assets + manifest")
        run["stage"] = ST_STAGE4  # _set_step fija la etapa en curso
        self._save(run)
        task = asyncio.create_task(asyncio.to_thread(
            self._render_worker, run_id, bool(dry_run)))
        self._tasks[f"render:{run_id}"] = task
        task.add_done_callback(
            lambda _t: (self._tasks.pop(f"render:{run_id}", None),
                        self._render_busy.pop(run_id, None)))
        return run["render"]

    def _render_progress(self, run_id: str) -> Callable[[str, str, int], None]:
        def cb(stage: str, detail: str, pct: int) -> None:
            try:
                run = self._load(run_id)
                run["render"].update({"stage": stage, "progress_pct": int(pct),
                                      "detail": str(detail)[:280]})
                self._set_step(run, ST_STAGE4, "running", f"[{stage}] {detail}")
                run["stage"] = ST_STAGE4
                self._save(run)
            except (PipelineError, OSError):
                pass  # la corrida dejó de existir: el worker termina solo
        return cb

    def _render_worker(self, run_id: str, dry_run: bool) -> None:
        """Cuerpo del Stage 4 EN HILO: harvest → manifest → assemble.
        Nunca lanza hacia el event loop: todo se persiste en run['render']."""
        try:
            run = self._load(run_id)
            rd = self._run_dir(run_id)
            force = bool(run["render"].get("force_placeholder"))
            manifest, _ = harv.harvest_run(run, rd, placeholders_for_failed=force)
            self._render_progress(run_id)("plan",
                f"manifest OK — {len(manifest['scenes'])} escena(s)", 5)
            res = vasm.assemble_run(
                rd, dry_run=dry_run,
                music_path=str(_cfg("RENDER_MUSIC_PATH", "") or ""),
                progress_cb=self._render_progress(run_id))
            run = self._load(run_id)
            run["render"].update({"status": "done", "stage": "done",
                                  "progress_pct": 100,
                                  "output": res["output"],
                                  "dry_run": bool(dry_run),
                                  "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                  "detail": f"{res.get('steps', '?')} pasos · "
                                            f"{res.get('duration_total', 0):.1f}s"
                                            f"{'' if not dry_run else ' (dry-run)'}"})
            self._set_step(run, ST_STAGE4, "ok",
                           ("dry-run: plan generado → " if dry_run else "render final → ")
                           + Path(res["output"]).name)
            run["stage"] = ST_DONE
            self._save(run)
            log.info("[render %s] terminado: %s", run_id, res["output"])
        except (harv.HarvesterError, vasm.AssemblerError) as e:
            self._render_fail(run_id, e.code, str(e))
        except Exception as e:  # noqa: BLE001 — el render nunca tumba el backend
            self._render_fail(run_id, "RENDER_CRASH", str(e)[:300])

    def _render_fail(self, run_id: str, code: str, detail: str) -> None:
        try:
            run = self._load(run_id)
            run["render"].update({"status": "error", "error_code": code,
                                  "error_detail": detail[:400],
                                  "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
            self._set_step(run, ST_STAGE4, "failed", f"[{code}] {detail[:200]}")
            run["stage"] = ST_DONE
            self._save(run)
            log.error("[render %s] %s: %s", run_id, code, detail[:200])
        except (PipelineError, OSError):
            pass

    def get_render_status(self, run_id: str = "") -> dict:
        """Snapshot del Stage 4 (la última corrida si no se indica run_id)."""
        run = self.get_status(run_id)
        return {"run_id": run["run_id"], "stage": run["stage"],
                "failed_scene_ids": run.get("failed_scene_ids") or [],
                "render": run.get("render") or {}}

    def get_manifest(self, run_id: str) -> dict:
        """Manifest.json de la corrida (404 limpio si no existe)."""
        self._load(run_id)  # valida run_id + existencia
        return harv.load_manifest(self._run_dir(run_id))

    def harvest_only(self, run_id: str,
                     placeholders_for_failed: bool = False) -> dict:
        """Stage 3.5 standalone: re-consolida assets + regenera manifest.json
        SIN renderizar (útil para inspección y para tests)."""
        run = self._load(run_id)
        if run["stage"] in _STAGES_ACTIVE and run["stage"] != ST_QUEUED:
            raise PipelineError("el pipeline sigue en marcha", "PIPELINE_BUSY")
        if run["stage"] not in (ST_DONE, ST_ERROR):
            raise PipelineError(
                "Stage 3 no ha terminado — no hay assets que consolidar",
                "RENDER_NOT_DONE")
        force = bool(placeholders_for_failed)
        manifest, _ = harv.harvest_run(run, self._run_dir(run_id),
                                       placeholders_for_failed=force)
        return manifest

    # ──────────────────────────────── motor de etapas ──
    def _set_step(self, run: dict, stage: str, state: str,
                  detail: str = "") -> None:
        for st in run["steps"]:
            if st["stage"] == stage:
                st["state"] = state
                if detail:
                    st["detail"] = detail[:280]
        run["stage"] = stage
        self._save(run)

    def _pct(self, run: dict) -> int:
        base = {ST_PREFLIGHT: 5, ST_STAGE1: 25, ST_STAGE2: 45}.get(run["stage"])
        if base is not None:
            return base
        if run["stage"] == ST_STAGE3:
            total = max(1, len(run["scenes"]))
            return min(95, 50 + int(45 * run["dispatched"] / total))
        return 100 if run["stage"] == ST_DONE else run.get("progress_pct", 0)

    def _fail(self, run: dict, code: str, detail: str) -> None:
        run["error_code"], run["error_detail"] = code, detail[:400]
        run["stage"] = ST_ERROR
        step = {"preflight": ST_PREFLIGHT, "notebooklm": ST_STAGE1}.get(
            code.split("_")[-1], "")
        for st in run["steps"]:
            if st["state"] == "running":
                st["state"] = "failed"
                st["detail"] = f"[{code}] {detail[:200]}"
        self._save(run)
        log.error("[pipeline %s] %s: %s", run["run_id"], code, detail[:200])

    async def _exposed_tools(self, service: str) -> set[str]:
        """Consulta el conjunto de nombres de tools expuestas por el servidor MCP.
        Usa tools_catalog si existe o inspecciona la conexión viva; ante fallos
        operacionales devuelve set() sin capturar Exception genérica."""
        if hasattr(self.manager, "tools_catalog"):
            try:
                cat = await self.manager.tools_catalog(service, auto_connect=True)
                return {t.get("name") for t in (cat.get("tools") or []) if t.get("name")}
            except (mcpm.MCPManagerError, OSError, asyncio.TimeoutError, KeyError, AttributeError, TypeError) as e:
                log.debug(f"[_exposed_tools {service}] tools_catalog no disponible: {e}")
        elif hasattr(self.manager, "_conns"):
            try:
                conn = getattr(self.manager, "_conns", {}).get(service)
                if conn and getattr(conn, "tools", None):
                    return {t.get("name") for t in conn.tools if t.get("name")}
            except (KeyError, AttributeError, TypeError):
                pass
        return set()

    async def _flow_keepalive(self, run: dict, interval: float = 45.0,
                              timeout: float = 30.0) -> None:
        """D2: keepalive CDP acotado a la corrida (etapas 0-2): ping periódico a
        flow_list_assets para que el transporte CDP de Flow no se duerma mientras
        Gemini genera el blueprint (Stage 2 puede tardar minutos). Los errores
        SOLO se registran — nunca se lanzan ni tumban la corrida. Cancelable:
        _run cancela la tarea que la ejecuta en TODAS las salidas (finally)."""
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    res = await self.manager.execute(
                        "google-flow", "flow_list_assets", {}, timeout=timeout)
                    log.info("[pipeline %s] Keepalive Flow CDP: ok=%s",
                             run.get("run_id"), res.get("ok"))
                except (mcpm.MCPManagerError, RuntimeError, OSError, TimeoutError,
                        asyncio.TimeoutError) as e:
                    # Los errores solo se registran, nunca se lanzan
                    log.warning("[pipeline %s] Keepalive Flow CDP falló (ignorado): %s",
                                run.get("run_id"), e)
        except asyncio.CancelledError:
            pass

    async def _run(self, run_id: str) -> None:
        run = self._load(run_id)
        keepalive_task: asyncio.Task | None = None

        async def _cancel_keepalive() -> None:
            nonlocal keepalive_task
            if keepalive_task and not keepalive_task.done():
                keepalive_task.cancel()
                try:
                    await keepalive_task
                except (asyncio.CancelledError, RuntimeError, OSError):
                    pass
                keepalive_task = None

        try:
            # ── pre-flight gatekeeper (§2): aborta ANTES de gastar tokens ──
            self._set_step(run, ST_PREFLIGHT, "running")
            run["progress_pct"] = 5
            is_local_mode = str(_cfg("PIPELINE_CONTEXT_SOURCE", "") or "").strip().lower() == "local"
            if not is_local_mode:
                pre_n = await self.manager.test_pipeline(
                    "notebooklm", notebook_id=run["notebook_id"] or None)
                if not pre_n.get("ok"):
                    code = ("PRE_FLIGHT_AUTH" if pre_n.get("state") == mcpm.ST_AUTH_REQUIRED
                            else "PRE_FLIGHT_NOTEBOOKLM")
                    self._fail(run, code,
                               f"NotebookLM no listo: state={pre_n.get('state')} "
                               f"auth={pre_n.get('auth')} {pre_n.get('detail') or pre_n.get('auth_detail') or ''}")
                    return
            pre_f = await self.manager.test_pipeline("google-flow")
            if not pre_f.get("ok"):
                code = ("PRE_FLIGHT_AUTH" if pre_f.get("state") == mcpm.ST_AUTH_REQUIRED
                        else "PRE_FLIGHT_FLOW")
                self._fail(run, code,
                           f"Google Flow no listo: state={pre_f.get('state')} "
                           f"auth={pre_f.get('auth')} {pre_f.get('detail') or pre_f.get('auth_detail') or ''}")
                return
            # ── HOTFIX INT-023.4: propagación / auto-descubrimiento del notebook_id ──
            # Resolución: UI payload > .env NOTEBOOKLM_NOTEBOOK_ID > auto-descubrimiento
            # vía la tool de listado del MCP (notebook_list / list_notebooks). Si nada
            # produce un id, [0/3] ABORTA con PRE_FLIGHT_MISSING_NOTEBOOK_ID antes de
            # gastar tokens — nunca se llega a Stage 1 con notebook_id vacío.
            nid = (run["notebook_id"] or "").strip()
            if not nid and not is_local_mode:
                nid = str(_cfg("NOTEBOOKLM_NOTEBOOK_ID", "") or "").strip()
                if nid:
                    run["notebook_id"] = nid          # env → estado (visibilidad total)
                    self._save(run)
            pre_detail = "local-context ✅ · google-flow ✅" if is_local_mode else "notebooklm ✅ · google-flow ✅"
            if not nid and not is_local_mode:
                disc = getattr(self.manager, "discover_notebook_id", None)
                auto = ""
                if disc:
                    try:
                        auto = await disc() or ""
                    except Exception:  # noqa: BLE001 — degrada al guard determinista
                        auto = ""
                if auto and mcpm._NOTEBOOK_ID_RE.match(auto):
                    run["notebook_id"] = auto
                    self._save(run)
                    nid = auto
                    pre_detail += (f" · notebook_id auto-descubierto vía list tool: "
                                   f"{auto[:12]}…")
                    log.info("[pipeline %s] notebook_id auto-descubierto: %s",
                             run["run_id"], auto)
                else:
                    self._fail(run, "PRE_FLIGHT_MISSING_NOTEBOOK_ID",
                               "notebook_id ausente en la UI y en .env, y el auto-"
                               "descubrimiento (list tool) no devolvió notebooks. "
                               "Conecta NotebookLM en el panel MCP — el dropdown "
                               "«Notebook activo» se rellena SOLO con tus notebooks "
                               "y eliges con 1 click —, o fija NOTEBOOKLM_NOTEBOOK_ID "
                               "en backend/.env. Si el badge está rojo de sesión: "
                               "«🔑 Vincular Sesión Google (Login Único)» + «📥 "
                               "Capturar sesión».")
                    return
            self._set_step(run, ST_PREFLIGHT, "ok", pre_detail)
            # D2: Keepalive acotado a la corrida durante etapas 0 a 2
            ka_interval = float(_cfg("FLOW_KEEPALIVE_INTERVAL", 45.0))
            ka_timeout = float(_cfg("FLOW_KEEPALIVE_TIMEOUT", 30.0))
            keepalive_task = asyncio.create_task(
                self._flow_keepalive(run, ka_interval, ka_timeout))

            # ── Stage 1: contexto de NotebookLM (solo-lectura) o Local ──
            self._set_step(run, ST_STAGE1, "running")
            run["progress_pct"] = 25
            nicho_id = run.get("nicho_id")
            context = None
            context_source = ""

            # 2) Si PIPELINE_CONTEXT_SOURCE == "local", saltar NotebookLM por completo
            if str(_cfg("PIPELINE_CONTEXT_SOURCE", "") or "").strip().lower() == "local":
                local_ctx = self._load_local_context(nicho_id)
                if local_ctx:
                    context = local_ctx
                    context_source = "local"
                    log.warning(
                        "[pipeline %s] PIPELINE_CONTEXT_SOURCE=local: "
                        "usando contexto local de '%s' (%d caracteres)",
                        run["run_id"], nicho_id, len(context)
                    )
                else:
                    self._fail(
                        run, "CONTEXT_EMPTY",
                        f"Sin sesión de NotebookLM y sin contexto local del nicho '{nicho_id or ''}'"
                    )
                    return

            if context is None:
                tool = str(_cfg("NOTEBOOKLM_CONTEXT_TOOL", "notebook_query") or "").strip()
                query = str(_cfg(
                    "NOTEBOOKLM_CONTEXT_QUERY",
                    "Extrae del notebook la biblia de investigación para producir un "
                    "video: puntos clave y datos verificables, arco narrativo sugerido, "
                    "y una descripción física CONSISTENTE del personaje principal "
                    "(look, ropa, rasgos) reutilizable en todas las escenas.") or "").strip()

                # BB1: si el servidor no expone la tool configurada pero sí notebook_query, usar notebook_query y loguear aviso
                if tool != "notebook_query":
                    exposed_tools = await self._exposed_tools("notebooklm")
                    if exposed_tools and tool not in exposed_tools and "notebook_query" in exposed_tools:
                        log.warning(
                            f"[pipeline {run['run_id']}] El servidor NotebookLM no expone '{tool}' "
                            f"pero sí 'notebook_query' — usando 'notebook_query'"
                        )
                        tool = "notebook_query"

                auth_error_detected = False
                auth_error_msg = ""
                res = None

                try:
                    # HOTFIX INT-023.4: inyección EXPLÍCITA del id resuelto en los
                    # arguments (defensa en profundidad; mcp_manager re-valida/inyecta).
                    id_key = str(_cfg("NOTEBOOKLM_ID_KEY", "notebook_id") or "notebook_id")
                    args = {"query": query}
                    if (run["notebook_id"] or "").strip():
                        args[id_key] = run["notebook_id"].strip()
                    res = await self.manager.execute(
                        "notebooklm", tool, args,
                        timeout=float(_cfg("NOTEBOOKLM_MCP_TIMEOUT", 60.0)),
                        notebook_id=run["notebook_id"] or None)
                except mcpm.MCPManagerError as e:
                    if e.code == "TOOL_UNKNOWN" and tool != "notebook_query":
                        exposed = await self._exposed_tools("notebooklm")
                        if "notebook_query" in exposed or not exposed:
                            log.warning(
                                f"[pipeline {run['run_id']}] El servidor NotebookLM no expone '{tool}' "
                                f"pero sí 'notebook_query' — fallback a 'notebook_query'"
                            )
                            tool = "notebook_query"
                            try:
                                res = await self.manager.execute(
                                    "notebooklm", tool, args,
                                    timeout=float(_cfg("NOTEBOOKLM_MCP_TIMEOUT", 60.0)),
                                    notebook_id=run["notebook_id"] or None)
                            except mcpm.MCPManagerError as e2:
                                if e2.code in ("AUTH_REQUIRED", "SESSION_INVALID", "TIMEOUT") or any(k in str(e2).lower() for k in ("auth", "expired", "400", "bad request", "forbidden", "403", "timeout")):
                                    auth_error_detected = True
                                    auth_error_msg = str(e2)
                                else:
                                    code = ("PRE_FLIGHT_MISSING_NOTEBOOK_ID"
                                            if e2.code == "MISSING_NOTEBOOK_ID" else "CONTEXT_EXTRACTION_FAILED")
                                    self._fail(run, code, f"tool '{tool}': [{e2.code}] {e2}")
                                    return
                        else:
                            self._fail(run, "CONTEXT_EXTRACTION_FAILED", f"tool '{tool}': [{e.code}] {e}")
                            return
                    elif e.code in ("AUTH_REQUIRED", "SESSION_INVALID", "TIMEOUT") or any(k in str(e).lower() for k in ("auth", "expired", "400", "bad request", "forbidden", "403", "timeout")):
                        auth_error_detected = True
                        auth_error_msg = str(e)
                    else:
                        code = ("PRE_FLIGHT_MISSING_NOTEBOOK_ID"
                                if e.code == "MISSING_NOTEBOOK_ID" else "CONTEXT_EXTRACTION_FAILED")
                        self._fail(run, code, f"tool '{tool}': [{e.code}] {e}")
                        return

                if not auth_error_detected and res is not None:
                    raw_text = (res.get("text") or "").strip()
                    parsed_json = None
                    if raw_text:
                        try:
                            loaded = json.loads(raw_text)
                            if isinstance(loaded, dict):
                                parsed_json = loaded
                        except (json.JSONDecodeError, ValueError):
                            parsed_json = None

                    if parsed_json is not None:
                        # BB2/BB3: si "text" es JSON, usar solo el campo "answer".
                        st = parsed_json.get("status")
                        ans = parsed_json.get("answer")
                        ans_str = str(ans or "").strip()
                        err_msg = str(parsed_json.get("error") or parsed_json.get("message") or "").strip()

                        if st != "success":
                            if any(k in err_msg.lower() for k in ("authentication expired", "re-authenticate", "auth", "400", "bad request", "forbidden", "403")):
                                auth_error_detected = True
                                auth_error_msg = err_msg
                            else:
                                if err_msg:
                                    detail = f"el cuaderno no tiene fuentes o no respondió: {err_msg}"
                                else:
                                    detail = "el cuaderno no tiene fuentes o no respondió: sube fuentes en NotebookLM"
                                self._fail(run, "CONTEXT_EMPTY", detail)
                                return
                        elif not ans_str:
                            self._fail(
                                run, "CONTEXT_EMPTY",
                                "el cuaderno no tiene fuentes o no respondió: sube fuentes en NotebookLM"
                            )
                            return
                        else:
                            context = ans_str
                            context_source = "notebooklm"
                    else:
                        # Si el texto no es JSON, comportamiento actual
                        context = raw_text
                        if not context:
                            self._fail(run, "CONTEXT_EMPTY",
                                       f"la tool '{tool}' devolvió texto vacío — revisa el "
                                       f"notebookId y NOTEBOOKLM_CONTEXT_TOOL")
                            return
                        context_source = "notebooklm"

                # 1) Si la consulta a NotebookLM devolvió error de autenticación:
                if auth_error_detected:
                    local_ctx = self._load_local_context(nicho_id)
                    if local_ctx:
                        context = local_ctx
                        context_source = "local"
                        log.warning(
                            "[pipeline %s] NotebookLM no autenticado ('%s'): "
                            "usando contexto local de '%s' (%d caracteres)",
                            run["run_id"], auth_error_msg, nicho_id, len(context)
                        )
                    else:
                        detail = f"el cuaderno no respondió: {auth_error_msg or 'Authentication expired'}"
                        self._fail(
                            run, "CONTEXT_EMPTY",
                            f"{detail} — Sin sesión de NotebookLM y sin contexto local del nicho"
                        )
                        return

            rd = self._run_dir(run["run_id"])
            rd.mkdir(parents=True, exist_ok=True)
            (rd / "context.md").write_text(context, encoding="utf-8")
            run["context_chars"] = len(context)
            run["context_source"] = context_source
            if context_source == "local":
                self._set_step(run, ST_STAGE1, "ok",
                               f"{len(context)} caracteres cargados del contexto local "
                               f"de nicho «{nicho_id or ''}»")
            else:
                self._set_step(run, ST_STAGE1, "ok",
                               f"{len(context)} caracteres extraídos del notebook "
                               f"«{run['notebook_id'] or '(env fallback)'}»")

            # ── Stage 2: blueprint con el generador EXISTENTE (sin tocarlo) ──
            self._set_step(run, ST_STAGE2, "running")
            run["progress_pct"] = 45
            ext_bp = run.get("external_blueprint")
            if ext_bp:
                # BG2: puerta DECLARADA — el blueprint llegó validado en
                # create_run y Gemini NO se llama en esta etapa. Visible:
                # engine "external:<label>", gemini_model "" y
                # blueprint_source "external" en /api/pipeline/status.
                log.warning("[pipeline %s] Blueprint EXTERNO %s: no generado por Gemini",
                            run["run_id"], ext_bp["label"])
                scenes = []
                for i, sc in enumerate(ext_bp["scenes"]):
                    scenes.append({
                        "scene_id": f"s{i + 1}",
                        "title": sc.get("title") or f"Escena {i + 1}",
                        "narration": sc.get("narration") or "",
                        "image_prompt": sc.get("image_prompt") or "",
                        "status": "pending",
                        "attempts": 0,
                        "video_file": "",
                        "start_frame_asset": "",   # BI1/BJ4: nombre Flow real
                        "start_frame_asset_id": "",   # BJ4: mediaId del asset
                        "detail": "",
                    })
                active_model = ""
                blueprint = {"title": ext_bp.get("title") or run["idea"][:60],
                             "hook": "", "cta": "",
                             "engine": f"external:{ext_bp['label']}",
                             "notebook_id": run["notebook_id"],
                             "format": run["format"], "style": run["style"],
                             "context_source": run.get("context_source", "notebooklm"),
                             "gemini_model": "",
                             "blueprint_source": "external",
                             "scenes": scenes}
            else:
                idea_enriched = (
                    f"{run['idea']}\n\n[Contexto verificado extraído de NotebookLM — "
                    f"úsalo como bíblia de investigación: hechos, arco narrativo y "
                    f"descripción consistente del personaje]:\n"
                    + context[:int(_cfg("PIPELINE_CONTEXT_MAX_CHARS", 6000))])
                try:
                    raw = await script_gen.from_idea(idea_enriched, run["style"],
                                                     run["format"], None, None)
                    res2 = script_gen.build_result(raw)
                except Exception as e:  # noqa: BLE001 — surfaced, no tumba el backend
                    self._fail(run, "BLUEPRINT_FAILED", str(e)[:300])
                    return

                if res2.get("engine") == "local-demo" and os.environ.get("PIPELINE_ALLOW_DEMO") != "1":
                    # BG1: motivo REAL registrado por script_gen (código y tipo,
                    # sin claves). Sin error registrado → no había GEMINI_API_KEY
                    # (hecho, no la sugerencia fija eliminada).
                    motivo = (script_gen.describe_gemini_error()
                              or "sin GEMINI_API_KEY configurada")
                    self._fail(run, "BLUEPRINT_DEMO",
                               f"Gemini falló: {motivo} — "
                               "el guion salió del generador demo y no se despacha a Flow")
                    return

                scenes = []
                for i, sc in enumerate(res2.get("scenes") or []):
                    scenes.append({
                        "scene_id": f"s{i + 1}",
                        "title": sc.get("title") or f"Escena {i + 1}",
                        "narration": sc.get("narration") or "",
                        "image_prompt": sc.get("image_prompt") or "",
                        "status": "pending",
                        "attempts": 0,
                        "video_file": "",
                        "start_frame_asset": "",   # BI1/BJ4: nombre Flow real
                        "start_frame_asset_id": "",   # BJ4: mediaId del asset
                        "detail": "",
                    })
                if not scenes:
                    self._fail(run, "BLUEPRINT_EMPTY",
                               "el generador no devolvió escenas — revisa GEMINI_API_KEY "
                               "o el contenido del notebook")
                    return

                ms = run.get("max_scenes")
                if ms and len(scenes) > ms:
                    scenes = (scenes[:ms - 1] + [scenes[-1]]) if ms > 1 else [scenes[-1]]
                    for idx, sc in enumerate(scenes):
                        sc["scene_id"] = f"s{idx + 1}"
                from services import gemini_client
                active_model = gemini_client.get_active_text_model()
                blueprint = {"title": res2.get("title") or run["idea"][:60],
                             "hook": res2.get("hook", ""), "cta": res2.get("cta", ""),
                             "engine": res2.get("engine", "") or f"gemini ({active_model})",
                             "notebook_id": run["notebook_id"],
                             "format": run["format"], "style": run["style"],
                             "context_source": run.get("context_source", "notebooklm"),
                             "gemini_model": active_model,
                             "scenes": scenes}
            (rd / "blueprint.json").write_text(
                json.dumps(blueprint, ensure_ascii=False, indent=1),
                encoding="utf-8")
            run["scenes"] = json.loads(json.dumps(blueprint["scenes"]))
            run["blueprint_title"] = blueprint["title"]
            run["engine"] = blueprint["engine"]
            run["gemini_model"] = active_model
            if ext_bp:
                run["blueprint_source"] = "external"
            self._set_step(run, ST_STAGE2, "ok",
                           f"«{blueprint['title']}» — {len(scenes)} escenas "
                           f"(motor: {blueprint['engine']})")

            # D2: Cancelar keepalive al empezar la etapa 3 (el calentamiento ya cubre la transición)
            await _cancel_keepalive()

            # ── Stage 3: despacho a Flow (consistencia de personaje) ──
            self._set_step(run, ST_STAGE3, "running")
            try:
                await self._stage3(run)
            except PipelineError as e:
                # p.ej. FLOW_NOT_CONNECTED a mitad de corrida: estado limpio,
                # escenas pendientes quedan 'failed' y reintegrables vía retry
                self._fail(run, e.code, str(e))
                return
            failed = [s for s in run["scenes"] if s["status"] == "failed"]
            if failed:
                # §2: corrida termina con fallos PARCIALES registrados, assets intactos
                run["stage"] = ST_DONE
                run["error_code"] = "PARTIAL_FAILURES"
                run["error_detail"] = (
                    f"{len(failed)} escena(s) fallaron: "
                    f"{', '.join(s['scene_id'] for s in failed)} — usa retry-scenes")
                for st in run["steps"]:
                    if st["stage"] == ST_STAGE3:
                        st["state"], st["detail"] = "failed", run["error_detail"]
                run["progress_pct"] = 95
                self._save(run)
            else:
                self._set_step(run, ST_STAGE3, "ok",
                               f"{run['done_count']}/{len(run['scenes'])} escenas "
                               f"generadas en Flow")
                run["stage"], run["progress_pct"] = ST_DONE, 100
                self._save(run)
        except Exception as e:  # noqa: BLE001 — nunca colgar el backend por una corrida
            self._fail(run, "PIPELINE_CRASH", str(e)[:300])
        finally:
            # D2: el keepalive se cancela en CUALQUIER salida (fin normal, fallo
            # de etapa 1/2, excepción de la corrida o cancelación externa) —
            # junto al single-flight de _busy, para no dejar tareas huérfanas
            # de keepalive viviendo más allá de la corrida.
            await _cancel_keepalive()
            if self._busy == run_id:
                self._busy = None

    # ──────────────────────────────── Stage 3 ──
    async def _flow_call(self, run: dict, tool: str, arguments: dict,
                         timeout: float | None = None) -> str:
        res = await self.manager.execute(
            "google-flow", tool, arguments, timeout=timeout)
        return res.get("text") or ""

    async def _ensure_reference(self, run: dict) -> str:
        """Asset Flow @{personaje} compartido por TODAS las escenas (§1.3):
        usa FLOW_REF_IMAGE_PATH si existe; si no, genera un ancla con el
        contexto del notebook. Se sube UNA vez por corrida."""
        ref_name = str(_cfg("FLOW_REF_ASSET_NAME", "personaje") or "personaje")
        if run.get("reference_asset"):
            return run["reference_asset"]
        rd = self._run_dir(run["run_id"])
        ref_path = str(_cfg("FLOW_REF_IMAGE_PATH", "") or "").strip()
        if ref_path and Path(ref_path).is_file():
            local = ref_path
        else:
            ctx = ""
            try:
                ctx = (rd / "context.md").read_text(encoding="utf-8")[:500]
            except OSError:
                pass
            prompt = ("Personaje principal CONSISTENTE para una serie de videos, "
                      "retrato completo, fondo neutro, iluminación uniforme. "
                      + (ctx[:400] if ctx else ""))
            t0 = time.time()   # BH1: respaldo por fecha posterior a la llamada
            text = await self._flow_call(run, "flow_generate_image", {
                "prompt": prompt, "aspect": "1:1", "count": 1,
                "model": str(_cfg("FLOW_MCP_MODEL", "2") or "2"),
                "outDir": str(rd)})
            local = _last_path(text) or _recent_media_in_dir(rd, t0)
            if not local:
                raise mcpm.MCPManagerError(
                    "flow_generate_image no devolvió ruta del ancla de personaje",
                    "TOOL_ERROR")
        await self._flow_call(run, "flow_upload_file",
                              {"filePath": local, "name": ref_name,
                               "replace": False})
        run["reference_asset"] = ref_name
        self._save(run)
        return ref_name

    async def _list_assets(self, run: dict) -> list[tuple[str, str | None]] | None:
        """flow_list_assets parseado → [(nombre, id|None), …] (BJ2: el tool
        real trae "- <name> [id:<mediaId>]"). None si el listado FALLA (el
        caller trata ese caso como no confirmable → regenerar imagen, sin
        adivinar); [] si Flow no tiene assets."""
        try:
            res = await self.manager.execute(
                "google-flow", "flow_list_assets", {}, timeout=30.0)
            if not res.get("ok"):
                log.warning("[pipeline %s] flow_list_assets respondió ok=False",
                            run.get("run_id"))
                return None
            return _parse_asset_listing(res.get("text") or "")
        except (mcpm.MCPManagerError, RuntimeError, OSError, TimeoutError,
                asyncio.TimeoutError) as e:
            log.warning("[pipeline %s] flow_list_assets falló: %s",
                        run.get("run_id"), e)
            return None

    async def _stage3(self, run: dict, only_scene_ids: set[str] | None = None) -> None:
        """Despacho por escena. Una escena que falla NO aborta la corrida:
        se registra scene_id + detalle y se continúa (§2 del mandato).
        BJ4: el startFrame se pasa como "id:<mediaId>" — se parsea la línea
        "Asset: <name> [id:<mediaId>]" de la salida de flow_generate_image
        (_parse_generated_asset); si no viene la línea, respaldo de subida
        con nombre explícito f"{run_id}-{scene_id}" (copia reducida). Se
        guardan nombre E id del start-frame en la escena: en retry, si la
        escena ya tiene start-frame y el asset sigue en Flow (por id o
        nombre), NO se regenera la imagen: solo el video."""
        # gate barato: Flow debe seguir conectado (retry incluido)
        pre = await self.manager.test_pipeline("google-flow")
        if not pre.get("ok"):
            detail = (f"Google Flow perdió conexión/sesión: state={pre.get('state')} "
                      f"auth={pre.get('auth')}")
            for s in run["scenes"]:
                if s["status"] in ("pending", "dispatched") and (
                        not only_scene_ids or s["scene_id"] in only_scene_ids):
                    s["status"], s["detail"] = "failed", detail[:200]
                    if s["scene_id"] not in run["failed_scene_ids"]:
                        run["failed_scene_ids"].append(s["scene_id"])
            raise PipelineError(detail, "FLOW_NOT_CONNECTED")

        # D2: Calentamiento previo a Stage 3: llamada real a flow_list_assets (hasta 2 intentos)
        # BK1: timeout = FLOW_CDP_CONNECT_TIMEOUT_MS/1000 + 30 (150 s por defecto):
        # el connectOverCDP en frío puede tardar hasta 120 s y el calentamiento
        # es la PRIMERA llamada CDP de la corrida.
        warm_ok = False
        last_warm_err = ""
        warm_timeout = _flow_warm_timeout()
        for attempt in range(1, 3):
            try:
                res = await self.manager.execute(
                    "google-flow", "flow_list_assets", {}, timeout=warm_timeout)
                if res.get("ok"):
                    warm_ok = True
                    break
            except (mcpm.MCPManagerError, RuntimeError, OSError, TimeoutError, asyncio.TimeoutError) as e:
                last_warm_err = str(e)
                log.warning("[pipeline %s] Calentamiento Flow CDP intento %d falló: %s",
                            run.get("run_id"), attempt, e)
        if not warm_ok:
            detail = f"Flow CDP no responde tras 2 intentos de calentamiento (FLOW_CDP_SLOW): {last_warm_err[:200]}"
            for s in run["scenes"]:
                if s["status"] in ("pending", "dispatched") and (
                        not only_scene_ids or s["scene_id"] in only_scene_ids):
                    s["status"], s["detail"] = "failed", detail[:200]
                    if s["scene_id"] not in run["failed_scene_ids"]:
                        run["failed_scene_ids"].append(s["scene_id"])
            raise PipelineError(detail, "FLOW_CDP_SLOW")
        ref = await self._ensure_reference(run)
        aspect = "9:16" if run["format"] == "short" else "16:9"
        model = str(_cfg("FLOW_MCP_MODEL", "2") or "2")
        rd = self._run_dir(run["run_id"])
        if only_scene_ids:
            targets = [s for s in run["scenes"] if s["scene_id"] in only_scene_ids]
        else:
            targets = [s for s in run["scenes"] if s["status"] == "pending"]
        total = max(1, len(run["scenes"]))
        for s in targets:
            s["attempts"] += 1
            s["status"], s["detail"] = "dispatched", ""
            run["dispatched"] += 1
            run["progress_pct"] = min(95, 50 + int(45 * run["dispatched"] / total))
            self._save(run)
            try:
                # 1) start-frame de la escena con el personaje de referencia @{ref}
                #    BJ4: Flow nombra sus assets por el CONTENIDO del prompt — el
                #    stem del archivo local NO es el nombre del asset. Se usa el
                #    "id:<mediaId>" de la línea "Asset:" (inequívoco aunque Flow
                #    repita nombres); sin línea Asset: → subida de respaldo con
                #    nombre explícito único.
                start_name = str(s.get("start_frame_asset") or "")
                start_id = str(s.get("start_frame_asset_id") or "")
                if start_name or start_id:
                    # retry: si Flow aún lista el asset (por id, o por nombre
                    # para estados BI1 sin id), NO regenerar la imagen: solo
                    # el video (ahorra créditos).
                    listing = await self._list_assets(run)
                    if listing is not None and _asset_in_listing(
                            start_name, start_id, listing):
                        log.info("[pipeline %s] escena %s reutiliza start-frame "
                                 "'%s'%s (no regenera imagen)",
                                 run["run_id"], s["scene_id"], start_name,
                                 f" [id:{start_id}]" if start_id else "")
                    else:
                        if listing is None:
                            log.warning("[pipeline %s] escena %s: listado Flow "
                                        "indisponible — no se puede confirmar el "
                                        "start-frame '%s'; se regenera la imagen",
                                        run["run_id"], s["scene_id"], start_name)
                        else:
                            log.warning("[pipeline %s] escena %s: el start-frame "
                                        "'%s' ya NO está en Flow — se regenera "
                                        "la imagen", run["run_id"],
                                        s["scene_id"], start_name)
                        start_name = start_id = ""
                        s["start_frame_asset"] = ""
                        s["start_frame_asset_id"] = ""
                if not start_name and not start_id:
                    img_prompt = (f"Image 1 -> Personaje: @{{{ref}}}\n"
                                  f"{s['image_prompt'] or s['title']}").strip()
                    t0 = time.time()   # BH1: respaldo por fecha posterior a la llamada
                    text = await self._flow_call(run, "flow_generate_image", {
                        "prompt": img_prompt, "aspect": aspect, "count": 1,
                        "model": model, "outDir": str(rd)})
                    frame = _last_path(text) or _recent_media_in_dir(rd, t0)
                    if not frame:
                        raise mcpm.MCPManagerError(
                            "flow_generate_image no devolvió ruta del start-frame",
                            "TOOL_ERROR")
                    # BJ4: el tool (BJ2) emite "Asset: <name> [id:<mediaId>]"
                    # ANTES de la ruta → el video va POR ID, inequívoco.
                    nombre_asset, mid_asset = _parse_generated_asset(text)
                    if mid_asset:
                        start_name, start_id = nombre_asset, mid_asset
                    else:
                        # Sin línea "Asset:" (tool antiguo/respaldo) → subir la
                        # copia local (previsualización reducida) con nombre
                        # explícito único. Si la subida también falla → error
                        # claro, sin adivinar.
                        start_name = f"{run['run_id']}-{s['scene_id']}"
                        start_id = ""
                        log.warning(
                            "[pipeline %s] escena %s: sin línea 'Asset:' en la "
                            "salida de flow_generate_image — se sube la copia "
                            "local reducida como '%s'", run["run_id"],
                            s["scene_id"], start_name)
                        try:
                            await self._flow_call(run, "flow_upload_file",
                                                  {"filePath": frame,
                                                   "name": start_name,
                                                   "replace": False})
                        except mcpm.MCPManagerError as e:
                            raise mcpm.MCPManagerError(
                                f"sin línea 'Asset:' en flow_generate_image y "
                                f"la subida de respaldo '{start_name}' falló: {e}",
                                e.code) from e
                    s["start_frame_asset"] = start_name
                    s["start_frame_asset_id"] = start_id
                # 2) video con movimiento coherente + narración de la escena
                start_frame = f"id:{start_id}" if start_id else start_name
                motion = (f"{s['image_prompt']}\nMovimiento de cámara y acción, "
                          f"plano continuo coherente: {s['narration'][:300]}").strip()
                out_file = str(rd / f"scene_{s['scene_id']}.mp4")
                t0 = time.time()   # BH1: respaldo por fecha posterior a la llamada
                text = await self._flow_call(run, "flow_generate_video", {
                    "prompt": motion, "startFrame": start_frame,
                    "aspect": aspect, "outDir": str(rd), "outFile": out_file},
                    timeout=float(_cfg("FLOW_MCP_TIMEOUT", 120.0)))
                video = _last_path(text) or _recent_media_in_dir(rd, t0) or out_file
                # [A13 · P1.6] VERIFICAR en disco ANTES de marcar done: el tool
                # puede responder 200 con texto de éxito sin haber dejado el
                # MP4 (descarga truncada, disco lleno, rename fallido). Antes
                # la escena quedaba done con video_file inexistente y el
                # ensamblado moría después con el run en verde.
                if not Path(video).is_file():
                    raise mcpm.MCPManagerError(
                        f"flow_generate_video respondió pero el archivo no "
                        f"existe en disco: {video}", "TOOL_ERROR")
                s["status"], s["video_file"] = "done", video
                run["done_count"] += 1
                log.info("[pipeline %s] escena %s OK → %s",
                         run["run_id"], s["scene_id"], video)
            except mcpm.MCPManagerError as e:
                s["status"] = "failed"
                s["detail"] = f"[{e.code}] {str(e)[:200]}"
                if s["scene_id"] not in run["failed_scene_ids"]:
                    run["failed_scene_ids"].append(s["scene_id"])
                log.warning("[pipeline %s] escena %s FALLÓ: %s",
                            run["run_id"], s["scene_id"], s["detail"])
            finally:
                self._save(run)


# Singleton del backend (los endpoints en main.py lo consumen)
orchestrator = PipelineOrchestrator()

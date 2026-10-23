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
_PATH_LINE_RE = re.compile(r"([A-Za-z]:\\[^\s]+|/[^\s]+)\s*$")

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
    return getattr(config, name, default)


def _last_path(text: str) -> str:
    """Extrae la última ruta de archivo de la respuesta textual de Flow.
    Los servidores GoogleFlowMCP responden con '…:\\n<ruta local>'."""
    for line in reversed((text or "").strip().splitlines()):
        line = line.strip().lstrip("- ").strip()
        m = _PATH_LINE_RE.search(line)
        if m:
            return m.group(1).strip()
    return ""


def _asset_name_from_file(path_text: str) -> str:
    """Nombre de asset Flow para un archivo local generado (stem saneado).
    flow.js nombra los archivos sin caracteres raros; defensa extra igualmente."""
    stem = Path(path_text).stem.strip()
    stem = re.sub(r"[^A-Za-z0-9_\-]", "_", stem)[:64] or "frame"
    return stem


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
        return run

    # ──────────────────────────────── API pública ──
    def create_run(self, idea: str, notebook_id: str | None = None,
                   fmt: str = "short", style: str = "auto") -> dict:
        idea = (idea or "").strip()
        if not idea:
            raise PipelineError("idea requerida para el pipeline", "IDEA_REQUIRED")
        if self._busy:
            raise PipelineError(
                f"ya hay un pipeline en marcha ({self._busy}) — espera su fin "
                f"o usa retry-scenes", "PIPELINE_BUSY")
        now = time.strftime("%Y%m%d_%H%M%S")
        run_id = f"run_{now}_{uuid.uuid4().hex[:6]}"
        run = {
            "run_id": run_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "idea": idea[:500],
            "notebook_id": (notebook_id or "").strip(),
            "format": fmt if fmt in ("short", "long") else "short",
            "style": (style or "auto").strip()[:40] or "auto",
            "stage": ST_QUEUED,
            "error_code": "",
            "error_detail": "",
            "steps": [{"stage": s, "label": lbl, "state": "pending", "detail": ""}
                      for s, lbl in _STEPS],
            "progress_pct": 0,
            "context_chars": 0,
            "blueprint_title": "",
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
                           scene_ids: list[str] | None = None) -> dict:
        """Re-despacha SOLO escenas fallidas de Stage 3 (§2 del mandato).
        Nunca repite Stage 1/2: usa el blueprint persistido."""
        run = self._load(run_id)
        # ST_QUEUED = creada y nunca lanzada: no está "en marcha"
        if run["stage"] in _STAGES_ACTIVE and run["stage"] != ST_QUEUED:
            raise PipelineError("el pipeline sigue en marcha", "PIPELINE_BUSY")
        if not run["scenes"]:
            raise PipelineError(
                "no hay blueprint persistido — relanza el pipeline completo",
                "RETRY_NO_BLUEPRINT")
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

    async def _run(self, run_id: str) -> None:
        run = self._load(run_id)
        try:
            # ── pre-flight gatekeeper (§2): aborta ANTES de gastar tokens ──
            self._set_step(run, ST_PREFLIGHT, "running")
            run["progress_pct"] = 5
            pre_n = await self.manager.test_pipeline(
                "notebooklm", notebook_id=run["notebook_id"] or None)
            pre_f = await self.manager.test_pipeline("google-flow")
            if not pre_n.get("ok"):
                code = ("PRE_FLIGHT_AUTH" if pre_n.get("state") == mcpm.ST_AUTH_REQUIRED
                        else "PRE_FLIGHT_NOTEBOOKLM")
                self._fail(run, code,
                           f"NotebookLM no listo: state={pre_n.get('state')} "
                           f"auth={pre_n.get('auth')} {pre_n.get('detail') or pre_n.get('auth_detail') or ''}")
                return
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
            if not nid:
                nid = str(_cfg("NOTEBOOKLM_NOTEBOOK_ID", "") or "").strip()
                if nid:
                    run["notebook_id"] = nid          # env → estado (visibilidad total)
                    self._save(run)
            pre_detail = "notebooklm ✅ · google-flow ✅"
            if not nid:
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
                               "Usa «📋 Listar mis Notebooks» del panel MCP para "
                               "elegir uno con 1 click, pégalo en «Notebook ID "
                               "activo», o fija NOTEBOOKLM_NOTEBOOK_ID en backend/.env.")
                    return
            self._set_step(run, ST_PREFLIGHT, "ok", pre_detail)

            # ── Stage 1: contexto de NotebookLM (solo-lectura) ──
            self._set_step(run, ST_STAGE1, "running")
            run["progress_pct"] = 25
            tool = str(_cfg("NOTEBOOKLM_CONTEXT_TOOL", "query_notebook") or "").strip()
            query = str(_cfg(
                "NOTEBOOKLM_CONTEXT_QUERY",
                "Extrae del notebook la biblia de investigación para producir un "
                "video: puntos clave y datos verificables, arco narrativo sugerido, "
                "y una descripción física CONSISTENTE del personaje principal "
                "(look, ropa, rasgos) reutilizable en todas las escenas.") or "").strip()
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
                code = ("PRE_FLIGHT_MISSING_NOTEBOOK_ID"
                        if e.code == "MISSING_NOTEBOOK_ID" else "CONTEXT_EXTRACTION_FAILED")
                self._fail(run, code, f"tool '{tool}': [{e.code}] {e}")
                return
            context = (res.get("text") or "").strip()
            if not context:
                self._fail(run, "CONTEXT_EMPTY",
                           f"la tool '{tool}' devolvió texto vacío — revisa el "
                           f"notebookId y NOTEBOOKLM_CONTEXT_TOOL")
                return
            rd = self._run_dir(run["run_id"])
            rd.mkdir(parents=True, exist_ok=True)
            (rd / "context.md").write_text(context, encoding="utf-8")
            run["context_chars"] = len(context)
            self._set_step(run, ST_STAGE1, "ok",
                           f"{len(context)} caracteres extraídos del notebook "
                           f"«{run['notebook_id'] or '(env fallback)'}»")

            # ── Stage 2: blueprint con el generador EXISTENTE (sin tocarlo) ──
            self._set_step(run, ST_STAGE2, "running")
            run["progress_pct"] = 45
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
                    "detail": "",
                })
            if not scenes:
                self._fail(run, "BLUEPRINT_EMPTY",
                           "el generador no devolvió escenas — revisa GEMINI_API_KEY "
                           "o el contenido del notebook")
                return
            blueprint = {"title": res2.get("title") or run["idea"][:60],
                         "hook": res2.get("hook", ""), "cta": res2.get("cta", ""),
                         "engine": res2.get("engine", ""),
                         "notebook_id": run["notebook_id"],
                         "format": run["format"], "style": run["style"],
                         "context_source": "notebooklm", "scenes": scenes}
            (rd / "blueprint.json").write_text(
                json.dumps(blueprint, ensure_ascii=False, indent=1),
                encoding="utf-8")
            run["scenes"] = json.loads(json.dumps(blueprint["scenes"]))
            run["blueprint_title"] = blueprint["title"]
            self._set_step(run, ST_STAGE2, "ok",
                           f"«{blueprint['title']}» — {len(scenes)} escenas "
                           f"(motor: {blueprint['engine']})")

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
            text = await self._flow_call(run, "flow_generate_image", {
                "prompt": prompt, "aspect": "1:1", "count": 1,
                "model": str(_cfg("FLOW_MCP_MODEL", "2") or "2"),
                "outDir": str(rd)})
            local = _last_path(text)
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

    async def _stage3(self, run: dict, only_scene_ids: set[str] | None = None) -> None:
        """Despacho por escena. Una escena que falla NO aborta la corrida:
        se registra scene_id + detalle y se continúa (§2 del mandato)."""
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
                img_prompt = (f"Image 1 -> Personaje: @{{{ref}}}\n"
                              f"{s['image_prompt'] or s['title']}").strip()
                text = await self._flow_call(run, "flow_generate_image", {
                    "prompt": img_prompt, "aspect": aspect, "count": 1,
                    "model": model, "outDir": str(rd)})
                frame = _last_path(text)
                if not frame:
                    raise mcpm.MCPManagerError(
                        "flow_generate_image no devolvió ruta del start-frame",
                        "TOOL_ERROR")
                start_frame = _asset_name_from_file(frame)
                # 2) video con movimiento coherente + narración de la escena
                motion = (f"{s['image_prompt']}\nMovimiento de cámara y acción, "
                          f"plano continuo coherente: {s['narration'][:300]}").strip()
                out_file = str(rd / f"scene_{s['scene_id']}.mp4")
                text = await self._flow_call(run, "flow_generate_video", {
                    "prompt": motion, "startFrame": start_frame,
                    "aspect": aspect, "outDir": str(rd), "outFile": out_file},
                    timeout=float(_cfg("FLOW_MCP_TIMEOUT", 120.0)))
                video = _last_path(text) or out_file
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

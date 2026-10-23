"""
YOUTUBE AUTOMATION v2.23 — Asset Harvester (INT-024 · Stage 3.5)
Consolida los assets que Stage 3 dejó dispersos (rutas absolutas de Flow,
nombres arbitrarios) en una estructura DETERMINISTA por corrida:

  <run_dir>/                        (≡ output/{run_id}/ del mandato)
  ├── state.json                    estado del orquestador (INT-023)
  ├── scenes/scene_{idx:03d}.mp4    visual normalizado de cada escena
  │         scene_{idx:03d}.png     …o imagen con fallback Ken Burns
  ├── narration/scene_{idx:03d}.wav locución por escena (si existe)
  └── manifest.json                 contrato estricto del ensamblador

manifest.json (esquema validado por validate_manifest):
  run_id, notebook_id, character_ref, format, aspect, fps, resolution,
  created_at, y scenes[] = {scene_id, idx, asset_path, asset_type
  (video|image|placeholder), narration_audio_path, duration_sec,
  subtitle_text, status (ready|placeholder|failed), source}.

Hermeticidad: cero red — solo shutil/ffprobe opcional. Si ffprobe no está,
la duración se ESTIMA por caracteres de narración (RENDER_EST_CPS), así la
batería corre en cualquier sandbox sin binarios externos.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import config

log = logging.getLogger("asset_harvester")

MANIFEST_NAME = "manifest.json"
SCENES_DIRNAME = "scenes"
NARRATION_DIRNAME = "narration"

_ASPECT = {"short": "9:16", "long": "16:9"}
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


class HarvesterError(Exception):
    """Error operacional del harvester con código estable para la UI."""

    def __init__(self, msg: str, code: str = "HARVEST_ERROR"):
        super().__init__(msg)
        self.code = code


def _cfg(name: str, default: Any) -> Any:
    return getattr(config, name, default)


# ─────────────────────────────── duraciones ──────────────────────────────
def estimate_duration(text: str) -> float:
    """Duración estimada de la locución (seg) por caracteres/segundo.
    Determinista y hermética: es el fallback cuando no hay audio ni ffprobe."""
    chars = len((text or "").strip())
    if chars <= 0:
        return float(_cfg("RENDER_MIN_SCENE_SEC", 2.0))
    cps = float(_cfg("RENDER_EST_CPS", 14.5)) or 14.5
    return max(float(_cfg("RENDER_MIN_SCENE_SEC", 2.0)), round(chars / cps, 2))


def probe_duration(path: Path) -> float | None:
    """Duración real vía ffprobe (si el binario existe y el medio es legible).
    Nunca lanza: devuelve None y el llamante cae a la estimación."""
    if not shutil.which("ffprobe") or not path or not Path(path).is_file():
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30)
        val = float(out.stdout.strip().splitlines()[0])
        return val if val > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return None


# ─────────────────────────────── harvesting ──────────────────────────────
def _copy(src: Path, dst: Path) -> None:
    """Copia robusta e IDEMPOTENTE (el re-harvest sobre el mismo run_dir no
    debe fallar): mismo inodo → no-op; dst existente → reemplazo; hardlink si
    es posible (mismo FS, instantáneo), fallback shutil.copy2. Nunca mueve:
    el original queda intacto para retry."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if dst.exists() and os.path.samefile(src, dst):
            return  # ya consolidado en un harvest anterior
    except OSError:
        pass  # dst no existe o comparación imposible → continuar
    if dst.exists():
        try:
            dst.unlink()
        except OSError:
            pass
    try:
        os.link(src, dst)
    except OSError:
        try:
            shutil.copy2(src, dst)
        except shutil.SameFileError:
            pass  # misma ruta lógica: nada que copiar


def _resolve_source(video_file: str, run_dir: Path) -> Path | None:
    """Resuelve la ruta que Flow reportó: absoluta, relativa al run_dir,
    o solo el nombre de archivo dentro del run_dir (flow.js escribe ahí)."""
    vf = (video_file or "").strip()
    if not vf:
        return None
    p = Path(vf)
    if p.is_file():
        return p
    alt = run_dir / p.name
    if alt.is_file():
        return alt
    alt2 = run_dir / p
    if alt2.is_file():
        return alt2
    return None


def _find_image(run_dir: Path, scene_id: str) -> Path | None:
    """Imagen candidata de la escena (start-frame generado en Stage 3) cuando
    el video no llegó: scene_<scene_id>.* en el run_dir."""
    for ext in _IMAGE_EXTS:
        cand = run_dir / f"scene_{scene_id}{ext}"
        if cand.is_file():
            return cand
    # frame derivado: flow.js a veces nombra <outFile stems>.png
    for ext in _IMAGE_EXTS:
        for cand in sorted(run_dir.glob(f"*{scene_id}*{ext}")):
            if cand.is_file():
                return cand
    return None


def harvest_scenes(run: dict, run_dir: Path,
                   placeholders_for_failed: bool = False) -> list[dict]:
    """Stage 3.5: consolida cada escena del estado del orquestador en su
    ruta determinista y devuelve las entradas del manifest.
    placeholders_for_failed: escena failed → status 'placeholder' (el
    ensamblador genera un clip de color con su duración estimada) en vez de
    'failed' (bloqueante). Nunca tumba: escena problemática queda 'failed'
    y el resto se consolida igual."""
    scenes_dir = run_dir / SCENES_DIRNAME
    nar_dir = run_dir / NARRATION_DIRNAME
    scenes_dir.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for i, s in enumerate(run.get("scenes") or [], start=1):
        idx_name = f"scene_{i:03d}"
        dest_video = scenes_dir / f"{idx_name}.mp4"
        dest_image = scenes_dir / f"{idx_name}.png"
        entry = {
            "scene_id": s.get("scene_id") or f"s{i}",
            "idx": i,
            "asset_path": "",
            "asset_type": "placeholder",
            "narration_audio_path": "",
            "duration_sec": 0.0,
            "subtitle_text": (s.get("narration") or "").strip(),
            "status": "failed",
            "source": "",
        }
        status = s.get("status")
        if status == "done":
            src = _resolve_source(s.get("video_file") or "", run_dir)
            if src is not None and src.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv"):
                _copy(src, dest_video)
                entry.update(asset_path=f"{SCENES_DIRNAME}/{dest_video.name}",
                             asset_type="video", status="ready",
                             source=str(src))
            elif src is not None and src.suffix.lower() in _IMAGE_EXTS:
                _copy(src, dest_image)
                entry.update(asset_path=f"{SCENES_DIRNAME}/{dest_image.name}",
                             asset_type="image", status="ready",
                             source=str(src))
            else:
                img = _find_image(run_dir, entry["scene_id"])
                if img is not None:
                    _copy(img, dest_image)
                    entry.update(asset_path=f"{SCENES_DIRNAME}/{dest_image.name}",
                                 asset_type="image", status="ready",
                                 source=str(img))
                else:
                    entry["source"] = s.get("video_file") or ""
        # locución por escena (convención narration/scene_XXX.wav)
        nar = nar_dir / f"{idx_name}.wav"
        if nar.is_file():
            entry["narration_audio_path"] = f"{NARRATION_DIRNAME}/{nar.name}"
        # duración: audio real > visual real > estimada por texto
        dur: float | None = None
        if entry["narration_audio_path"]:
            dur = probe_duration(nar)
        if dur is None and entry["asset_type"] == "video":
            dur = probe_duration(dest_video)
        if dur is None:
            dur = estimate_duration(entry["subtitle_text"])
        entry["duration_sec"] = round(float(dur), 3)
        # placeholders (§3 del mandato: el testeo nunca se deadlocka)
        if entry["status"] != "ready":
            if placeholders_for_failed:
                # fallida → placeholder SIN condiciones: clip de color con
                # silencio de su duración (estimada), con o sin narración
                entry["status"] = "placeholder"
                entry["asset_type"] = "placeholder"
        out.append(entry)
    return out


# ─────────────────────────────── manifest ────────────────────────────────
def build_manifest(run: dict, run_dir: Path,
                   placeholders_for_failed: bool = False) -> dict:
    """Construye el manifest estricto de la corrida (no lo escribe)."""
    fmt = run.get("format") if run.get("format") in ("short", "long") else "short"
    w, h = ((int(_cfg("SHORT_W", 1080)), int(_cfg("SHORT_H", 1920)))
            if fmt == "short" else (int(_cfg("LONG_W", 1920)), int(_cfg("LONG_H", 1080))))
    entries = harvest_scenes(run, run_dir, placeholders_for_failed)
    return {
        "schema": "albra.manifest/1",
        "run_id": run.get("run_id") or run_dir.name,
        "notebook_id": run.get("notebook_id") or "",
        "character_ref": run.get("reference_asset")
                         or str(_cfg("FLOW_REF_ASSET_NAME", "personaje") or "personaje"),
        "format": fmt,
        "aspect": _ASPECT[fmt],
        "fps": int(_cfg("FPS", 30)),
        "resolution": f"{w}x{h}",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "scenes": entries,
    }


def validate_manifest(manifest: dict) -> list[str]:
    """Validación estricta del esquema. Devuelve lista de errores (vacía = OK).
    El ensamblador rechaza un manifest inválido ANTES de invocar ffmpeg."""
    errs: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest no es un objeto"]
    for key in ("run_id", "notebook_id", "character_ref", "scenes"):
        if key not in manifest:
            errs.append(f"falta clave obligatoria: {key}")
    scenes = manifest.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        errs.append("scenes debe ser una lista no vacía")
        return errs
    seen_ids: set[str] = set()
    total = 0.0
    for i, sc in enumerate(scenes, start=1):
        sid = str(sc.get("scene_id") or "")
        if not sid:
            errs.append(f"scenes[{i}]: scene_id vacío")
        elif sid in seen_ids:
            errs.append(f"scenes[{i}]: scene_id duplicado '{sid}'")
        seen_ids.add(sid)
        for key in ("asset_path", "narration_audio_path", "duration_sec",
                    "subtitle_text", "status", "asset_type"):
            if key not in sc:
                errs.append(f"scenes[{i}] ({sid}): falta '{key}'")
        dur = sc.get("duration_sec")
        if not isinstance(dur, (int, float)) or dur <= 0:
            errs.append(f"scenes[{i}] ({sid}): duration_sec inválido ({dur!r})")
        else:
            total += float(dur)
        st = sc.get("status")
        if st not in ("ready", "placeholder", "failed"):
            errs.append(f"scenes[{i}] ({sid}): status inválido '{st}'")
        at = sc.get("asset_type")
        if at not in ("video", "image", "placeholder"):
            errs.append(f"scenes[{i}] ({sid}): asset_type inválido '{at}'")
        if st == "ready" and not sc.get("asset_path"):
            errs.append(f"scenes[{i}] ({sid}): status ready sin asset_path")
    if total <= 0:
        errs.append("duración total del video <= 0")
    return errs


def write_manifest(run_dir: Path, manifest: dict) -> Path:
    """Escritura atómica del manifest (tmp + os.replace, convención del repo)."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = run_dir / (MANIFEST_NAME + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    dst = run_dir / MANIFEST_NAME
    os.replace(tmp, dst)
    return dst


def load_manifest(run_dir: Path) -> dict:
    """Carga y valida el manifest; lanza HarvesterError con código estable."""
    f = Path(run_dir) / MANIFEST_NAME
    try:
        manifest = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HarvesterError(
            f"manifest.json ausente o corrupto en {f.parent.name} — corre "
            f"Stage 3.5 (harvest) primero", "HARVEST_NO_MANIFEST") from e
    errs = validate_manifest(manifest)
    if errs:
        raise HarvesterError(
            "manifest inválido: " + "; ".join(errs[:5]), "HARVEST_INVALID_MANIFEST")
    return manifest


def harvest_run(run: dict, run_dir: Path,
                placeholders_for_failed: bool = False) -> dict:
    """API de alto nivel (Stage 3.5 completo): harvest + manifest + validación.
    Devuelve (manifest, path). Lanza HarvesterError si el resultado es
    inservible (p.ej. 0 escenas)."""
    manifest = build_manifest(run, run_dir, placeholders_for_failed)
    errs = validate_manifest(manifest)
    if errs:
        raise HarvesterError(
            "el harvest produjo un manifest inservible: " + "; ".join(errs[:5]),
            "HARVEST_INVALID_MANIFEST")
    path = write_manifest(run_dir, manifest)
    log.info("[harvest %s] manifest OK — %d escena(s), %.2fs totales",
             manifest["run_id"], len(manifest["scenes"]),
             sum(s["duration_sec"] for s in manifest["scenes"]))
    return manifest, path

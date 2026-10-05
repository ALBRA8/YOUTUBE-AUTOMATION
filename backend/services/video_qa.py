"""
Video QA — control de calidad REAL de los assets de Flow y del render final.

Responde, con hechos medidos (no suposiciones), tres preguntas por proyecto:

  1. ¿Las imágenes de Flow son imágenes válidas y con qué dimensiones?
     (PIL: formato real, ancho×alto, modo de color — detecta HTML de error
     guardado como imagen, imágenes truncadas y miniaturas degeneradas).
  2. ¿Los clips de video de Flow son MP4 sanos y con qué propiedades?
     (ffprobe JSON: duración, resolución, fps, códec, pista de audio —
     detecta WebM disfrazado de .mp4, clips truncados y videos sin stream).
  3. ¿El render final existe y cumple lo mínimo para publicar?
     (existe, es MP4 ffprobe-válido, duración razonable, tiene audio).

Cada hallazgo sale como "flag" con severidad: error (bloquea publicación),
warn (revisar) u ok (informativo). qa_project() nunca lanza por assets
malos: reporta. Solo lanza LookupError si el proyecto no existe.

Uso desde la API:  GET /api/video_qa/{pid}
Uso desde MCP:     tool video_qa(project_id=...)
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from config import OUTPUT_DIR
from database import get_project, get_scenes

MIN_CLIP_S = 0.3        # igual que flow_jobs / flow_import
MIN_FINAL_S = 3.0       # un render final de menos de 3s es sospechoso
MIN_DIM = 240           # px; por debajo es basura para YouTube Shorts


def _ffprobe_json(path: Path) -> dict | None:
    """ffprobe con streams+format en JSON. None si el archivo no se puede
    abrir/leer (no lanza: QA reporta, no revienta)."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_streams", "-show_format", str(path)],
            capture_output=True, timeout=60)
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def _fps_of(stream: dict) -> float:
    """avg_frame_rate '30000/1001' → 29.97 (0 si no parsea)."""
    raw = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "")
    try:
        num, _, den = raw.partition("/")
        d = float(den) if den else 1.0
        return float(num) / d if d else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def qa_image(path: str | Path) -> dict:
    """QA de UNA imagen con PIL (formato real, dimensiones, modo)."""
    p = Path(path)
    info: dict = {"path": str(p), "exists": p.exists(), "flags": []}
    if not p.exists():
        info["flags"].append({"sev": "error", "msg": "imagen no existe en disco"})
        return info
    try:
        from PIL import Image
        with Image.open(p) as im:
            info["format"] = im.format
            info["width"], info["height"] = im.size
            info["mode"] = im.mode
            im.verify()
    except Exception as exc:  # noqa: BLE001
        info["flags"].append({"sev": "error",
                              "msg": f"imagen inválida/corrupta: {exc}"})
        return info
    if (info.get("format") or "").upper() not in ("PNG", "JPEG", "WEBP"):
        info["flags"].append({"sev": "error",
                              "msg": f"formato inesperado: {info.get('format')}"})
    w, h = int(info.get("width") or 0), int(info.get("height") or 0)
    if w < MIN_DIM or h < MIN_DIM:
        info["flags"].append({"sev": "error",
                              "msg": f"dimensión degenerada {w}x{h} (<{MIN_DIM}px)"})
    if not info["flags"]:
        info["flags"].append({"sev": "ok",
                              "msg": f"imagen válida {w}x{h} {info.get('format')}"})
    return info


def qa_video(path: str | Path, *, final: bool = False) -> dict:
    """QA de UN video con ffprobe (duración, resolución, fps, códecs, audio).
    `final=True` aplica las reglas más duras del render final."""
    p = Path(path)
    info: dict = {"path": str(p), "exists": p.exists(), "final": final,
                  "flags": []}
    if not p.exists():
        info["flags"].append({"sev": "error", "msg": "video no existe en disco"})
        return info
    probe = _ffprobe_json(p)
    if not probe or not probe.get("streams"):
        info["flags"].append({"sev": "error",
                              "msg": "ffprobe no puede leerlo (¿no es MP4? "
                                     "¿WebM renombrado? ¿archivo truncado?)"})
        return info
    streams = probe["streams"]
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        dur = float((probe.get("format") or {}).get("duration")
                    or (v or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        dur = 0.0
    info.update({"duration_s": round(dur, 3),
                 "has_video": v is not None, "has_audio": a is not None})
    if v:
        info.update({"width": v.get("width"), "height": v.get("height"),
                     "fps": round(_fps_of(v), 3),
                     "vcodec": v.get("codec_name")})
    min_dur = MIN_FINAL_S if final else MIN_CLIP_S
    if dur < min_dur:
        info["flags"].append({"sev": "error",
                              "msg": f"duración {dur:.2f}s < mínimo {min_dur}s"})
    if v is None:
        info["flags"].append({"sev": "error", "msg": "sin stream de video"})
    else:
        if (v.get("codec_name") or "") not in ("h264", "hevc", "vp9", "av1"):
            info["flags"].append({"sev": "warn",
                                  "msg": f"códec de video poco común: "
                                         f"{v.get('codec_name')}"})
        w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        if w and (w < MIN_DIM or h < MIN_DIM):
            info["flags"].append({"sev": "error",
                                  "msg": f"resolución degenerada {w}x{h}"})
    if a is None:
        if final:
            info["flags"].append({"sev": "error",
                                  "msg": "render final sin pista de audio"})
        else:
            info["flags"].append({"sev": "ok",
                                  "msg": "clip de Flow sin audio (normal)"})
    else:
        info["acodec"] = a.get("codec_name")
    if not any(f["sev"] == "error" for f in info["flags"]):
        info["flags"].append({"sev": "ok",
                              "msg": f"video válido {dur:.1f}s "
                                     f"{info.get('width')}x{info.get('height')}"
                                     f"{' +audio' if a else ''}"})
    return info


def _worst(flags: list[dict]) -> str:
    if any(f["sev"] == "error" for f in flags):
        return "error"
    if any(f["sev"] == "warn" for f in flags):
        return "warn"
    return "ok"


def qa_project(pid: str) -> dict:
    """QA completo del proyecto: escenas (imagen+clip Flow por escena) y
    render final (project.video_url si ya existe). Nunca lanza por assets
    malos — solo LookupError si el proyecto no existe."""
    project = get_project(pid)
    if not project:
        raise LookupError(f"proyecto {pid} no existe")
    scenes = get_scenes(pid)

    per_scene: list[dict] = []
    n_img_err = n_vid_err = 0
    for sc in scenes:
        no = int(sc["idx"]) + 1
        entry: dict = {"scene": no}
        # Prioridad: imagen YA mapeada (proyecto renderizado); si no existe,
        # el asset crudo de Flow (proyecto en curso con el bridge activo).
        mapped = sc.get("image_path")
        flow_img = None
        if not mapped:
            cands = sorted((OUTPUT_DIR / pid / "flow").glob(
                f"Escena_{no:02d}_flow.*"))
            flow_img = str(cands[0]) if cands else None
        target = mapped or flow_img
        if target:
            entry["image"] = qa_image(target)
            entry["image"]["source"] = "mapped" if mapped else "flow"
            if _worst(entry["image"]["flags"]) == "error":
                n_img_err += 1
        else:
            entry["image"] = {"path": None, "exists": False, "source": None,
                              "flags": [{"sev": "warn",
                                         "msg": "escena sin imagen (ni "
                                                "mapeada ni en flow/)"}]}
        flow_dir = OUTPUT_DIR / pid / "flow"
        clips = sorted(flow_dir.glob(f"Escena_{no:02d}_video_*.mp4"))
        if clips:
            entry["clips"] = [qa_video(c) for c in clips]
            n_vid_err += sum(1 for c in entry["clips"]
                             if _worst(c["flags"]) == "error")
        elif sc.get("video_prompt"):
            entry["clips"] = []
            entry["clip_flags"] = [{"sev": "warn",
                                    "msg": "escena con video_prompt pero sin "
                                           "clip en flow/ (pendiente o job "
                                           "en cola)"}]
        per_scene.append(entry)

    final_info = None
    video_url = (project or {}).get("video_url")
    if video_url and Path(str(video_url)).exists():
        final_info = qa_video(video_url, final=True)

    errors = n_img_err + n_vid_err
    if final_info and _worst(final_info["flags"]) == "error":
        errors += 1
    return {"ok": True, "project_id": pid,
            "status": "error" if errors else ("warn" if _has_warn(per_scene,
                                                              final_info)
                                              else "ok"),
            "scenes": per_scene, "final": final_info,
            "summary": {"scenes": len(scenes), "image_errors": n_img_err,
                        "clip_errors": n_vid_err,
                        "final_present": bool(final_info)}}


def _has_warn(per_scene: list[dict], final_info: dict | None) -> bool:
    for s in per_scene:
        for block in ([s.get("image")] if s.get("image") else []) \
                + (s.get("clips") or []):
            if _worst(block.get("flags", [])) == "warn":
                return True
        if any(f["sev"] == "warn" for f in s.get("clip_flags", [])):
            return True
    if final_info and _worst(final_info.get("flags", [])) == "warn":
        return True
    return False

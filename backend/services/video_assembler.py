"""
YOUTUBE AUTOMATION v2.23 — Video Assembler (INT-024 · Stage 4)
Ensamblaje determinista con FFmpeg del render final de una corrida:

  1. DURATION SYNC  — cada visual se recorta (trim), se repite (loop con
     -stream_loop) o recibe Ken Burns (zoompan sobre imagen estática) para
     calzar EXACTAMENTE con la duración de su segmento de narración.
  2. AUDIO MIXING   — las locuciones ya van embebidas por escena (apad a la
     duración exacta); la cama musical opcional se atenúa -20dB (ducking
     determinista) y se mezcla con amix(duration=first).
  3. CAPTIONS       — .srt por escena (ventanas acumuladas exactas); se
     QUEMA con el filtro subtitles (libass) o se muxea soft (mov_text).
  4. EXPORT         — output: <run_dir>/final_render.mp4
     H.264 (preset/CRF configurables) + AAC 160k, 1080p, 30 fps.

Tolerancia a fallos (mandato §2): si el binario ffmpeg NO existe, el modo
dry_run=True construye y devuelve TODA la cadena de comandos sin ejecutarla
(render_plan.json) — así la batería hermética y los sandboxes sin GPU/binario
nunca se deadlockean. Cada comando corre con timeout y su stderr se surfaced
con código estable (RENDER_CMD_FAILED / RENDER_TIMEOUT / RENDER_NO_FFMPEG).

NO bloquea el event loop: los endpoints lo invocan vía asyncio.to_thread
(vea pipeline_orchestrator.render_final). Aquí todo es sync puro.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

import config
from services.asset_harvester import (HarvesterError, load_manifest)

log = logging.getLogger("video_assembler")

FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"
FINAL_NAME = "final_render.mp4"
NORM_DIRNAME = "norm"
SRT_NAME = "final_captions.srt"
PLAN_NAME = "render_plan.json"

_COLOR_BG = "0x101418"          # fondo del placeholder (casi negro azulado)
_MIX_DB_FLOOR = -60.0           # clampa el ducking a algo audible-sane


class AssemblerError(Exception):
    """Error operacional del ensamblador con código estable para la UI."""

    def __init__(self, msg: str, code: str = "RENDER_ERROR"):
        super().__init__(msg)
        self.code = code


def _cfg(name: str, default: Any) -> Any:
    return getattr(config, name, default)


# ─────────────────────────── detección de binarios ───────────────────────
def ffmpeg_version() -> str | None:
    """Primera línea de `ffmpeg -version`, o None si el binario no responde."""
    if not shutil.which(FFMPEG_BIN):
        return None
    try:
        out = subprocess.run([FFMPEG_BIN, "-version"], capture_output=True,
                             text=True, timeout=15)
        line = (out.stdout or "").strip().splitlines()
        return line[0].strip() if line else None
    except (OSError, subprocess.SubprocessError):
        return None


_FILTER_CACHE: dict[str, bool] = {}


def has_filter(name: str) -> bool:
    """True si la build de ffmpeg soporta un filtro (p.ej. 'subtitles'/libass).
    Cacheado; en sandbox sin binario devuelve False (→ degrada a soft mux)."""
    if name in _FILTER_CACHE:
        return _FILTER_CACHE[name]
    ok = False
    if shutil.which(FFMPEG_BIN):
        try:
            out = subprocess.run([FFMPEG_BIN, "-hide_banner", "-filters"],
                                 capture_output=True, text=True, timeout=15)
            ok = f" {name} " in (out.stdout or "")
        except (OSError, subprocess.SubprocessError):
            ok = False
    _FILTER_CACHE[name] = ok
    return ok


# ─────────────────────────── plan de sincronía ───────────────────────────
def plan_scene(entry: dict, run_dir: Path) -> dict:
    """Decide CÓMO calzar el visual con su narración:
    · placeholder → lavfi color (escena fallida con force_placeholder)
    · image       → Ken Burns (zoompan) de la duración exacta
    · video corta → loop (-stream_loop -1 + -t)
    · video larga → trim (-t)
    · probe fallido → loop (seguro: -t corta de todos modos)"""
    target = round(float(entry.get("duration_sec") or 0) or
                   float(_cfg("RENDER_MIN_SCENE_SEC", 2.0)), 3)
    atype = entry.get("asset_type")
    if entry.get("status") != "ready" or atype == "placeholder" or not entry.get("asset_path"):
        return {"mode": "placeholder", "target": target}
    if atype == "image":
        return {"mode": "kenburns", "target": target}
    src = Path(run_dir) / (entry.get("asset_path") or "")
    src_dur = _probe_media(src)
    if src_dur is None:
        return {"mode": "loop", "target": target, "source_duration": None}
    if src_dur >= target - 0.05:
        return {"mode": "trim", "target": target, "source_duration": round(src_dur, 3)}
    return {"mode": "loop", "target": target, "source_duration": round(src_dur, 3)}


def _probe_media(path: Path) -> float | None:
    """Duración real vía ffprobe; None si no está el binario o el medio."""
    if not shutil.which(FFPROBE_BIN) or not path.is_file():
        return None
    try:
        out = subprocess.run(
            [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30)
        val = float((out.stdout or "").strip().splitlines()[0])
        return val if val > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return None


def _video_chain(plan: dict, w: int, h: int, fps: int) -> str:
    """Cadena -vf de normalización por modo (determinista, testeable)."""
    if plan["mode"] == "kenburns":
        frames = max(1, int(round(plan["target"] * fps)))
        # pre-escala a cover + crop ANTES del zoompan: imágenes con aspect
        # distinto al del render nunca se estiran (Ken Burns centrado limpio)
        return (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},"
                "zoompan=z='min(zoom+0.0015,1.15)'"
                f":d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":s={w}x{h}:fps={fps},setsar=1,format=yuv420p")
    if plan["mode"] == "placeholder":
        return "setsar=1,format=yuv420p"
    base = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},fps={fps},setsar=1,format=yuv420p")
    return base


def build_scene_cmd(entry: dict, plan: dict, run_dir: Path) -> dict:
    """Comando ffmpeg que NORMALIZA una escena a norm/scene_XXX.mp4 con
    duración EXACTA (duration sync), H.264/AAC y audio 48k stereo."""
    run_dir = Path(run_dir)
    m = manifest_res(run_dir)  # resolución del manifest persistido
    w, h = m
    fps = int(_cfg("FPS", 30))
    preset = str(_cfg("RENDER_X264_PRESET", "veryfast"))
    crf = int(_cfg("RENDER_CRF", 20))
    target = plan["target"]
    out_dir = run_dir / NORM_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"scene_{int(entry.get('idx') or 0):03d}.mp4"
    cmd = [FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error"]
    # ── entrada de video (índice 0) ──
    if plan["mode"] == "placeholder":
        cmd += ["-f", "lavfi", "-i",
                f"color=c={_COLOR_BG}:s={w}x{h}:r={fps}"]
    else:
        src = run_dir / (entry.get("asset_path") or "")
        if plan["mode"] == "loop":
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", str(src)]
    # ── entrada de audio (índice 1) ──
    nar = entry.get("narration_audio_path") or ""
    has_voice = bool(nar)
    if has_voice:
        cmd += ["-i", str(run_dir / nar)]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    # ── filtros y duración exacta ──
    cmd += ["-map", "0:v", "-map", "1:a"]
    if has_voice:
        # apad rellena con silencio hasta la duración objetivo (voice-over
        # más corto que la escena nunca desincroniza el concat)
        cmd += ["-af", f"apad=whole_dur={target:.3f},aresample=48000",
                "-ac", "2"]
    cmd += ["-vf", _video_chain(plan, w, h, fps),
            "-t", f"{target:.3f}", "-r", str(fps),
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            str(out)]
    return {"cmd": cmd, "out": out, "mode": plan["mode"], "target": target}


def manifest_res(run_dir: Path) -> tuple[int, int]:
    """Lee WxH del manifest persistido (fuente de verdad del formato)."""
    try:
        m = json.loads((Path(run_dir) / "manifest.json").read_text(encoding="utf-8"))
        w, h = str(m.get("resolution") or "1080x1920").lower().split("x")
        return int(w), int(h)
    except (OSError, ValueError, json.JSONDecodeError):
        return int(_cfg("SHORT_W", 1080)), int(_cfg("SHORT_H", 1920))


# ─────────────────────────── subtítulos (.srt) ───────────────────────────
def _ts(seconds: float) -> str:
    """Timestamp SRT: HH:MM:SS,mmm (determinista, sin drift acumulado:
    se calcula desde el inicio absoluto de cada escena)."""
    ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(entries: list[dict]) -> str:
    """SRT por escena: cada subtítulo cubre [inicio_acumulado, +duration].
    Escenas sin texto se omiten (no generan bloques vacíos)."""
    blocks: list[str] = []
    cursor = 0.0
    n = 0
    for e in entries:
        dur = float(e.get("duration_sec") or 0)
        text = (e.get("subtitle_text") or "").strip()
        if text:
            n += 1
            start = cursor
            end = cursor + max(dur, 0.001)
            blocks.append(f"{n}\n{_ts(start)} --> {_ts(end)}\n{text}\n")
        cursor += dur
    return "\n".join(blocks)


def write_srt(run_dir: Path, entries: list[dict]) -> Path:
    p = Path(run_dir) / SRT_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(build_srt(entries), encoding="utf-8")
    return p


# ─────────────────────────── concat · mix · captions ─────────────────────
def build_concat_cmd(scene_outs: list[Path], run_dir: Path) -> dict:
    """Concat demuxer (los norm/ comparten códec/params → -c copy sin
    re-codificar). list.txt con rutas ABSOLUTAS y comillas escapadas."""
    run_dir = Path(run_dir)
    list_path = run_dir / NORM_DIRNAME / "concat_list.txt"
    lines = [f"file '{p.resolve()}'" for p in scene_outs]
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    concat_out = run_dir / "video_concat.mp4"
    cmd = [FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", str(list_path),
           "-c", "copy", str(concat_out)]
    return {"cmd": cmd, "out": concat_out, "list": list_path}


def resolve_music(music_path: str) -> Path | None:
    """Ruta de música: absoluta, o nombre dentro de config.MUSIC_DIR.
    Configurada pero inexistente → None (mezcla sin música, NUNCA tumba)."""
    mp = (music_path or "").strip() or str(_cfg("RENDER_MUSIC_PATH", "") or "").strip()
    if not mp:
        return None
    p = Path(mp)
    if not p.is_file():
        alt = Path(_cfg("MUSIC_DIR", "")) / mp if _cfg("MUSIC_DIR", "") else None
        if alt and alt.is_file():
            return alt
        return None
    return p



def build_sfx_cmd(video_in: Path, scene_durations: list[float], run_dir: Path) -> dict | None:
    """Inserta micro-efectos de sonido (Whoosh) en los cortes de escena (INT-050)."""
    try:
        from services import sfx_manager
        events = sfx_manager.plan_sfx_events(scene_durations)
        if not events:
            return None
        lib = sfx_manager.ensure_sfx_library()
        valid_events = [ev for ev in events if ev.get("type") in lib and lib[ev["type"]].is_file()]
        if not valid_events:
            return None

        out = run_dir / "sfx_mix.mp4"
        cmd = [FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video_in)]
        filter_parts = []
        mix_labels = ["[0:a]"]

        for idx, ev in enumerate(valid_events, start=1):
            sfx_path = lib[ev["type"]]
            cmd.extend(["-i", str(sfx_path)])
            delay_ms = int(round(max(0.0, ev["time"]) * 1000))
            vol = float(ev.get("volume", 0.22))
            filter_parts.append(f"[{idx}:a]volume={vol},adelay={delay_ms}|{delay_ms}[sfx{idx}];")
            mix_labels.append(f"[sfx{idx}]")

        num_inputs = len(mix_labels)
        filter_parts.append(
            f"{''.join(mix_labels)}amix=inputs={num_inputs}:duration=first:dropout_transition=0:normalize=0[aout]"
        )

        cmd.extend([
            "-filter_complex", "".join(filter_parts),
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            str(out)
        ])
        return {"out": out, "cmd": cmd, "count": len(valid_events)}
    except Exception as ex:
        log.warning("[video_assembler] Omitiendo SFX por error: %s", ex)
        return None

def build_mix_cmd(concat_out: Path, music: Path | None,
                  run_dir: Path) -> dict | None:
    """Cama musical ducked -20dB mezclada sobre la voz (amix duration=first:
    la voz manda). Video se copia (sin re-codificar). None si no hay música."""
    if music is None:
        return None
    run_dir = Path(run_dir)
    duck = max(min(float(_cfg("RENDER_MUSIC_DUCK_DB", -20)), 0.0), _MIX_DB_FLOOR)
    out_av = run_dir / "final_av.mp4"
    fc = (f"[1:a]volume={duck:g}dB[m];"
          f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[aout]")
    cmd = [FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(concat_out), "-stream_loop", "-1", "-i", str(music),
           "-filter_complex", fc,
           "-map", "0:v", "-map", "[aout]",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
           str(out_av)]
    return {"cmd": cmd, "out": out_av, "duck_db": duck}


def build_burn_cmd(src: Path, srt: Path, out: Path) -> dict:
    """Quema subtítulos con libass. cwd=run_dir y nombre de archivo RELATIVO
    en el filtro → cero problemas de escaping de rutas Windows/espacios."""
    cmd = [FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(src), "-vf", f"subtitles={srt.name}",
           "-c:v", "libx264", "-preset", str(_cfg("RENDER_X264_PRESET", "veryfast")),
           "-crf", str(int(_cfg("RENDER_CRF", 20))), "-pix_fmt", "yuv420p",
           "-c:a", "copy", str(out)]
    return {"cmd": cmd, "out": out}


def build_soft_cmd(src: Path, srt: Path, out: Path) -> dict:
    """Fallback sin libass: subtítulos SOFT (mov_text, pista seleccionable)."""
    cmd = [FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(src), "-i", str(srt),
           "-map", "0", "-map", "1", "-c", "copy", "-c:s", "mov_text",
           "-metadata:s:s:0", "language=spa", str(out)]
    return {"cmd": cmd, "out": out}


# ─────────────────────────── plan completo ───────────────────────────────
def plan_render(manifest: dict, run_dir: Path, music_path: str = "",
                subtitles: str | None = None) -> dict:
    """Construye el plan COMPLETO de render (lista de comandos ffmpeg en orden)
    sin ejecutar nada. Es la unidad de test hermética: cada fragmento clave
    (scale/crop, fps, -stream_loop, zoompan, apad, volume=-20dB, subtitles,
    libx264/aac, -t exacto) es verificable sin binario ni GPU."""
    run_dir = Path(run_dir)
    subs_mode = (subtitles or str(_cfg("RENDER_SUBTITLES", "burn")) or "off").lower()
    entries = manifest.get("scenes") or []
    usable = [e for e in entries if e.get("status") in ("ready", "placeholder")]
    if not usable:
        raise AssemblerError(
            "no hay escenas consolidadas (ready/placeholder) para ensamblar",
            "RENDER_NOTHING_READY")
    steps: list[dict] = []
    # 1) normalización por escena (duration sync)
    scene_outs: list[Path] = []
    plans: list[dict] = []
    for e in usable:
        p = plan_scene(e, run_dir)
        built = build_scene_cmd(e, p, run_dir)
        plans.append({"scene_id": e.get("scene_id"), "mode": p["mode"],
                      "target": p["target"]})
        steps.append({"stage": "scenes", "desc": f"normaliza {e.get('scene_id')} "
                                                  f"({p['mode']} → {p['target']:.2f}s)",
                      "cmd": built["cmd"]})
        scene_outs.append(Path(built["out"]))
    # 2) concat
    cc = build_concat_cmd(scene_outs, run_dir)
    steps.append({"stage": "concat", "desc": f"concat demuxer de {len(scene_outs)} escenas",
                  "cmd": cc["cmd"]})
    current = cc["out"]
    # 3) mix con cama musical (opcional, duck -20dB)
    music = resolve_music(music_path)
    mc = build_mix_cmd(cc["out"], music, run_dir)
    if mc is not None:
        steps.append({"stage": "mix",
                      "desc": f"mezcla música {music.name} ducked {mc['duck_db']:g}dB",
                      "cmd": mc["cmd"]})
        current = mc["out"]
    # 3.5) INT-050: Sound Effects (SFX) automáticos en cortes
    use_sfx = bool(manifest.get("sfx", True))
    if use_sfx and len(usable) > 1:
        durs = [float(e.get("duration_sec") or 0) for e in usable]
        sfx_c = build_sfx_cmd(current, durs, run_dir)
        if sfx_c is not None:
            steps.append({"stage": "sfx",
                          "desc": f"micro-efectos SFX en {sfx_c['count']} cortes (whoosh)",
                          "cmd": sfx_c["cmd"]})
            current = sfx_c["out"]
    # 4) subtítulos burn → soft → off
    final = run_dir / FINAL_NAME
    srt_path = None
    ass_path = None
    if subs_mode in ("burn", "soft"):
        srt_path = write_srt(run_dir, usable)
        style_name = str(manifest.get("subtitle_style") or _cfg("SUBTITLE_STYLE", "")).strip().lower()
        if style_name and style_name not in ("srt", "classic", "none", "off"):
            try:
                from services import karaoke_subtitles
                res_str = str(manifest.get("resolution") or "1080x1920")
                ass_path = karaoke_subtitles.write_ass(run_dir, usable, style_name=style_name, resolution=res_str)
            except Exception as ex:
                log.debug("[video_assembler] karaoke ass fallback a srt: %s", ex)
    if subs_mode == "burn" and has_filter("subtitles"):
        cap_file = ass_path if (ass_path and ass_path.is_file()) else srt_path
        steps.append({"stage": "subtitles", "desc": f"quema {cap_file.name} (libass)",
                      "cmd": build_burn_cmd(current, cap_file, final)["cmd"]})
    elif subs_mode in ("burn", "soft"):
        steps.append({"stage": "subtitles", "desc": "mux .srt soft (mov_text)",
                      "cmd": build_soft_cmd(current, srt_path, final)["cmd"]})
    elif current != final:
        steps.append({"stage": "final", "desc": "copia del master a final_render.mp4",
                      "cmd": [FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
                              "-i", str(current), "-c", "copy", str(final)]})
    return {
        "run_id": manifest.get("run_id") or run_dir.name,
        "resolution": manifest.get("resolution"),
        "fps": manifest.get("fps"),
        "scenes_total": len(entries),
        "scenes_used": len(usable),
        "duration_total": round(sum(float(e.get("duration_sec") or 0)
                                    for e in usable), 3),
        "music": str(music) if music else "",
        "subtitles": (subs_mode if subs_mode in ("burn", "soft") else "off"),
        "srt": str(srt_path) if srt_path else "",
        "final": str(final),
        "scene_plans": plans,
        "steps": steps,
    }


def _short(cmd: list[str], limit: int = 200) -> str:
    s = " ".join(str(c) for c in cmd)
    return s if len(s) <= limit else s[:limit - 1] + "…"


def execute_plan(plan: dict, run_dir: Path,
                 progress_cb: Callable[[str, str, int], None] | None = None,
                 timeout: float | None = None) -> dict:
    """Ejecuta los comandos del plan en orden (subprocess con timeout y
    stderr surfaced). Lanza AssemblerError con código estable al primer fallo.
    progress_cb(stage, detail, pct) se invoca antes de cada paso."""
    run_dir = Path(run_dir)
    timeout = timeout or float(_cfg("RENDER_FFMPEG_TIMEOUT", 900))
    steps = plan.get("steps") or []
    n = max(1, len(steps))
    for i, st in enumerate(steps):
        pct = int(10 + 85 * i / n)
        if progress_cb:
            progress_cb(st["stage"], f"[{i + 1}/{n}] {st['desc']}", pct)
        try:
            proc = subprocess.run(st["cmd"], cwd=str(run_dir),
                                  capture_output=True, text=True,
                                  timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise AssemblerError(
                f"timeout {timeout:.0f}s en paso '{st['stage']}' "
                f"({_short(st['cmd'])})", "RENDER_TIMEOUT") from e
        except OSError as e:
            raise AssemblerError(
                f"no se pudo ejecutar ffmpeg en '{st['stage']}': {e} "
                f"(¿ffmpeg instalado? sudo apt install ffmpeg)",
                "RENDER_NO_FFMPEG") from e
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-400:].strip()
            raise AssemblerError(
                f"ffmpeg falló en '{st['stage']}' (rc={proc.returncode}): {tail}",
                "RENDER_CMD_FAILED")
    # copia final si el último paso no produjo final_render.mp4 directamente
    final = Path(plan.get("final") or (run_dir / FINAL_NAME))
    if not final.is_file() and steps:
        raise AssemblerError(
            "el plan terminó pero final_render.mp4 no existe "
            "(paso final no produjo salida)", "RENDER_NO_OUTPUT")
    if progress_cb:
        progress_cb("done", "render final listo", 100)
    return {"output": str(final), "steps_executed": len(steps),
            "duration_total": plan.get("duration_total")}


# ─────────────────────────── API de alto nivel ───────────────────────────
def assemble_run(run_dir: Path, dry_run: bool = False,
                 music_path: str = "", subtitles: str | None = None,
                 progress_cb: Callable[[str, str, int], None] | None = None) -> dict:
    """Stage 4 completo sobre un run_dir con manifest.json válido.
    · dry_run=True → construye el plan COMPLETO (cmds exactos), lo persiste
      en render_plan.json y NO ejecuta nada (hermético / sin ffmpeg).
    · dry_run=False → exige ffmpeg presente (RENDER_NO_FFMPEG si no) y
      ejecuta el plan con tolerancia a fallos."""
    run_dir = Path(run_dir)
    manifest = load_manifest(run_dir)  # valida esquema estricto
    plan = plan_render(manifest, run_dir, music_path=music_path,
                       subtitles=subtitles)
    plan_path = run_dir / PLAN_NAME
    tmp = run_dir / (PLAN_NAME + ".tmp")
    tmp.write_text(json.dumps(plan, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, plan_path)
    if dry_run:
        if progress_cb:
            progress_cb("plan", f"plan de {len(plan['steps'])} paso(s) "
                                f"(dry-run, sin ejecutar)", 5)
        return {"dry_run": True, "plan": plan, "plan_path": str(plan_path),
                "output": plan["final"], "steps": len(plan["steps"])}
    if ffmpeg_version() is None:
        raise AssemblerError(
            "binario ffmpeg no disponible — instala ffmpeg o usa dry_run=true",
            "RENDER_NO_FFMPEG")
    result = execute_plan(plan, run_dir, progress_cb=progress_cb)
    result.update({"dry_run": False, "duration_total": plan["duration_total"],
                   "resolution": plan["resolution"], "fps": plan["fps"],
                   "subtitles": plan["subtitles"], "srt": plan["srt"]})
    log.info("[render %s] OK → %s (%.2fs, %d pasos)", plan["run_id"],
             result["output"], plan["duration_total"], len(plan["steps"]))
    return result


__all__ = [
    "AssemblerError", "assemble_run", "build_burn_cmd", "build_concat_cmd",
    "build_mix_cmd", "build_scene_cmd", "build_srt", "build_soft_cmd",
    "execute_plan", "ffmpeg_version", "has_filter", "manifest_res",
    "plan_render", "plan_scene", "resolve_music", "write_srt",
    "HarvesterError",
]

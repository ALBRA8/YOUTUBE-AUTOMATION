"""
YOUTUBE AUTOMATION v2.0 — Paso 4: Render de video
Ken Burns (zoompan) por escena → concat → voz + música con ducking →
subtítulos estilo TikTok/Hormozi quemados con ASS. 100% ffmpeg.
"""
import asyncio
import json
import logging
import subprocess
from pathlib import Path

from config import FPS, LONG_H, LONG_W, MUSIC_VOLUME, OUTPUT_DIR, SHORT_H, SHORT_W
from pipeline import subtitles as subs_mod

log = logging.getLogger("video")

TRANSITION_DUR = 0.5  # segundos de crossfade entre escenas (compensado en el pad)


def _run_ffmpeg(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe_duration(path: Path) -> float:
    """Duración REAL de un medio con ffprobe (nunca estimar: sincronía exacta)."""
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30)
        return float(p.stdout.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return 0.0


def scene_clip_cmd(img: Path, duration: float, out: Path, w: int, h: int,
                   fps: int = FPS, zoom_dir: int = 1) -> list[str]:
    """Ken Burns: zoom in/out suave con zoompan."""
    frames = max(int(duration * fps), 1)
    zexpr = (f"min(1+0.12*on/{frames},1.12)" if zoom_dir > 0
             else f"max(1.12-0.12*on/{frames},1.0)")
    vf = (
        f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,"
        f"crop={w * 2}:{h * 2},"
        f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={w}x{h}:fps={fps},"
        f"format=yuv420p"
    )
    return ["ffmpeg", "-y", "-loop", "1", "-i", str(img), "-t", f"{duration:.3f}",
            "-vf", vf, "-r", str(fps), "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out)]


def retime_clip_cmd(src: Path, target_dur: float, out: Path, w: int, h: int,
                    fps: int = FPS) -> list[str]:
    """Video REAL de Flow (Veo ~8s fijos) re-temporalizado a la duración de la
    narración con setpts (patrón hans-n8n / AI-Content-Automation-Engine).
    duration_out = duration_src * factor ⇒ factor = target/src:
    factor>1 ralentiza (slow-mo cinemático), factor<1 acelera. Se limita a
    [0.5, 2.5] y se recorta con -t. Audio original eliminado (la voz es nuestra)."""
    src_dur = probe_duration(src)
    factor = (target_dur / src_dur) if (src_dur > 0.3 and target_dur > 0.3) else 1.0
    factor = max(0.5, min(2.5, factor))
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,"
          f"crop={w * 2}:{h * 2},setpts=PTS*{factor:.6f},fps={fps},format=yuv420p")
    return ["ffmpeg", "-y", "-i", str(src), "-vf", vf, "-an",
            "-t", f"{target_dur:.3f}", "-r", str(fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out)]


def _clip_cache_ok(out: Path, src: Path, target_dur: float) -> bool:
    """Reutilización EXACTA de clips (FolderStore): el clip existe, pesa lo
    suficiente, proviene del mismo asset fuente y su duración objetivo no ha
    cambiado (sidecar JSON). Un re-run del pipeline no re-renderiza lo válido."""
    try:
        d = json.loads(out.with_suffix(".json").read_text())
        return (out.exists() and out.stat().st_size > 4096
                and d.get("src") == str(src)
                and abs(float(d.get("dur", 0)) - target_dur) < 0.05)
    except Exception:  # noqa: BLE001
        return False


async def render_scenes(project: dict, scenes: list[dict], durations: list[float],
                        on_progress=None, is_cancelled=None,
                        flow_videos: dict | None = None,
                        transition_pad: float = 0.0) -> list[Path]:
    """Renderiza el clip de cada escena, 2 en paralelo.

    - Si la escena tiene video REAL de Flow (flow_videos[i]) se usa con retime
      setpts a la duración de la narración; si no, Ken Burns sobre la imagen.
    - transition_pad añade margen a los clips NO finales para que, tras el
      solape xfade, la duración total coincida EXACTAMENTE con sum(durations)
      y la voz quede sincronizada.
    - Reutilización idempotente: clip válido con mismo source y misma
      duración objetivo se salta (ver _clip_cache_ok)."""
    proj_dir = OUTPUT_DIR / project["id"]
    clips_dir = proj_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    w, h = (SHORT_W, SHORT_H) if project["format"] == "short" else (LONG_W, LONG_H)
    n_scenes = len(scenes)

    async def one(i: int) -> Path:
        if is_cancelled and is_cancelled():
            raise asyncio.CancelledError("cancelado")
        img = scenes[i].get("image_path") or ""
        out = clips_dir / f"clip_{i:02d}.mp4"
        dur = max(durations[i], 1.0)
        pad = transition_pad if i < n_scenes - 1 else 0.0
        fv = (flow_videos or {}).get(i)
        has_fv = bool(fv) and Path(str(fv)).exists()
        src = Path(str(fv)) if has_fv else Path(img)
        target = dur + pad if has_fv else dur + 0.05 + pad
        if _clip_cache_ok(out, src, target):
            if on_progress:
                await on_progress(i + 1, n_scenes, None)
            return out
        if has_fv:
            cmd = retime_clip_cmd(src, target, out, w, h)
        else:
            cmd = scene_clip_cmd(src, target, out, w, h,
                                 zoom_dir=1 if i % 2 == 0 else -1)
        p = await asyncio.to_thread(lambda: _run_ffmpeg(cmd))
        if p.returncode != 0:
            log.error("clip %d: %s", i, p.stderr[-300:])
            raise RuntimeError(f"Error renderizando escena {i + 1}")
        try:  # sidecar para reutilización exacta en re-runs
            out.with_suffix(".json").write_text(json.dumps(
                {"src": str(src), "dur": round(target, 3)}))
        except Exception:  # noqa: BLE001
            pass
        if on_progress:
            await on_progress(i + 1, n_scenes, None)
        return out

    sem = asyncio.Semaphore(2)

    async def guarded(i):
        async with sem:
            return await one(i)

    return await asyncio.gather(*(guarded(i) for i in range(n_scenes)))


async def concat_clips(project: dict, clips: list[Path],
                       transition: str | None = None) -> Path:
    """Une los clips. Con transition (ej. 'fade', 'smoothleft', 'circleopen')
    usa xfade encadenado con offsets incrementales (offset += dur_prev - tdur;
    el detalle que casi todos hacen mal). Si algo falla, cae al concat demuxer
    -c copy sin re-encode."""
    proj_dir = OUTPUT_DIR / project["id"]
    out = proj_dir / "video_silent.mp4"

    if transition and len(clips) >= 2:
        try:
            return await _concat_xfade(project, clips, out, transition)
        except Exception as e:  # noqa: BLE001
            log.warning("xfade falló (%s) → concat -c copy", str(e)[:160])

    concat_file = proj_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{c.as_posix()}'" for c in clips), encoding="utf8")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
           "-c", "copy", str(out)]
    p = await asyncio.to_thread(lambda: _run_ffmpeg(cmd, timeout=300))
    if p.returncode != 0:
        raise RuntimeError("No se pudo unir los clips")
    return out


async def _concat_xfade(project: dict, clips: list[Path], out: Path,
                        transition: str) -> Path:
    """filter_complex xfade encadenado con offsets incrementales sobre las
    duraciones REALES (ffprobe) de cada clip. Sin audio (clips -an):
    la voz se mezcla después en mux_audio_music."""
    tdur = TRANSITION_DUR
    durs = [probe_duration(c) for c in clips]
    if any(d <= tdur + 0.1 for d in durs):
        raise RuntimeError("clip demasiado corto para xfade")
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]
    chains: list[str] = []
    prev = "[0:v]"
    offset = 0.0
    for k in range(1, len(clips)):
        offset += durs[k - 1] - tdur
        label = f"[v{k}]"
        chains.append(
            f"{prev}[{k}:v]xfade=transition={transition}:duration={tdur:.3f}"
            f":offset={offset:.3f}{label}")
        prev = label
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(chains),
           "-map", prev, "-c:v", "libx264", "-profile:v", "main", "-level", "4.0",
           "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "18",
           "-r", str(FPS), str(out)]
    p = await asyncio.to_thread(lambda: _run_ffmpeg(cmd, timeout=1800))
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-300:])
    return out


async def mux_audio_music(project: dict, video_silent: Path, voice_full: Path) -> Path:
    """Une video + voz + música (con ducking automático sobre la voz)."""
    proj_dir = OUTPUT_DIR / project["id"]
    music = _pick_music()
    out = proj_dir / "video_raw.mp4"

    if music and music.exists():
        # sidechaincompress: la música baja cuando habla la voz
        filter_complex = (
            f"[1:a]asplit=2[vo][sc];"
            f"[2:a]volume={MUSIC_VOLUME},aformat=sample_rates=24000:channel_layouts=mono[mus];"
            f"[mus][sc]sidechaincompress=threshold=0.02:ratio=12:attack=20:release=350[duck];"
            f"[vo][duck]amix=inputs=2:duration=first:dropout_transition=3[aout]"
        )
        cmd = ["ffmpeg", "-y", "-i", str(video_silent), "-i", str(voice_full),
               "-stream_loop", "-1", "-i", str(music),
               "-filter_complex", filter_complex, "-map", "0:v", "-map", "[aout]",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-shortest", str(out)]
        p = await asyncio.to_thread(lambda: _run_ffmpeg(cmd, timeout=600))
        if p.returncode != 0:
            log.warning("mux con música falló (%s) → solo voz", p.stderr[-200:])
    else:
        cmd = ["ffmpeg", "-y", "-i", str(video_silent), "-i", str(voice_full),
               "-map", "0:v", "-map", "1:a", "-c:v", "copy",
               "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)]
        p = await asyncio.to_thread(lambda: _run_ffmpeg(cmd, timeout=300))
        if p.returncode != 0:
            raise RuntimeError("No se pudo unir audio y video")
    return out


async def burn_subtitles(project: dict, video_raw: Path, words_path: Path) -> Path:
    """Quema los subtítulos ASS estilo TikTok/Hormozi sobre el video final."""
    proj_dir = OUTPUT_DIR / project["id"]
    words = json.loads(Path(words_path).read_text())
    if not words:
        import shutil
        final = proj_dir / f"{project['id']}_final.mp4"
        shutil.copy(video_raw, final)
        return final

    ass_path = proj_dir / "subs.ass"
    w, h = (SHORT_W, SHORT_H) if project["format"] == "short" else (LONG_W, LONG_H)
    ass_path.write_text(subs_mod.build_ass(words, w, h), encoding="utf8")

    final = proj_dir / f"{project['id']}_final.mp4"
    sub_filter = f"ass={ass_path.as_posix().replace(':', '\\\\:')}"
    cmd = ["ffmpeg", "-y", "-i", str(video_raw), "-vf", sub_filter,
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-c:a", "copy", str(final)]
    p = await asyncio.to_thread(lambda: _run_ffmpeg(cmd, timeout=900))
    if p.returncode != 0:
        log.error("subs burn: %s", p.stderr[-300:])
        import shutil
        shutil.copy(video_raw, final)
    return final


def make_thumbnail(project: dict, first_image: str | None) -> Path | None:
    """Miniatura 1080x1080 (o vertical) desde la primera escena."""
    proj_dir = OUTPUT_DIR / project["id"]
    if not first_image or not Path(first_image).exists():
        return None
    thumb = proj_dir / "thumb.jpg"
    w, h = (SHORT_W, SHORT_H) if project["format"] == "short" else (LONG_W, LONG_H)
    cmd = ["ffmpeg", "-y", "-i", first_image, "-vf",
           f"scale={w // 2}:{h // 2}:force_original_aspect_ratio=increase,"
           f"crop={w // 2}:{h // 2}",
           "-q:v", "3", str(thumb)]
    p = _run_ffmpeg(cmd, timeout=60)
    return thumb if p.returncode == 0 else None


def _pick_music() -> Path | None:
    from config import MUSIC_DIR
    tracks = sorted(MUSIC_DIR.glob("*.mp3")) + sorted(MUSIC_DIR.glob("*.wav"))
    return tracks[0] if tracks else None

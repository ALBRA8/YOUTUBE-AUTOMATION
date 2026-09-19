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


def _run_ffmpeg(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


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


async def render_scenes(project: dict, scenes: list[dict], durations: list[float],
                        on_progress=None, is_cancelled=None) -> list[Path]:
    """Renderiza el clip de cada escena (Ken Burns), 2 en paralelo."""
    proj_dir = OUTPUT_DIR / project["id"]
    clips_dir = proj_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    w, h = (SHORT_W, SHORT_H) if project["format"] == "short" else (LONG_W, LONG_H)

    async def one(i: int) -> Path:
        if is_cancelled and is_cancelled():
            raise asyncio.CancelledError("cancelado")
        img = scenes[i].get("image_path") or ""
        out = clips_dir / f"clip_{i:02d}.mp4"
        dur = max(durations[i], 1.0)
        cmd = scene_clip_cmd(Path(img), dur + 0.05, out, w, h,
                             zoom_dir=1 if i % 2 == 0 else -1)
        p = await asyncio.to_thread(lambda: _run_ffmpeg(cmd))
        if p.returncode != 0:
            log.error("clip %d: %s", i, p.stderr[-300:])
            raise RuntimeError(f"Error renderizando escena {i + 1}")
        if on_progress:
            await on_progress(i + 1, len(scenes), None)
        return out

    sem = asyncio.Semaphore(2)

    async def guarded(i):
        async with sem:
            return await one(i)

    return await asyncio.gather(*(guarded(i) for i in range(len(scenes))))


async def concat_clips(project: dict, clips: list[Path]) -> Path:
    proj_dir = OUTPUT_DIR / project["id"]
    concat_file = proj_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{c.as_posix()}'" for c in clips), encoding="utf8")
    out = proj_dir / "video_silent.mp4"
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
           "-c", "copy", str(out)]
    p = await asyncio.to_thread(lambda: _run_ffmpeg(cmd, timeout=300))
    if p.returncode != 0:
        raise RuntimeError("No se pudo unir los clips")
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

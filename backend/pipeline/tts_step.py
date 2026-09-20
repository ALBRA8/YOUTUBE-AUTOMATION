"""
YOUTUBE AUTOMATION v2.0 — Paso 3: TTS por escena + alineación Whisper
Genera la locución de cada escena (TTS dual con fallback automático) y
construye la línea de tiempo de palabras para los subtítulos TikTok/Hormozi.
Salida: voice_full.wav (pista completa) + words.json (timeline global).
"""
import asyncio
import json
import logging
import subprocess
from pathlib import Path

import database as db
from config import OUTPUT_DIR, TMP_DIR
from services import tts_service, whisper_service

log = logging.getLogger("tts_step")

GAP = 0.35  # pausa entre escenas (segundos)


async def synthesize_scenes(project: dict, scenes: list[dict], on_progress=None,
                            is_cancelled=None) -> tuple[list[float], list[list[dict]]]:
    """Devuelve (duraciones por escena, palabras por escena)."""
    provider = project.get("tts_provider") or None
    voice = project.get("voice") or None
    out_dir = OUTPUT_DIR / project["id"] / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)

    durations: list[float] = []
    words_per_scene: list[list[dict]] = []
    offset = 0.0

    for i, sc in enumerate(scenes):
        if is_cancelled and is_cancelled():
            raise asyncio.CancelledError("cancelado por el usuario")
        wav = out_dir / f"scene_{i:02d}.wav"
        text = sc["narration"] or sc["title"]
        try:
            _, dur, used = await tts_service.synthesize(text, wav, provider, voice)
        except Exception as e:  # noqa: BLE001
            log.error("TTS escena %d falló definitivamente: %s", i, e)
            tts_service.silence_wav(wav, 2.0)  # no romper el render
            dur, used = 2.0, "silence"

        db.update_scene(sc["id"], audio_path=str(wav), duration=dur,
                        meta={**sc.get("meta", {}), "tts": used})

        words = await whisper_service.align_scene(text, str(wav), dur)
        words = [{**w, "start": round(w["start"] + offset, 3),
                  "end": round(w["end"] + offset, 3)} for w in words]
        durations.append(dur)
        words_per_scene.append(words)
        offset += dur + GAP

        if on_progress:
            await on_progress(i + 1, len(scenes), used)

    return durations, words_per_scene


async def build_full_track(project: dict, durations: list[float]) -> Path:
    """Concatena audios de escenas con pausas → voice_full.wav
    Gráfica: [i:a]apad=pad_dur=GAP[ai]; ... ; [a0][a1]...concat=n:v=0:a=1[out]"""
    proj_dir = OUTPUT_DIR / project["id"]
    audio_dir = proj_dir / "audio"
    full = proj_dir / "voice_full.wav"

    inputs: list[str] = []
    pad_chains: list[str] = []
    concat_labels: list[str] = []
    for i, dur in enumerate(durations):
        wav = audio_dir / f"scene_{i:02d}.wav"
        if not wav.exists():
            silence = TMP_DIR / f"sil_{i}.wav"
            tts_service.silence_wav(silence, durations[i])
            wav = silence
        inputs += ["-i", str(wav)]
        if i < len(durations) - 1 and GAP > 0:
            pad_chains.append(f"[{i}:a]apad=pad_dur={GAP}[a{i}]")
        else:
            pad_chains.append(f"[{i}:a]anull[a{i}]")
        concat_labels.append(f"[a{i}]")

    chain = ";".join(pad_chains) + ";" + "".join(concat_labels) + \
        f"concat=n={len(durations)}:v=0:a=1[out]"
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", chain, "-map", "[out]",
           "-ar", "24000", "-ac", "1", str(full)]
    p = await asyncio.to_thread(
        lambda: subprocess.run(cmd, capture_output=True, text=True))
    if p.returncode != 0:
        log.error("concat audio: %s", p.stderr[-400:])
        raise RuntimeError("No se pudo unir el audio")
    return full


def save_words_timeline(project: dict, words_per_scene: list[list[dict]]) -> Path:
    proj_dir = OUTPUT_DIR / project["id"]
    out = proj_dir / "words.json"
    all_words = [w for ws in words_per_scene for w in ws]
    out.write_text(json.dumps(all_words, ensure_ascii=False, indent=1))
    return out

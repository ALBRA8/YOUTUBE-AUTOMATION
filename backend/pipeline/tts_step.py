"""
YOUTUBE AUTOMATION v2.1.2 — Paso 3: TTS + alineación Whisper
Dos rutas de síntesis:
  A) BATCHED (gemini): 1 llamada de TTS por cada 15 escenas + transcripción
     del lote con faster-whisper + fronteras de escena (mapeo de tokens con
     verificación LLM como plan B) + split ffmpeg. Patrón probado en
     AI-Content-Automation-Engine: reduce las llamadas TTS 15× (cuota gratis).
  B) POR ESCENA (edge/gemini): la ruta clásica, usada como fallback si el
     lote falla en CUALQUIER punto (nada queda a medias).
Ambas rutas son IDEMPOTENTES: una escena cuyo WAV ya existe en disco y cuyo
hash de texto coincide NO se vuelve a sintetizar (FolderStore skip-if-exists).
Salida: voice_full.wav + words.json (timeline global de palabras).
"""
import asyncio
import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path

import database as db
from config import OUTPUT_DIR, TMP_DIR
from services import gemini_client, tts_service, whisper_service

log = logging.getLogger("tts_step")

GAP = 0.35          # pausa entre escenas en voice_full (segundos)
TTS_BATCH_SIZE = 15 # escenas por llamada de TTS (cuota free-tier Gemini)
MIN_SCENE_DUR = 0.4 # duración mínima válida para un audio de escena


def _text_of(sc: dict) -> str:
    return (sc.get("narration") or sc.get("title") or "").strip()


def _hash_of(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


async def synthesize_scenes(project: dict, scenes: list[dict], on_progress=None,
                            is_cancelled=None) -> tuple[list[float], list[list[dict]]]:
    """Devuelve (duraciones por escena, palabras por escena)."""
    provider = project.get("tts_provider") or None
    voice = project.get("voice") or None
    out_dir = OUTPUT_DIR / project["id"] / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)

    n = len(scenes)
    durations: list[float] = [0.0] * n
    words_per_scene: list[list[dict] | None] = [None] * n
    used_per_scene: list[str] = [""] * n
    done = 0

    # 1) IDEMPOTENCIA — escenas ya en disco con hash de texto vigente
    todo: list[int] = []
    for i, sc in enumerate(scenes):
        wav = out_dir / f"scene_{i:02d}.wav"
        text = _text_of(sc)
        meta = sc.get("meta") or {}
        dur = tts_service.probe_duration(wav)
        if dur >= MIN_SCENE_DUR and meta.get("tts_hash") == _hash_of(text):
            durations[i] = dur
            used_per_scene[i] = meta.get("tts") or "cache"
            db.update_scene(sc["id"], audio_path=str(wav), duration=dur, meta=meta)
            done += 1
            if on_progress:
                await on_progress(done, n, "cache")
        else:
            todo.append(i)

    # 2) RUTA BATCHED (gemini + faster-whisper + ≥2 escenas pendientes)
    if (todo and len(todo) >= 2
            and (provider in (None, "gemini"))
            and gemini_client.available() and whisper_service.available()):
        try:
            done, todo = await _synthesize_batched(
                project, scenes, todo, out_dir, durations, used_per_scene,
                voice, done, on_progress, is_cancelled)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("TTS batched falló (%s) → síntesis por escena", str(e)[:160])
            # los lotes ya completados conservan su duración: no se re-sintetizan
            todo = [i for i in todo if durations[i] < MIN_SCENE_DUR]

    # 3) RUTA POR ESCENA (fallback o edge-tts)
    for i in todo:
        if is_cancelled and is_cancelled():
            raise asyncio.CancelledError("cancelado por el usuario")
        sc = scenes[i]
        wav = out_dir / f"scene_{i:02d}.wav"
        text = _text_of(sc)
        try:
            _, dur, used = await tts_service.synthesize(text, wav, provider, voice)
        except Exception as e:  # noqa: BLE001
            log.error("TTS escena %d falló definitivamente: %s", i, e)
            tts_service.silence_wav(wav, 2.0)  # no romper el render
            dur, used = 2.0, "silence"
        meta = {**(sc.get("meta") or {}), "tts": used, "tts_hash": _hash_of(text)}
        db.update_scene(sc["id"], audio_path=str(wav), duration=dur, meta=meta)
        durations[i] = dur
        used_per_scene[i] = used
        done += 1
        if on_progress:
            await on_progress(done, n, used)

    # 4) Timeline global de palabras (offset acumulado con GAP)
    offset = 0.0
    for i, sc in enumerate(scenes):
        wav = out_dir / f"scene_{i:02d}.wav"
        if durations[i] < MIN_SCENE_DUR:  # blindaje: nunca colapsar el render
            tts_service.silence_wav(wav, 2.0)
            durations[i] = 2.0
            used_per_scene[i] = used_per_scene[i] or "silence"
        words = await whisper_service.align_scene(_text_of(sc), str(wav), durations[i])
        words = [{**w, "start": round(w["start"] + offset, 3),
                  "end": round(w["end"] + offset, 3)} for w in words]
        words_per_scene[i] = words
        offset += durations[i] + GAP

    return durations, words_per_scene


# ───────────────────────────── RUTA BATCHED ────────────────────────────────
async def _synthesize_batched(project: dict, scenes: list[dict], todo: list[int],
                              out_dir: Path, durations: list[float],
                              used_per_scene: list[str], voice: str | None,
                              done: int, on_progress=None, is_cancelled=None):
    """Sintetiza las escenas pendientes en lotes de TTS_BATCH_SIZE.
    Devuelve (done, todo_restante). Lanza si algo falla → el caller hace
    fallback completo a la ruta por escena (el lote se borra)."""
    provider_hint = "gemini-batch"
    chunks = [todo[k:k + TTS_BATCH_SIZE] for k in range(0, len(todo), TTS_BATCH_SIZE)]
    remaining = list(todo)

    for chunk_ids in chunks:
        if is_cancelled and is_cancelled():
            raise asyncio.CancelledError("cancelado por el usuario")
        texts = [_text_of(scenes[i]) for i in chunk_ids]
        chunk_wav = out_dir / f"batch_{chunk_ids[0]:02d}_{chunk_ids[-1]:02d}.wav"
        try:
            pcm = await gemini_client.tts_pcm("\n\n".join(texts), voice)
            chunk_wav.write_bytes(pcm)
            chunk_dur = tts_service.probe_duration(chunk_wav)
            if chunk_dur < 1.0:
                raise RuntimeError("audio del lote demasiado corto")

            words = await whisper_service.transcribe_words(str(chunk_wav))
            if not words:
                raise RuntimeError("whisper no devolvió palabras del lote")

            bounds = await _scene_boundaries(texts, words, chunk_dur)
            for k, (st, en) in enumerate(bounds):
                if en - st < MIN_SCENE_DUR:
                    raise RuntimeError(f"duración inválida en escena {chunk_ids[k] + 1}")

            # split + persistencia por escena
            for k, i in enumerate(chunk_ids):
                st, en = bounds[k]
                scene_wav = out_dir / f"scene_{i:02d}.wav"
                _ffmpeg_cut(chunk_wav, scene_wav, st, en - st)
                dur = tts_service.probe_duration(scene_wav)
                if dur < MIN_SCENE_DUR:
                    raise RuntimeError(f"split escena {i + 1} demasiado corto")
                durations[i] = dur
                used_per_scene[i] = provider_hint
                meta = {**(scenes[i].get("meta") or {}), "tts": provider_hint,
                        "tts_hash": _hash_of(texts[k])}
                db.update_scene(scenes[i]["id"], audio_path=str(scene_wav),
                                duration=dur, meta=meta)
                done += 1
                remaining.remove(i)
                if on_progress:
                    await on_progress(done, len(scenes), provider_hint)
        finally:
            chunk_wav.unlink(missing_ok=True)  # el lote nunca queda huérfano

    return done, remaining


def _tokens_of(text: str) -> list[str]:
    """Palabras de una narración tal cual las contará el TTS (unicode-safe)."""
    return re.findall(r"\w+", (text or "").lower())


async def _scene_boundaries(texts: list[str], words: list[dict],
                            chunk_dur: float) -> list[tuple[float, float]]:
    """Fronteras (start, end) por escena dentro del lote.
    Plan A: mapeo secuencial por conteo de tokens (exacto si TTS leyó todo).
    Plan B: LLM con la transcripción temporizada (patrón del repo de referencia).
    Lanza si ninguno logra una alineación válida."""
    # Plan A — mapeo secuencial por conteo de tokens (gratis y exacto si el
    # TTS leyó las palabras tal cual; p.ej. números expandidos → mismatch)
    try:
        counts = [len(_tokens_of(t)) for t in texts]
        if sum(counts) == len(words):
            bounds: list[tuple[float, float]] = []
            pos = 0
            ok = True
            for c in counts:
                grp = words[pos:pos + c]
                if not grp:
                    ok = False
                    break
                start = max(0.0, grp[0]["start"] - 0.05)
                end = min(chunk_dur, grp[-1]["end"] + 0.12)
                if bounds and start < bounds[-1][1] - 0.25:
                    ok = False  # solape imposible → el TTS no leyó en orden
                    break
                bounds.append((start, end))
                pos += c
            if ok and pos == len(words):
                return bounds
    except Exception:  # noqa: BLE001
        pass

    # Plan B — LLM con la transcripción temporizada
    return await _llm_boundaries(texts, words, chunk_dur)


async def _llm_boundaries(texts: list[str], words: list[dict],
                          chunk_dur: float) -> list[tuple[float, float]]:
    if not gemini_client.available():
        raise RuntimeError("sin LLM para alinear fronteras")
    wtxt = " ".join(f"{w['word']}({w['start']:.2f}-{w['end']:.2f})" for w in words)
    stext = "\n".join(f"{k + 1}. {t}" for k, t in enumerate(texts))
    schema = {"type": "object", "properties": {"alignments": {"type": "array",
              "items": {"type": "object",
                        "properties": {"scene_number": {"type": "integer"},
                                       "start": {"type": "number"},
                                       "end": {"type": "number"}},
                        "required": ["scene_number", "start", "end"]}}},
              "required": ["alignments"]}
    prompt = (f"Un audio contiene {len(texts)} narraciones leídas en orden:\n"
              f"{stext}\n\nTranscripción temporizada (palabra(inicio-fin)):\n"
              f"{wtxt}\n\nDuración total: {chunk_dur:.2f}s. Devuelve para CADA "
              f"narración su tiempo de inicio y fin en segundos (scene_number "
              f"1-based en orden). JSON estricto con la schema.")
    data = await gemini_client.generate_json(prompt, schema=schema,
                                             system="Devuelve SOLO JSON válido.")
    al = data.get("alignments") or []
    if len(al) != len(texts):
        raise RuntimeError(f"alineación LLM: esperaba {len(texts)}, llegó {len(al)}")
    al.sort(key=lambda a: a["scene_number"])
    bounds = []
    for a in al:
        st, en = float(a["start"]), float(a["end"])
        if not (0.0 <= st < en <= chunk_dur + 0.5):
            raise RuntimeError("frontera LLM fuera de rango")
        bounds.append((st, min(en, chunk_dur)))
    for k in range(1, len(bounds)):
        if bounds[k][0] < bounds[k - 1][1] - 0.3:
            raise RuntimeError("fronteras LLM solapadas")
    return bounds


def _ffmpeg_cut(src: Path, dst: Path, start: float, duration: float) -> None:
    cmd = ["ffmpeg", "-y", "-i", str(src), "-ss", f"{start:.3f}",
           "-t", f"{duration:.3f}", "-ar", "24000", "-ac", "1", str(dst)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg cut: " + (p.stderr or "")[-200:])


# ───────────────────────── PISTA COMPLETA + TIMELINE ───────────────────────
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

"""
YOUTUBE AUTOMATION v2.0 — Paso 4: Render de video
Ken Burns (zoompan) por escena → concat → voz + música con ducking →
subtítulos estilo TikTok/Hormozi quemados con ASS. 100% ffmpeg.

INT-077 · Pacing estricto + estructura UGC nativa:
- El clip de cada escena dura EXACTAMENTE dur_audio + GAP(pausa de voz) +
  pad(transición) en escenas no finales y dur_audio en la final ⇒ la duración
  del master silencioso coincide MILIMÉTRICamente con voice_full.wav
  (Σdur + GAP×(n-1)) y el mux con -shortest jamás corta la narración en seco.
- Si el audio excede lo que el slow-mo (cap FACTOR_MAX) puede estirar del
  video de Flow, el clip se ENBUCLA (-stream_loop -1) con factor por
  segmento; tras cada render se mide el clip con ffprobe y una remediación
  única fuerza el bucle si quedó corto (verificación, no suposición).
- Escenas tipadas UGC: type 'avatar' (Flow + lip-sync v2v) intercalado con
  type 'product_broll' (imagen de producto + zoompan, solo TTS en off, SIN
  lip-sync facial) — el B-roll descansa la vista del avatar y mata el
  uncanny valley de los planos fijos de 8-12 s.
"""
import asyncio
import json
import logging
import math
import random
import subprocess
from pathlib import Path

from config import FPS, LONG_H, LONG_W, MUSIC_VOLUME, OUTPUT_DIR, SHORT_H, SHORT_W
from pipeline import subtitles as subs_mod
from pipeline import typography as typo_mod
from pipeline.tts_step import GAP as VOICE_GAP  # pausa real de voice_full
from services import avatar_motion

log = logging.getLogger("video")

TRANSITION_DUR = 0.5  # segundos de crossfade entre escenas (compensado en el pad)
FACTOR_MAX = 2.5      # cap de slow-mo por segmento (retime setpts)
CLIP_TOL = 0.25       # tolerancia milimétrica post-render (s) clip vs target
# INT-077 · tipos de escena UGC (scene['type'] o scene['meta']['type'],
# case-insensitive). Sin type → comportamiento legacy 100% compatible.
BROLL_TYPES = {"product_broll", "broll", "product"}


def scene_render_mode(scene: dict, has_flow_video: bool) -> str:
    """Modo de render de una escena (INT-077 estructura UGC nativa):
    - 'broll_zoompan': escena product_broll → imagen de producto + Ken Burns
      (zoompan 3 fases) y solo TTS en off. NUNCA lip-sync facial: aunque haya
      video de Flow asignado se ignora a propósito (descanso visual del
      avatar, cero uncanny valley).
    - 'flow_lipsync': escena avatar → video de Flow + lip-sync v2v + retime.
    - 'kenburns': sin video de Flow → imagen con Ken Burns (fail-open clásico).
    El type se lee de scene['type'] o scene['meta']['type']; sin type los
    proyectos legacy renderizan exactamente igual que siempre."""
    stype = str(scene.get("type")
                or (scene.get("meta") or {}).get("type") or "").strip().lower()
    if stype in BROLL_TYPES:
        return "broll_zoompan"
    if has_flow_video:
        return "flow_lipsync"
    return "kenburns"

# Ken Burns 3 fases (patrón hans-n8n "videos-without-ai"):
# zoom-in durante los primeros ZOOM_IN_FRAC de la escena, meseta al peak,
# zoom-out en el último ZOOM_OUT_FRAC. Rotación sinusoidal sutil de
# ROTATE_DEG grados con periodo ROTATE_SPEED s para dar vida sin marear.
ZOOM_IN_FRAC = 0.2
ZOOM_OUT_FRAC = 0.2
ZOOM_PEAK = 1.2
ROTATE_DEG = 0.8
ROTATE_SPEED = 4.0


def kenburns_3phase_expr(frames: int, zoom_in_frac: float = ZOOM_IN_FRAC,
                          zoom_out_frac: float = ZOOM_OUT_FRAC,
                          peak: float = ZOOM_PEAK) -> str:
    """Expresión zoompan EXACTA de hans-n8n:
    if(lt(on,F_IN),1+amp*(on/F_IN), if(lt(on,F_OUT),peak,
       peak-amp*((on-F_OUT)/(TOTAL-F_OUT))))
    F_IN/F_OUT derivan de TOTAL_FRAMES × fracción. Con d=frames, `on`
    recorre 0..frames-1 sobre la única imagen de entrada."""
    frames = max(int(frames), 1)
    amp = peak - 1.0
    f_in = max(int(frames * zoom_in_frac), 1)
    f_out = max(frames - max(int(frames * zoom_out_frac), 1), f_in + 1)
    tail = max(frames - f_out, 1)
    return (f"if(lt(on,{f_in}),1+{amp:.3f}*(on/{f_in}),"
            f"if(lt(on,{f_out}),{peak:.3f},"
            f"{peak:.3f}-{amp:.3f}*((on-{f_out})/{tail})))")


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
                   fps: int = FPS, zoom_dir: int = 1,
                   rotate_deg: float = ROTATE_DEG,
                   rotate_speed: float = ROTATE_SPEED) -> list[str]:
    """Ken Burns 3 FASES + rotación sinusoidal (patrón hans-n8n):
    zoom-in 0→peak en el primer 20% de la escena, meseta al peak,
    zoom-out peak→1.0 en el último 20%; la cámara oscila ±rotate_deg grados
    con periodo rotate_speed s. zoom_dir alterna el peak por paridad de
    escena para variedad (escenas contiguas no respiran igual)."""
    frames = max(int(duration * fps), 1)
    peak = ZOOM_PEAK if zoom_dir > 0 else 1.12
    zexpr = kenburns_3phase_expr(frames, peak=peak)
    parts = [
        f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase",
        f"crop={w * 2}:{h * 2}",
        f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={w}x{h}:fps={fps}",
    ]
    if rotate_deg and rotate_deg > 0:
        parts.append(
            f"rotate='{rotate_deg}*PI/180*sin(2*PI*t/{rotate_speed})'"
            ":fillcolor=black")
    parts.append("format=yuv420p")
    vf = ",".join(parts)
    # -frames:v exacto (INT-077): ver retime_clip_cmd — -t solo deja pasar
    # frames extra de la cola del encoder; el conteo es determinista.
    frames_out = max(int(math.ceil(duration * fps)), 1)
    return ["ffmpeg", "-y", "-loop", "1", "-i", str(img),
            "-frames:v", str(frames_out), "-t", f"{duration:.3f}",
            "-vf", vf, "-r", str(fps), "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out)]


def retime_clip_cmd(src: Path, target_dur: float, out: Path, w: int, h: int,
                    fps: int = FPS, force_loop: bool = False) -> list[str]:
    """Video REAL de Flow (Veo ~8s fijos) re-temporalizado a la duración de la
    narración con setpts (patrón hans-n8n / AI-Content-Automation-Engine).
    duration_out = duration_src * factor ⇒ factor = target/src:
    factor>1 ralentiza (slow-mo cinemático), factor<1 acelera. Se limita a
    [0.5, FACTOR_MAX] y se recorta con -t. Audio original eliminado (la voz
    es nuestra).
    INT-077 pacing estricto (fin del corte en seco a mitad de frase):
    - Si target > src×FACTOR_MAX (p. ej. 11.8s de voz sobre 7.6s de Veo):
      el clip se ENBUCLA (-stream_loop -1) y el factor se calcula POR
      SEGMENTO sobre n_loops = ceil(target/src) ⇒ siempre ≤ FACTOR_MAX y el
      video alcanza la narración completa sin slow-mo ridículo.
    - force_loop=True (remediación post-render): enbucla SIEMPRE a velocidad
      natural y deja que -t recorte — salva también el caso de
      probe_duration fallido (factor 1.0) y el cache/sidecar rancio."""
    src_dur = probe_duration(src)
    n_loops = 1
    if src_dur > 0.3 and target_dur > src_dur * FACTOR_MAX:
        n_loops = max(int(math.ceil(target_dur / src_dur)), 1)
    factor = (target_dur / (src_dur * n_loops)) if (src_dur > 0.3 and target_dur > 0.3) else 1.0
    factor = max(0.5, min(FACTOR_MAX, factor))
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,"
          f"crop={w * 2}:{h * 2},setpts=PTS*{factor:.6f},fps={fps},format=yuv420p")
    # -frames:v corta por CONTEO exacto de frames: -t solo deja pasar frames
    # extra de la cola del encoder (medido: +0.37s con fps=30) — el conteo es
    # determinista ⇒ duración del clip = N/fps, milimétrica de verdad.
    frames_out = max(int(math.ceil(target_dur * fps)), 1)
    cmd = ["ffmpeg", "-y"]
    if force_loop or n_loops > 1:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", str(src), "-vf", vf, "-an",
            "-frames:v", str(frames_out),
            "-t", f"{target_dur:.3f}", "-r", str(fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out)]
    return cmd


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
                        transition_pad: float = 0.0,
                        scene_gap: float | None = None) -> list[Path]:
    """Renderiza el clip de cada escena, 2 en paralelo.

    - Escena avatar con video REAL de Flow (flow_videos[i]): lip-sync v2v
      (INT-075) + retime setpts a la duración de la narración (INT-077 con
      bucle si el audio excede el cap de slow-mo).
    - Escena product_broll (scenes[i].type/meta.type): Ken Burns zoompan sobre
      la imagen de producto con solo TTS en off — NUNCA lip-sync facial.
    - Sin video de Flow: Ken Burns sobre la imagen (fail-open clásico).
    - transition_pad añade margen a los clips NO finales para compensar el
      solape xfade, y scene_gap (default VOICE_GAP=tts_step.GAP) compensa la
      pausa de voz que build_full_track inserta entre escenas ⇒ la duración
      del master silencioso coincide MILIMÉTRICamente con voice_full.wav y
      el mux -shortest jamás corta la narración.
    - Reutilización idempotente: clip válido con mismo source y misma
      duración objetivo se salta (ver _clip_cache_ok).
    - Verificación milimétrica post-render: cada clip se mide con ffprobe; si
      quedó más corto que su narración (cache rancio, probe del src fallido,
      v2v acortado…) se re-renderiza UNA vez con bucle forzado y el resultado
      queda registrado en el sidecar (fitted/measured)."""
    proj_dir = OUTPUT_DIR / project["id"]
    clips_dir = proj_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    w, h = (SHORT_W, SHORT_H) if project["format"] == "short" else (LONG_W, LONG_H)
    n_scenes = len(scenes)
    gap = VOICE_GAP if scene_gap is None else max(float(scene_gap), 0.0)

    async def one(i: int) -> Path:
        if is_cancelled and is_cancelled():
            raise asyncio.CancelledError("cancelado")
        img = scenes[i].get("image_path") or ""
        out = clips_dir / f"clip_{i:02d}.mp4"
        dur = max(durations[i], 1.0)
        not_final = i < n_scenes - 1
        pad = transition_pad if not_final else 0.0
        fv = (flow_videos or {}).get(i)
        fv_ok = bool(fv) and Path(str(fv)).exists()
        mode = scene_render_mode(scenes[i], fv_ok)
        has_fv = fv_ok and mode == "flow_lipsync"
        if mode == "broll_zoompan":
            # B-roll: imagen de producto + zoompan; el video de Flow (si lo
            # hubiera) se ignora a propósito — solo TTS en off.
            src = Path(img)
            target = dur + 0.05 + gap + pad if not_final else dur + 0.05
        elif has_fv:
            src = Path(str(fv))
            # la escena FINAL no lleva gap: build_full_track no apadea el
            # último audio ⇒ target = dur exacto (mux -shortest sin recorte)
            target = dur + gap + pad if not_final else dur
        else:
            src = Path(img)
            target = dur + 0.05 + gap + pad if not_final else dur + 0.05
        if _clip_cache_ok(out, src, target):
            if on_progress:
                await on_progress(i + 1, n_scenes, None)
            return out
        src_use = src
        if has_fv:
            # INT-075: lip-sync VIDEO-to-VIDEO del clip de Flow con el audio
            # TTS de la escena, ANTES del retime/masterizado. Fail-open: si el
            # Space falla se sigue con el video original (render nunca se rompe).
            a_path = str(scenes[i].get("audio_path") or "").strip()
            if a_path and Path(a_path).is_file() and avatar_motion.v2v_enabled():
                v2v_out = clips_dir / f"lipsync_{i:02d}.mp4"
                try:
                    res = await avatar_motion.lipsync_video_to_video(
                        src, Path(a_path), v2v_out)
                    if res.get("ok") and Path(res["video"]).is_file():
                        src_use = Path(res["video"])
                        log.info("clip %d: lip-sync v2v OK (%s)", i, res.get("space"))
                    else:
                        log.warning("clip %d: v2v fail-open: %s",
                                    i, str(res.get("error"))[:120])
                except Exception as e:  # noqa: BLE001
                    log.warning("clip %d: v2v error (%s) — sin lip-sync",
                                i, str(e)[:120])
        if mode == "broll_zoompan" or not has_fv:
            cmd = scene_clip_cmd(src, target, out, w, h,
                                 zoom_dir=1 if i % 2 == 0 else -1)
        else:
            cmd = retime_clip_cmd(src_use, target, out, w, h)
        p = await asyncio.to_thread(lambda: _run_ffmpeg(cmd))
        if p.returncode != 0:
            log.error("clip %d: %s", i, p.stderr[-300:])
            raise RuntimeError(f"Error renderizando escena {i + 1}")
        # INT-077 · verificación milimétrica: el clip debe durar ≥ target-tol.
        # Si quedó corto (probe del src fallido, cap de factor, v2v acortado,
        # cache rancio) se re-renderiza UNA vez con bucle forzado.
        fitted, measured = True, 0.0
        try:
            measured = await asyncio.to_thread(lambda: probe_duration(out))
            fitted = measured >= target - CLIP_TOL
        except Exception:  # noqa: BLE001
            fitted = False
        if not fitted:
            log.warning("clip %d: %.2fs < target %.2fs — remediando con bucle",
                        i, measured, target)
            if mode == "broll_zoompan" or not has_fv:
                cmd_fix = scene_clip_cmd(src, target, out, w, h, zoom_dir=1)
            else:
                cmd_fix = retime_clip_cmd(src_use, target, out, w, h,
                                          force_loop=True)
            p2 = await asyncio.to_thread(lambda: _run_ffmpeg(cmd_fix))
            if p2.returncode == 0:
                try:
                    measured = await asyncio.to_thread(lambda: probe_duration(out))
                    fitted = measured >= target - CLIP_TOL
                except Exception:  # noqa: BLE001
                    fitted = False
        if not fitted:
            log.warning("clip %d: pacing no verificado (%.2fs/%.2fs) — "
                        "el QA final lo reportará", i, measured, target)
        try:  # sidecar para reutilización exacta en re-runs + observabilidad
            out.with_suffix(".json").write_text(json.dumps(
                {"src": str(src), "dur": round(target, 3),
                 "measured": round(measured, 3), "fitted": bool(fitted)}))
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
    """Une video + voz + música (con ducking automático sobre la voz).
    v2.19: la pista elegida queda registrada en music_track.json — antes
    era imposible saber qué música llevó cada video (observabilidad §28)."""
    proj_dir = OUTPUT_DIR / project["id"]
    music = _pick_music()
    out = proj_dir / "video_raw.mp4"
    (proj_dir / "music_track.json").write_text(json.dumps(
        {"track": music.name if music else None, "ducking": bool(music)},
        ensure_ascii=False), encoding="utf8")

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
    """Quema los subtítulos ASS estilo TikTok/Hormozi sobre el video final.
    v2.19: el resultado queda REGISTRADO en subs_status.json — antes el
    fallback «copiar raw sin subtítulos» era silencioso (degradación
    invisible que llegaba a ready/publish)."""
    proj_dir = OUTPUT_DIR / project["id"]
    words = json.loads(Path(words_path).read_text())
    if not words:
        import shutil
        final = proj_dir / f"{project['id']}_final.mp4"
        shutil.copy(video_raw, final)
        (proj_dir / "subs_status.json").write_text(json.dumps(
            {"burned": False,
             "reason": "words.json vacío — copiado sin subtítulos"},
            ensure_ascii=False), encoding="utf8")
        return final

    ass_path = proj_dir / "subs.ass"
    w, h = (SHORT_W, SHORT_H) if project["format"] == "short" else (LONG_W, LONG_H)
    # estilo de subtítulo elegible desde el dashboard (meta.subtitle_style):
    # shorts (INT-021: Montserrat ExtraBold + contraste dinámico, default)
    # / hormozi (amarillo gigante) / tiktok (blanco) / karaoke (lima)
    sub_style = ((project.get("meta") or {}).get("subtitle_style")
                 or "shorts")
    # INT-021: brillo medio REAL de una muestra del raw (ffmpeg signalstats
    # YAVG) alimenta la paleta de contraste dinámico. Pasa por _run_ffmpeg
    # (hermético en baterías) y su fallback interno es 0.5 ante CUALQUIER
    # fallo — el quemado nunca depende de esta medición.
    avg_bright = typo_mod.estimate_video_brightness(video_raw,
                                                    runner=_run_ffmpeg)
    ass_path.write_text(
        subs_mod.build_ass(words, w, h, style=sub_style,
                           avg_brightness=avg_bright),
        encoding="utf8")

    final = proj_dir / f"{project['id']}_final.mp4"
    sub_filter = f"ass={ass_path.as_posix().replace(':', '\\\\:')}"
    # INT-021: fontsdir hace que libass resuelva la Montserrat ExtraBold
    # embarcada (matching por familia ID1, verificado empíricamente con A/B
    # de MD5 de fotogramas — CONTEXTO INT-021 §3). Sin fontsdir el estilo
    # degradaría en silencio a la fuente por defecto del sistema.
    if typo_mod.FONT_DIR.is_dir():
        sub_filter += (f":fontsdir="
                       f"{typo_mod.FONT_DIR.as_posix().replace(':', '\\\\:')}")
    # INT-012: en 4K (2160x3840) libass+libx264 «medium» superó los 900 s y el
    # TimeoutExpired — no capturado — tumbaba TODO el pipeline aunque el resto
    # del render fuera válido. Dos mitigaciones quirúrgicas: (1) preset
    # veryfast, el mismo que ya usan kenburns/transitions en este módulo
    # (típicamente 3-5× más rápido en 4K con coste de calidad marginal a CRF
    # 20); (2) el timeout se captura y se degrada por el MISMO camino honesto
    # que un rc != 0 (copia sin subtítulos + subs_status.json → el QA final
    # la reporta como warn; jamás un ready silencioso con degradación).
    cmd = ["ffmpeg", "-y", "-i", str(video_raw), "-vf", sub_filter,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "copy", str(final)]
    try:
        p = await asyncio.to_thread(lambda: _run_ffmpeg(cmd, timeout=900))
    except subprocess.TimeoutExpired:
        log.error("subs burn: timeout 900s — degradando a copia sin subtítulos")
        import shutil
        shutil.copy(video_raw, final)
        (proj_dir / "subs_status.json").write_text(json.dumps(
            {"burned": False,
             "reason": "ffmpeg timeout 900s — copiado sin subtítulos"},
            ensure_ascii=False), encoding="utf8")
        return final
    if p.returncode != 0:
        log.error("subs burn: %s", p.stderr[-300:])
        import shutil
        shutil.copy(video_raw, final)
        (proj_dir / "subs_status.json").write_text(json.dumps(
            {"burned": False,
             "reason": f"ffmpeg rc={p.returncode} — copiado sin subtítulos"},
            ensure_ascii=False), encoding="utf8")
    else:
        (proj_dir / "subs_status.json").write_text(json.dumps(
            {"burned": True, "reason": "ok"},
            ensure_ascii=False), encoding="utf8")

    # INT-055: Overlay de Badge de Conversión E-Commerce (Rating, Descuento, Envío)
    badge_cfg = (project.get("meta") or {}).get("ecommerce_badge")
    if project.get("mode") == "product" or badge_cfg:
        try:
            from services.ecommerce_overlays import generate_ecommerce_badge, build_ecommerce_ffmpeg_filter
            b_type = (badge_cfg.get("type") if isinstance(badge_cfg, dict) else badge_cfg) or "rating"
            badge_png = proj_dir / f"badge_{b_type}.png"
            generate_ecommerce_badge(badge_type=b_type, out_path=badge_png)

            overlay_filter = build_ecommerce_ffmpeg_filter(badge_png, start_sec=0.5, duration_sec=6.0, position="top")
            badged_video = proj_dir / f"{project['id']}_badged.mp4"
            badge_cmd = [
                "ffmpeg", "-y", "-i", str(final), "-i", str(badge_png),
                "-filter_complex", f"[0:v][1:v]{overlay_filter}[v]",
                "-map", "[v]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "copy", str(badged_video)
            ]
            pb = await asyncio.to_thread(lambda: _run_ffmpeg(badge_cmd, timeout=300))
            if pb.returncode == 0 and badged_video.is_file():
                import shutil
                shutil.move(badged_video, final)
        except Exception as e_badge:
            log.warning("ecommerce badge overlay falló: %s", e_badge)

    # INT-058: Overlay de Presentador Flotante (Circle PiP Avatar estilo HeyGen / Synthesia)
    meta = project.get("meta") or {}
    avatar_id = project.get("avatar_id") or meta.get("avatar_id")
    pip_cfg = meta.get("circle_avatar_pip")
    if avatar_id and pip_cfg:
        try:
            import database as db
            from services.avatar_pip import create_circle_avatar, build_pip_overlay_filter
            av = db.get_avatar(avatar_id)
            if av and av.get("image_path") and Path(av["image_path"]).is_file():
                b_color = "cyan"
                pos = "bottom_right"
                if isinstance(pip_cfg, dict):
                    b_color = pip_cfg.get("border_color", "cyan")
                    pos = pip_cfg.get("position", "bottom_right")
                elif isinstance(pip_cfg, str) and pip_cfg in ("cyan", "gold", "emerald", "purple", "white"):
                    b_color = pip_cfg

                pip_png = proj_dir / f"avatar_{avatar_id}_circle.png"
                create_circle_avatar(Path(av["image_path"]), diameter=320, border_color=b_color, output_path=pip_png)

                pip_filter = build_pip_overlay_filter(pip_png, position=pos)
                pip_video = proj_dir / f"{project['id']}_pip.mp4"
                pip_cmd = [
                    "ffmpeg", "-y", "-i", str(final), "-i", str(pip_png),
                    "-filter_complex", f"[0:v][1:v]{pip_filter}[v]",
                    "-map", "[v]", "-map", "0:a?",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-c:a", "copy", str(pip_video)
                ]
                pb_pip = await asyncio.to_thread(lambda: _run_ffmpeg(pip_cmd, timeout=300))
                if pb_pip.returncode == 0 and pip_video.is_file():
                    import shutil
                    shutil.move(pip_video, final)
        except Exception as e_pip:
            log.warning("circle avatar pip overlay falló: %s", e_pip)

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
    """Pista de fondo aleatoria entre las disponibles en data/music.
    (antes devolvía SIEMPRE tracks[0] alfabéticamente: todos los videos
    salían con la misma canción — hallazgo de la auditoría externa)."""
    from config import MUSIC_DIR
    tracks = sorted(MUSIC_DIR.glob("*.mp3")) + sorted(MUSIC_DIR.glob("*.wav"))
    return random.choice(tracks) if tracks else None


def cleanup_intermediates(project_id: str) -> int:
    """Libera el disco tras un render exitoso: borra los artefactos
    intermedios regenerables (segmentos Ken Burns pre-concat, video sin
    audio, video pre-subtítulos, listas concat). Conserva lo valioso:
    el MP4 final, imágenes de escena, assets Flow, sidecars .json de clips
    (reutilización idempotente) y audio TTS. Devuelve bytes liberados."""
    proj_dir = OUTPUT_DIR / project_id
    freed = 0
    targets: list[Path] = []
    clips_dir = proj_dir / "clips"
    if clips_dir.is_dir():
        targets += list(clips_dir.glob("*.mp4"))
    targets += [proj_dir / name for name in
                ("video_silent.mp4", "video_raw.mp4", "concat.txt")]
    final = proj_dir / f"{project_id}_final.mp4"
    for f in targets:
        try:
            if f.is_file() and final.is_file():  # solo si el final existe
                freed += f.stat().st_size
                f.unlink()
        except OSError as e:  # noqa: PERF203
            log.warning("cleanup %s: %s", f.name, e)
    if freed:
        log.info("cleanup %s: %.1f MB liberados", project_id, freed / 1e6)
    return freed

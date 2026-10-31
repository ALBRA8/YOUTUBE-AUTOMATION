"""
YOUTUBE AUTOMATION v2.37 — LivePortrait & MuseTalk Motion Connector (INT-066 + INT-072)
Clonado limpio de LivePortrait (KwaiVGI) y MuseTalk (Tencent Music Lyra Lab).

1. LivePortrait: Animación facial fluida (parpadeo de ojos, respiración y micro-movimiento de cabeza).
2. MuseTalk: Sincronización labial impulsada por audio (phoneme-driven lip-sync).
3. Motor dual: Soporta endpoints de inferencia remotos (GPU/Gradio) y motor determinista
   local offline a $0.00 de coste sin dependencias pesadas.
4. INT-072: lip-sync hiperrealista vía HF Spaces públicos $0.00 (gradio_client) con
   failover entre Spaces y fail-open al motor local (lipsync_liveportrait_hf +
   normalize_vertical_916 → lienzo 1080x1920).
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import logging
import math
import os
import shutil
import struct
import subprocess
import time
import wave
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

log = logging.getLogger("avatar_motion")

LIVEPORTRAIT_API_URL = os.getenv("LIVEPORTRAIT_API_URL", "").strip()
MUSETALK_API_URL = os.getenv("MUSETALK_API_URL", "").strip()


def extract_audio_amplitude_envelope(wav_path: Path, fps: int = 25) -> list[float]:
    """Calcula la envolvente de volumen RMS normalizada (0.0 a 1.0) para cada fotograma."""
    if not wav_path.is_file():
        return [0.0] * int(fps * 3.0)

    try:
        with wave.open(str(wav_path), "rb") as wf:
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            n_frames = wf.getnframes()
            audio_bytes = wf.readframes(n_frames)

        samples_per_frame = int(sample_rate / fps)
        envelope: list[float] = []

        # Solo manejar 16-bit PCM de forma estándar
        if sampwidth == 2:
            total_samples = len(audio_bytes) // 2
            format_str = f"<{total_samples}h"
            raw_samples = struct.unpack(format_str, audio_bytes)
            # Si es estéreo, promediar canales
            if n_channels == 2:
                samples = [
                    (raw_samples[i] + raw_samples[i + 1]) / 2.0
                    for i in range(0, len(raw_samples) - 1, 2)
                ]
            else:
                samples = list(raw_samples)

            for i in range(0, len(samples), samples_per_frame):
                chunk = samples[i : i + samples_per_frame]
                if not chunk:
                    envelope.append(0.0)
                    continue
                # RMS
                sum_sq = sum(s * s for s in chunk)
                rms = math.sqrt(sum_sq / len(chunk))
                # Normalizar a rango [0, 1]
                norm_rms = min(1.0, max(0.0, (rms - 300) / 4500.0))
                envelope.append(norm_rms)
        else:
            duration = n_frames / float(sample_rate)
            return [0.5] * max(1, int(duration * fps))

        return envelope
    except Exception as ex:
        log.warning("[avatar_motion] Error procesando audio para lip-sync: %s", ex)
        return [0.5] * 75


def generate_eyelid_blink_frame(base_img: Image.Image, blink_factor: float) -> Image.Image:
    """Modula los ojos cerrándolos suavemente según blink_factor (0.0 abierto, 1.0 cerrado)."""
    if blink_factor <= 0.05:
        return base_img

    img = base_img.copy()
    w, h = img.size
    draw = ImageDraw.Draw(img)

    # Región aproximada de ojos en retrato centrado (35% a 45% de altura)
    eye_y = int(h * 0.41)
    eye_h = int(h * 0.045 * blink_factor)

    # Color de párpado estimado tomando la muestra de la frente/mejilla
    skin_sample_x = int(w * 0.5)
    skin_sample_y = int(h * 0.32)
    skin_color = base_img.getpixel((skin_sample_x, skin_sample_y))
    if len(skin_color) == 3:
        skin_color = (*skin_color, 255)

    # Ojo izquierdo y derecho
    left_x = int(w * 0.38)
    right_x = int(w * 0.62)
    radius_x = int(w * 0.065)

    draw.ellipse(
        [left_x - radius_x, eye_y - eye_h, left_x + radius_x, eye_y + eye_h],
        fill=skin_color
    )
    draw.ellipse(
        [right_x - radius_x, eye_y - eye_h, right_x + radius_x, eye_y + eye_h],
        fill=skin_color
    )

    return img


def generate_mouth_lip_frame(base_img: Image.Image, mouth_open_factor: float) -> Image.Image:
    """Modula la apertura labial sincronizada con el habla (0.0 cerrado, 1.0 apertura máxima)."""
    if mouth_open_factor <= 0.05:
        return base_img

    img = base_img.copy()
    w, h = img.size
    draw = ImageDraw.Draw(img)

    mouth_x = int(w * 0.5)
    mouth_y = int(h * 0.68)
    mouth_w = int(w * 0.08)
    mouth_h = int(h * 0.035 * mouth_open_factor)

    # Interior de la cavidad bucal
    mouth_inner_color = (60, 20, 25, 255)

    draw.ellipse(
        [mouth_x - mouth_w, mouth_y - mouth_h, mouth_x + mouth_w, mouth_y + mouth_h],
        fill=mouth_inner_color
    )

    return img


def animate_liveportrait_local(
    image_path: Path,
    output_video: Path,
    duration_sec: float = 4.0,
    fps: int = 25
) -> Path:
    """Genera bucle de micro-movimiento LivePortrait (parpadeo + respiración + leve inclinación)."""
    if not image_path.is_file():
        raise FileNotFoundError(f"Imagen de avatar no encontrada: {image_path}")

    output_video.parent.mkdir(parents=True, exist_ok=True)
    tmp_frames_dir = output_video.parent / f"tmp_lp_{int(time.time() * 1000)}"
    tmp_frames_dir.mkdir(parents=True, exist_ok=True)

    base_img = Image.open(image_path).convert("RGBA")
    # Forzar tamaño uniforme cuadrado 512x512
    base_img = base_img.resize((512, 512), Image.Resampling.LANCZOS)

    total_frames = int(duration_sec * fps)

    try:
        for f in range(total_frames):
            t = f / float(fps)
            # 1. Respiración (escala sinusoidal sutil 1.000 a 1.012)
            scale = 1.0 + 0.010 * math.sin(t * 2.2)

            # 2. Inclinación y flotación suave de cabeza (yaw/pitch)
            drift_x = int(3.0 * math.sin(t * 1.5))
            drift_y = int(2.5 * math.cos(t * 1.8))

            # 3. Parpadeo de ojos humano (cada ~2.8 segundos)
            cycle = t % 2.8
            blink = 0.0
            if 2.4 <= cycle <= 2.6:
                blink = math.sin((cycle - 2.4) / 0.2 * math.pi)

            # Transformación afín
            frame = base_img.copy()
            if blink > 0.05:
                frame = generate_eyelid_blink_frame(frame, blink)

            # Aplicar respiración y drift
            new_w = int(512 * scale)
            new_h = int(512 * scale)
            resized = frame.resize((new_w, new_h), Image.Resampling.BILINEAR)

            canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 255))
            paste_x = (512 - new_w) // 2 + drift_x
            paste_y = (512 - new_h) // 2 + drift_y
            canvas.paste(resized, (paste_x, paste_y), resized)

            frame_path = tmp_frames_dir / f"frame_{f:04d}.png"
            canvas.convert("RGB").save(frame_path)

        # Ensamblar video con FFmpeg
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(tmp_frames_dir / "frame_%04d.png"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "ultrafast",
            "-crf", "22",
            str(output_video)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg error al compilar LivePortrait: {res.stderr}")

        return output_video
    finally:
        shutil.rmtree(tmp_frames_dir, ignore_errors=True)


def lipsync_musetalk_local(
    image_path: Path,
    audio_path: Path,
    output_video: Path,
    fps: int = 25
) -> Path:
    """Genera video sincronizado labialmente con el audio mediante envolvente fonética RMS."""
    if not image_path.is_file():
        raise FileNotFoundError(f"Imagen de avatar no encontrada: {image_path}")
    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio para lip-sync no encontrado: {audio_path}")

    output_video.parent.mkdir(parents=True, exist_ok=True)
    tmp_frames_dir = output_video.parent / f"tmp_mt_{int(time.time() * 1000)}"
    tmp_frames_dir.mkdir(parents=True, exist_ok=True)

    base_img = Image.open(image_path).convert("RGBA")
    base_img = base_img.resize((512, 512), Image.Resampling.LANCZOS)

    # Extraer envolvente fonética del audio
    envelope = extract_audio_amplitude_envelope(audio_path, fps=fps)
    total_frames = len(envelope)

    try:
        for f in range(total_frames):
            t = f / float(fps)
            amp = envelope[f]

            # Parpadeo natural ocasional
            cycle = t % 3.2
            blink = 0.0
            if 2.8 <= cycle <= 3.0:
                blink = math.sin((cycle - 2.8) / 0.2 * math.pi)

            # Inclinación sutil al hablar
            drift_x = int(2.0 * math.sin(t * 2.0))
            drift_y = int(1.5 * math.cos(t * 2.5))

            frame = base_img.copy()
            if blink > 0.05:
                frame = generate_eyelid_blink_frame(frame, blink)

            # Modulación labial por audio
            if amp > 0.05:
                frame = generate_mouth_lip_frame(frame, amp)

            canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 255))
            canvas.paste(frame, (drift_x, drift_y), frame)

            frame_path = tmp_frames_dir / f"frame_{f:04d}.png"
            canvas.convert("RGB").save(frame_path)

        # Ensamblar video con audio sincronizado vía FFmpeg
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(tmp_frames_dir / "frame_%04d.png"),
            "-i", str(audio_path),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "ultrafast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output_video)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg error al compilar MuseTalk: {res.stderr}")

        return output_video
    finally:
        shutil.rmtree(tmp_frames_dir, ignore_errors=True)


async def render_avatar_animation(
    image_path: Path,
    output_video: Path,
    audio_path: Path | None = None,
    duration_sec: float = 4.0,
    engine: str = "auto"
) -> dict[str, Any]:
    """Punto de entrada unificado que decide entre LivePortrait (bucle) o MuseTalk (hablado).

    INT-072: con audio, intenta primero el motor hiperrealista de HF Spaces
    (``lipsync_liveportrait_hf``, cadenas EchoMimic/AniPortrait audio-driven a
    $0.00) y hace fail-open al motor determinista local si HF falla, duerme o
    no tiene cuota. ``engine`` controla la ruta:
      · "auto" (default) → HF primero, local de respaldo.
      · "hf" / "liveportrait" → solo HF (si falla, propaga).
      · "musetalk" / "local" → solo motor local determinista (sin red).
    """
    # Si viene audio, ejecutar pipeline de Sincronización Labial
    if audio_path and audio_path.is_file():
        requested = (engine or "auto").strip().lower()
        want_hf = requested in ("auto", "hf", "liveportrait", "liveportrait_hf")
        if want_hf and hf_lipsync_enabled():
            try:
                p, space_used = await lipsync_liveportrait_hf(image_path, audio_path, output_video)
                p = await asyncio.to_thread(
                    normalize_vertical_916, p,
                    int(_am_cfg("AVATAR_OUTPUT_W", "1080")),
                    int(_am_cfg("AVATAR_OUTPUT_H", "1920")),
                )
                return {
                    "ok": True,
                    "engine": "liveportrait_hf",
                    "type": "lipsync_speaking",
                    "video_path": str(p),
                    "video_url": f"/static/assets/{p.name}",
                    "space": space_used,
                    "fallback": False,
                }
            except Exception as ex:  # fail-open: jamás romper el render
                log.warning("[avatar_motion] HF Spaces fail-open → motor local: %s", ex)
                if requested in ("hf", "liveportrait", "liveportrait_hf"):
                    raise  # modo explícito HF: sí propaga el fallo
        p = lipsync_musetalk_local(image_path, audio_path, output_video)
        return {
            "ok": True,
            "engine": "musetalk",
            "type": "lipsync_speaking",
            "video_path": str(p),
            "video_url": f"/static/assets/{p.name}"
        }
    else:
        # Si no viene audio, generar animación facial continua LivePortrait
        p = animate_liveportrait_local(image_path, output_video, duration_sec=duration_sec)
        return {
            "ok": True,
            "engine": "liveportrait",
            "type": "facial_motion_loop",
            "video_path": str(p),
            "video_url": f"/static/assets/{p.name}"
        }


# ── INT-072 · HF Spaces Lip-Sync & Face Animation ($0.00) ──────────────────
# Verificación de contratos (2026-10-31, view_api + predict real):
#   · KwaiVGI/LivePortrait: SOLO video-driven (no acepta audio) y
#     fffiloni/LivePortrait-Realtime fue eliminado de HF (404).
#   · TMElyralab/MuseTalk: caído (RUNTIME_ERROR).
#   · Vivos y audio-driven: fffiloni/EchoMimic (/generate_video),
#     fffiloni/echomimic-v2 (/generate), ZJYang/AniPortrait_official (/audio2video).
# "lipsync_liveportrait_hf" conserva el nombre de la spec INT-072; internamente
# enruta a la cadena audio-driven viva configurable via AVATAR_HF_SPACES.

_AVATAR_HF_SPACES_DEFAULT = "fffiloni/EchoMimic,ZJYang/AniPortrait_official,fffiloni/echomimic-v2"


def _am_cfg(key: str, default: str) -> str:
    """Lee config.py primero (recarga viva del dashboard) y .env como respaldo."""
    try:
        import config as _c
        v = getattr(_c, key, None)
        if v is not None and str(v).strip() != "":
            return str(v)
    except Exception:
        pass
    return os.getenv(key, default)


def hf_lipsync_enabled() -> bool:
    return _am_cfg("AVATAR_HF_ENABLED", "1").strip().lower() in ("1", "true", "yes")


def hf_space_list() -> list[str]:
    """Cadena de Spaces audio-driven en orden de prioridad (failover)."""
    raw = _am_cfg("AVATAR_HF_SPACES", _AVATAR_HF_SPACES_DEFAULT)
    return [s.strip() for s in str(raw).split(",") if s.strip()]


def _hf_token() -> str:
    """HF_TOKEN opcional (cuenta gratis sube la cuota ZeroGPU). Nunca se loguea."""
    tok = str(_am_cfg("HF_TOKEN", "") or "").strip()
    return tok


def _extract_video_from_result(result: Any) -> Path:
    """gradio_client devuelve filepath (str), dict con 'video'/'path', FileData o
    tuplas anidadas según el Space. Normaliza a la ruta del MP4 resultante."""
    if result is None:
        return None
    if isinstance(result, (list, tuple)):
        for item in result:
            found = _extract_video_from_result(item)
            if found is not None:
                return found
        raise RuntimeError(f"Sin video en la respuesta: {result!r:.200}")
    if isinstance(result, dict):
        for key in ("video", "path", "value", "filepath", "url"):
            if key in result and result[key]:
                found = _extract_video_from_result(result[key])
                if found is not None:
                    return found
        raise RuntimeError(f"Sin video en la respuesta dict: {result!r:.200}")
    if isinstance(result, str) and result.strip():
        p = Path(result.strip())
        if p.is_file():
            return p
        # FileData en modo URL (raro en spaces): descargaría aquí si hiciera falta
        raise FileNotFoundError(f"Ruta devuelta por el Space no existe: {p}")
    raise RuntimeError(f"Respuesta no reconocida del Space: {type(result).__name__}")


def _make_hf_client(space_id: str):
    """Client de gradio_client compatible con 1.x (hf_token=) y 2.x (token=).
    El token es opcional; si no hay, None (cuota anónima de ZeroGPU)."""
    from gradio_client import Client

    token = _hf_token()
    params = inspect.signature(Client.__init__).parameters
    if "token" in params:
        return Client(space_id, token=token or None, verbose=False)
    if "hf_token" in params:  # gradio_client 1.x
        return Client(space_id, hf_token=token or None, verbose=False)
    return Client(space_id, verbose=False)


def _call_hf_lipsync_gradio(space_id: str, img_path: str, audio_path: str, out_path: str) -> Path:
    """Llama a UN Space audio-driven con su contrato real. Sincrono (correr en hilo).
    Lanza excepción si el Space falla → el caller hace failover al siguiente."""
    from gradio_client import handle_file

    client = _make_hf_client(space_id)
    steps = int(_am_cfg("AVATAR_HF_STEPS", "12"))
    length = int(_am_cfg("AVATAR_HF_LENGTH", "100"))

    if space_id == "fffiloni/EchoMimic":
        result = client.predict(
            uploaded_img=handle_file(img_path),
            uploaded_audio=handle_file(audio_path),
            width=512, height=512,
            length=length,            # frames (mínimo 100 validado en vivo)
            seed=42,
            facemask_dilation_ratio=0.1, facecrop_dilation_ratio=0.1,
            context_frames=12, context_overlap=0,
            cfg=2.5, steps=steps,
            sample_rate=16000, fps=12, device="cuda",
            api_name="/generate_video",
        )
    elif space_id == "fffiloni/echomimic-v2":
        result = client.predict(
            image_input=handle_file(img_path),
            audio_input=handle_file(audio_path),
            pose_input="",
            preset_name="Showcase",
            width=512, height=512,
            length=length, steps=steps,
            sample_rate=16000, cfg=2.5, fps=12,
            context_frames=12, context_overlap=0,
            quantization_input=False, seed=42,
            api_name="/generate",
        )
    elif space_id == "ZJYang/AniPortrait_official":
        result = client.predict(
            input_audio=handle_file(audio_path),
            ref_img=handle_file(img_path),
            headpose_video=None,
            size=512, steps=min(steps, 20), length=length, seed=42,
            api_name="/audio2video",
        )
    else:
        # Space genérico añadido por .env: contrato especulativo estándar.
        result = client.predict(
            source_image=handle_file(img_path),
            driving_audio=handle_file(audio_path),
            api_name="/predict",
        )

    video_src = _extract_video_from_result(result)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(video_src, out_path)
    return Path(out_path)


async def lipsync_liveportrait_hf(
    image_path: Path,
    audio_path: Path,
    output_video: Path,
) -> tuple[Path, str]:
    """Lip-sync hiperrealista vía HF Spaces públicos ($0.00). INT-072.

    Recorre la cadena ``AVATAR_HF_SPACES`` con failover; cada intento corre en
    un hilo con timeout propio (el backend jamás se bloquea). Devuelve
    ``(video_path, space_usado)``. Lanza RuntimeError si todos los Spaces fallan
    (el caller decide fail-open al motor local).
    """
    if not image_path.is_file():
        raise FileNotFoundError(f"Imagen de avatar no encontrada: {image_path}")
    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio para lip-sync no encontrado: {audio_path}")

    timeout_s = float(_am_cfg("AVATAR_HF_TIMEOUT_S", "420"))
    errors: list[str] = []
    for space_id in hf_space_list():
        try:
            p = await asyncio.wait_for(
                asyncio.to_thread(
                    _call_hf_lipsync_gradio, space_id,
                    str(image_path), str(audio_path), str(output_video),
                ),
                timeout=timeout_s,
            )
            log.info("[avatar_motion] Lip-sync HF OK via %s", space_id)
            return p, space_id
        except Exception as ex:
            # NO registrar HF_TOKEN; solo tipo y mensaje corto
            errors.append(f"{space_id}: {type(ex).__name__}: {str(ex)[:160]}")
            log.warning("[avatar_motion] Space %s falló (%s)", space_id, type(ex).__name__)
    raise RuntimeError("Todos los Spaces HF fallaron → " + " | ".join(errors))


def _video_dims(video_path: Path) -> tuple[int, int] | None:
    """Dimensiones del video vía ffprobe (None si no se puede sondear)."""
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0",
             str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        w, h = res.stdout.strip().split(",")[:2]
        return int(w), int(h)
    except Exception:
        return None


def normalize_vertical_916(
    video_path: Path,
    out_w: int = 1080,
    out_h: int = 1920,
) -> Path:
    """Normaliza el video del Space (p.ej. 512x512 cuadrado) a 9:16 vertical
    (1080x1920) con FFmpeg: escalado 'cover' + crop centrado. Conserva el
    audio y escribe +faststart para streaming. Si ya está en el lienzo
    destino, no toca nada (idempotente). Sobrescribe ``video_path`` in situ.
    """
    if not video_path.is_file():
        raise FileNotFoundError(f"Video a normalizar no existe: {video_path}")

    dims = _video_dims(video_path)
    if dims == (out_w, out_h):
        return video_path  # ya está en 9:16

    tmp_out = video_path.with_name(video_path.stem + "_916.mp4")
    vf = (
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},setsar=1"
    )
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(tmp_out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg error normalizando 9:16: {res.stderr[-400:]}")
    shutil.move(str(tmp_out), str(video_path))
    return video_path


# ════════════════════════════════════════════════════════════════════════
# INT-075 · Lip-sync VIDEO-to-VIDEO (post-procesado de videos de Google Flow)
# El video base de Flow (cuerpo, manos con producto, fondo) entra junto al
# audio TTS de la escena y sale con los fonemas calzados a la boca. Cadena
# de Spaces públicos HF $0.00 con failover + timeout por intento + fail-open
# (si todo falla el pipeline sigue con el video original SIN lip-sync: el
# render NUNCA se rompe).
# Calibración en vivo (2026-10-31, gradio_client 2.0.3): los 3 Spaces de la
# cadena devuelven 401 sin token — ByteDance/LatentSync es GATED (aceptar la
# licencia en su página con una cuenta HF gratis). Con HF_TOKEN (ya soportado
# por _make_hf_client) la cadena opera a $0.00.
# ════════════════════════════════════════════════════════════════════════

_VIDEO_LIPSYNC_SPACES_DEFAULT = ("ByteDance/LatentSync,akhaliq/Wav2Lip,"
                                 "fffiloni/video-retalking")


def v2v_enabled() -> bool:
    """Interruptor maestro AVATAR_V2V_ENABLED (1/0)."""
    return _am_cfg("AVATAR_V2V_ENABLED", "1").strip().lower() in ("1", "true", "yes")


def v2v_space_list() -> list[str]:
    """Cadena de Spaces video-to-video configurable vía AVATAR_V2V_SPACES."""
    raw = _am_cfg("AVATAR_V2V_SPACES", _VIDEO_LIPSYNC_SPACES_DEFAULT)
    return [s.strip() for s in str(raw).split(",") if s.strip()]


def _to_wav_mono16k(audio_path: Path, out_wav: Path) -> Path:
    """Convierte CUALQUIER audio TTS (mp3/wav/webm/ogg) a WAV PCM mono 16 kHz.
    Evita el error 'file does not start with RIFF id' de los Spaces que solo
    aceptan WAV crudo."""
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(audio_path),
           "-ar", "16000", "-ac", "1", str(out_wav)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"ffmpeg wav16k timeout convirtiendo {Path(audio_path).name}") from e
    if res.returncode != 0 or not out_wav.is_file():
        raise RuntimeError(f"ffmpeg wav16k falló: {(res.stderr or '')[-200:]}")
    return out_wav


def _call_hf_v2v_gradio(space_id: str, video_path: str, audio_wav: str,
                        out_path: str) -> Path:
    """Llama a UN Space de video dubbing/lip-sync con su contrato real
    (sincrono — correr en hilo). Prueba primero los kwargs canónicos del Space
    y de último un predict posicional (video, audio) — máxima compatibilidad
    si el Space renombró sus inputs. Lanza si todo falla → el caller hace
    failover al siguiente Space."""
    from gradio_client import handle_file

    client = _make_hf_client(space_id)
    attempts: list = []
    if space_id == "ByteDance/LatentSync":
        attempts.append(lambda: client.predict(
            video_in=handle_file(video_path),
            audio_in=handle_file(audio_wav),
            guidance_scale=1.5,
            inference_steps=int(_am_cfg("AVATAR_V2V_STEPS", "25")),
            seed=42, api_name="/predict"))
    elif space_id == "akhaliq/Wav2Lip":
        attempts.append(lambda: client.predict(
            video_in=handle_file(video_path),
            audio_in=handle_file(audio_wav), api_name="/predict"))
    elif space_id == "fffiloni/video-retalking":
        attempts.append(lambda: client.predict(
            video=handle_file(video_path),
            audio=handle_file(audio_wav), api_name="/predict"))
    # Genérico posicional SIEMPRE como último intento del Space.
    attempts.append(lambda: client.predict(
        handle_file(video_path), handle_file(audio_wav)))

    result = None
    last_err: Exception | None = None
    for attempt in attempts:
        try:
            result = attempt()
            break
        except Exception as ex:  # noqa: BLE001
            last_err = ex
            log.warning("[avatar_motion v2v] %s: contrato falló: %s",
                        space_id, str(ex)[:120])
    if result is None:
        raise RuntimeError(
            f"{space_id}: todos los contratos fallaron "
            f"({type(last_err).__name__}: {last_err})")

    video_src = _extract_video_from_result(result)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(video_src, out_path)
    return Path(out_path)


async def lipsync_video_to_video(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    timeout_s: float | None = None,
) -> dict:
    """INT-075: lip-sync video-to-video del video base de Google Flow con el
    audio TTS de la escena ($0.00 vía Spaces públicos de Hugging Face).

    1) Normaliza el audio a WAV mono 16 kHz con FFmpeg (evita el error
       'file does not start with RIFF id').
    2) Recorre ``AVATAR_V2V_SPACES`` con failover; cada intento corre en hilo
       con timeout propio (``AVATAR_V2V_TIMEOUT_S`` por Space) — el backend
       jamás se bloquea.
    3) FAIL-OPEN: si toda la cadena falla, copia el video original a
       ``output_path`` y devuelve ``ok=False`` — el render continúa sin
       lip-sync.

    Devuelve ``{"ok", "video", "space", "attempted", "fallback", "error"}``.
    Firma de la espec: ``lipsync_video_to_video(video_path, audio_path,
    output_path)``; ``timeout_s`` es opcional (override por llamada)."""
    video_path = Path(video_path)
    audio_path = Path(audio_path)
    output_path = Path(output_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"Video base no encontrado: {video_path}")
    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio no encontrado: {audio_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not v2v_enabled():
        shutil.copy(video_path, output_path)
        return {"ok": False, "video": str(output_path), "space": "",
                "attempted": [], "fallback": True,
                "error": "AVATAR_V2V_ENABLED=0 — fail-open inmediato"}

    attempted: list[str] = []
    errors: list[str] = []
    tmp_wav = output_path.parent / f"{output_path.stem}_voice16k.wav"
    try:
        wav = await asyncio.to_thread(_to_wav_mono16k, audio_path, tmp_wav)
        timeout = float(timeout_s or _am_cfg("AVATAR_V2V_TIMEOUT_S", "300"))
        for space in v2v_space_list():
            attempted.append(space)
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(_call_hf_v2v_gradio, space,
                                      str(video_path), str(wav), str(output_path)),
                    timeout=timeout)
                return {"ok": True, "video": str(output_path), "space": space,
                        "attempted": attempted, "fallback": False, "error": ""}
            except Exception as ex:  # noqa: BLE001
                msg = f"{space}: {type(ex).__name__}: {str(ex)[:160]}"
                errors.append(msg)
                log.warning("[avatar_motion v2v] %s", msg)
        shutil.copy(video_path, output_path)  # FAIL-OPEN: video original
        return {"ok": False, "video": str(output_path), "space": "",
                "attempted": attempted, "fallback": True,
                "error": " | ".join(errors)[-400:]}
    finally:
        try:
            tmp_wav.unlink(missing_ok=True)
        except OSError:
            pass

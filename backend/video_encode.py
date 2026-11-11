# -*- coding: utf-8 -*-
"""P1-2 · Módulo NEUTRAL de codificación de video (única fuente de verdad).

get_video_encoder() vive aquí para que pipeline/ y services/ lo importen
sin dependencias cruzadas entre subpaquetes. pipeline/video.py re-exporta
get_video_encoder y _probe_nvenc por compatibilidad (tests existentes).

Política (P2-2 + P1-2):
  · final=True  → UNA sola codificación de calidad del entregable:
                  VIDEO_CRF (default 18) + VIDEO_PRESET (default veryfast,
                  heredado de RENDER_X264_PRESET) + -movflags +faststart
                  (streaming inmediato en el panel, P2-5). NVENC si
                  ENABLE_NVENC y h264_nvenc responde (p4 + -cq).
  · final=False → intermedios casi sin pérdida: INTERMEDIATE_CRF (10) +
                  INTERMEDIATE_PRESET (ultrafast). Sin faststart (se
                  re-codifican después; el moov da igual).

Tabla de rutas — qué produce cada flujo (auditoría P1-2):
  pipeline/orchestrator.py (Flow/escenas):
      scene_clip_cmd            → intermedio (helper False)  [pipeline/video.py]
      concat + burn_subtitles   → FINAL (helper True)        [pipeline/video.py]
  services/pipeline_orchestrator.py (ensamblador de servicios):
      video_assembler.build_scene_cmd  → intermedio norm/ (helper False)
      video_assembler.build_burn_cmd   → FINAL subtítulos quemados (helper True)
  Flujos de avatar:
      avatar_motion.animate_liveportrait_local → FINAL avatar (helper True)
      avatar_motion.lipsync_musetalk_local     → FINAL avatar (helper True)
      avatar_motion.normalize_vertical_916     → intermedio (helper False)
      avatar_pip.apply_pip_to_video            → FINAL (helper True)
  Flujos UGC / viral:
      ugc_hooks.stitch_hook_variants           → FINAL (helper True)
      viral_clipper._ffmpeg_render             → FINAL (helper True)
      broll_overlay.generate_synthetic_broll   → intermedio (helper False)
  video_retimer.retime_video                   → intermedio con ajuste fino
      propio (crf 14 / preset slow, «casi sin pérdida» estricto) — su salida
      siempre se re-codifica; se documenta y queda exento del helper.
"""
from __future__ import annotations

import subprocess

# Binding a import — MISMA semántica que tenía pipeline/video.py; los tests
# parchean backend.video_encode.ENABLE_NVENC (única identidad de módulo).
from config import (ENABLE_NVENC, INTERMEDIATE_CRF, INTERMEDIATE_PRESET,
                    VIDEO_CRF, VIDEO_PRESET)


_NVENC_AVAILABLE: bool | None = None


def _probe_nvenc() -> bool:
    """Evalúa si el encoder por hardware NVENC (h264_nvenc) está activo y funcional."""
    global _NVENC_AVAILABLE
    if _NVENC_AVAILABLE is not None:
        return _NVENC_AVAILABLE
    if not ENABLE_NVENC:
        _NVENC_AVAILABLE = False
        return False
    try:
        p = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             "testsrc=duration=0.1:size=64x64:rate=10",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, timeout=5
        )
        _NVENC_AVAILABLE = (p.returncode == 0)
    except Exception:  # noqa: BLE001
        _NVENC_AVAILABLE = False
    return _NVENC_AVAILABLE


def get_video_encoder(final: bool = True) -> list[str]:
    """Devuelve los parámetros ffmpeg de codificación de video.

    Intermedios (final=False): casi sin pérdida con INTERMEDIATE_CRF (default 10)
    y preset ultrafast (o NVENC p1 si está disponible). Final (final=True): codificación única de calidad con
    VIDEO_PRESET y VIDEO_CRF (o NVENC p4), añadiendo -movflags +faststart para
    streaming inmediato (P2-5). Lectura DINÁMICA de config (tests y .env)."""
    if not final:
        if _probe_nvenc():
            return ["-c:v", "h264_nvenc", "-preset", "p1",
                    "-cq", str(INTERMEDIATE_CRF)]
        return ["-c:v", "libx264",
                "-preset", str(INTERMEDIATE_PRESET),
                "-crf", str(INTERMEDIATE_CRF)]
    if _probe_nvenc():
        return ["-c:v", "h264_nvenc", "-preset", "p4",
                "-cq", str(VIDEO_CRF), "-movflags", "+faststart"]
    return ["-c:v", "libx264", "-preset", str(VIDEO_PRESET),
            "-crf", str(VIDEO_CRF), "-movflags", "+faststart"]

"""
YOUTUBE AUTOMATION — QA Forense de Medios (Magic Bytes y Detección de Silencios)
================================================================================
Procedencia: CHAT-X (src/lib/qa-forense.ts).
Verifica la firma binaria real de los archivos antes de pasarlos a FFmpeg para evitar
que errores HTTP 200 con cuerpo HTML o audios silenciosos rompan el pipeline.
"""
from __future__ import annotations

import os
import struct
from typing import Dict, List, Optional, Tuple

FIRMA_PNG = b"\x89PNG\r\n\x1a\n"
FIRMA_JPEG = b"\xff\xd8\xff"
FIRMA_RIFF = b"RIFF"
FIRMA_WAVE = b"WAVE"


def detect_media_type(buf: bytes) -> str:
    """Detecta el tipo de archivo según sus Magic Bytes reales."""
    if len(buf) < 12:
        return "vacio" if len(buf) == 0 else "texto"
    if buf.startswith(FIRMA_PNG):
        return "png"
    if buf.startswith(FIRMA_JPEG):
        return "jpeg"
    if buf.startswith(FIRMA_RIFF) and buf[8:12] == FIRMA_WAVE:
        return "wav"
    if len(buf) >= 8 and buf[4:8] == b"ftyp":
        return "mp4"

    start_text = buf[:512].strip().lower()
    if start_text.startswith(b"<!doctype html") or start_text.startswith(b"<html") or b"<body" in start_text:
        return "html"
    if start_text.startswith(b"<?xml") or start_text.startswith(b"<svg") or b"<svg" in start_text:
        return "svg"

    try:
        buf[:512].decode("utf-8")
        return "texto"
    except UnicodeDecodeError:
        return "desconocido"


def is_silent_wav(file_path: str, max_samples: int = 200_000, threshold_amp: int = 40) -> Tuple[bool, str]:
    """
    Analiza un archivo WAV PCM 16-bit para detectar si está completamente silencioso.
    Umbral ≈ -58 dBFS (amplitud <= 40).
    Retorna (es_silencioso, detalle).
    """
    if not os.path.isfile(file_path):
        return True, "Archivo no encontrado"
    size = os.path.getsize(file_path)
    if size < 44:
        return True, "Encabezado WAV corrupto o demasiado corto"

    with open(file_path, "rb") as f:
        header = f.read(44)
        if len(header) < 44 or not header.startswith(FIRMA_RIFF) or header[8:12] != FIRMA_WAVE:
            return True, "No es un archivo WAV válido (faltan magic bytes RIFF/WAVE)"

        channels = struct.unpack_from("<H", header, 22)[0] or 1
        bits_per_sample = struct.unpack_from("<H", header, 34)[0] or 16

        if bits_per_sample != 16:
            return False, f"Formato no analizable directamente (bits={bits_per_sample})"

        data = f.read(max_samples * 2)
        if not data:
            return True, "WAV sin datos de audio (payload vacío)"

        num_samples = len(data) // 2
        max_abs = 0
        for i in range(num_samples):
            val = abs(struct.unpack_from("<h", data, i * 2)[0])
            if val > max_abs:
                max_abs = val
            if max_abs > threshold_amp:
                return False, f"Audio con nivel válido (pico={max_abs})"

        if max_abs <= threshold_amp:
            return True, f"Audio silencioso o mudo detectado (amplitud máxima {max_abs} <= {threshold_amp})"

    return False, "Audio analizado correctamente"


def inspect_media_file(file_path: str, expected_type: Optional[str] = None) -> Dict[str, Any]:
    """Inspección forense completa de un archivo de imagen o audio."""
    if not os.path.isfile(file_path):
        return {"ok": False, "error": f"Archivo inexistente: {file_path}", "tipo": "no_existe"}

    size = os.path.getsize(file_path)
    if size == 0:
        return {"ok": False, "error": "Archivo vacío (0 bytes)", "tipo": "vacio"}

    with open(file_path, "rb") as f:
        header_sample = f.read(1024)

    detected = detect_media_type(header_sample)
    if detected == "html":
        return {
            "ok": False,
            "error": "El archivo es una página de error HTML (error de servidor o portal cautivo) guardada con extensión de medio",
            "tipo": "html",
            "bytes": size,
        }

    if expected_type and detected != expected_type:
        return {
            "ok": False,
            "error": f"Firma binaria '{detected}' no coincide con tipo esperado '{expected_type}'",
            "tipo": detected,
            "bytes": size,
        }

    # Si es WAV, verificar si es silencioso
    if detected == "wav":
        silent, detail = is_silent_wav(file_path)
        if silent:
            return {"ok": False, "error": detail, "tipo": "wav", "silencioso": True, "bytes": size}

    return {"ok": True, "tipo": detected, "bytes": size}

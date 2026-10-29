"""
YOUTUBE AUTOMATION v2.26 — Realineación de timestamps Whisper contra silencios reales (INT-070)

Adaptado de estudio-video-ia (scripts/transcribir.py, material aportado por el
usuario; sin fichero LICENSE — se porta el ALGORITMO, no el fichero).

PROBLEMA que resuelve: los timestamps por palabra de faster-whisper se desvían
hasta ~0.8 s junto a las pausas (el modelo reparte el tiempo dentro del segmento,
pero los silencios reales del locutor no coinciden exactamente). En karaoke
palabra-a-palabra (INT-045) ese desfase se VE: la palabra resaltada brilla
mientras la voz calla.

ALGORITMO (port fiel de `realinear`):
  1. Detectar pausas REALES del audio con ffmpeg silencedetect (-38 dB, ≥0.12 s).
  2. Anclar cada pausa real al hueco entre palabras más probable (ventana 1.5 s),
     con premio de 0.8 s si el hueco cae tras puntuación de fin de frase.
  3. Repartir el tiempo de cada tramo entre frases proporcionalmente al peso de
     sus palabras (letras +6 por cifra: los números se dicen más largos).
  4. Anclar inicio/fin de voz a los extremos reales.

Entrada/salida compatibles con los dos formatos del repo:
  - ALBRA (whisper_service): {"word", "start", "end"}
  - estudio-video-ia:        {"w", "ini", "fin"}
El resultado SIEMPRE sale en formato ALBRA.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

import config

log = logging.getLogger("whisper_realign")

PUNTUACION = set(".,;:?!…¿¡\"'«»—-")
FIN_PAUSA = tuple(".,;:?!…")
PREMIO_PUNTUACION = 0.8   # segundos: una pausa prefiere caer tras coma o punto
VENTANA = 1.5             # una pausa no se asigna a un hueco a más de esto
SILENCE_NOISE_DB = -38
SILENCE_MIN_D = 0.12

_KEYS = {
    "start": ("start", "ini"),
    "end": ("end", "fin"),
    "word": ("word", "w"),
}


def _get(w: dict, key: str):
    for k in _KEYS[key]:
        if k in w:
            return w[k]
    raise KeyError(f"palabra sin clave '{key}': {w!r}")


def detect_silences(audio_path: str | Path) -> list[tuple[float, float]]:
    """Pausas reales del audio: [(inicio, fin), ...] vía ffmpeg silencedetect."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(audio_path),
         "-af", f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_D}",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    ini = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    fin = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(ini, fin))


def word_weight(word: str) -> float:
    """Cuánto se tarda en decir la palabra; las cifras se leen más largas."""
    return max(2, len(re.findall(r"[^\W\d_]", word, re.UNICODE))
               + 6 * len(re.findall(r"\d", word))) + 0.5


def realign_words(words: list[dict], pauses: list[tuple[float, float]],
                  total_dur: float) -> list[dict]:
    """Ancla cada pausa real al hueco entre palabras más probable y reparte el
    tiempo de cada tramo por la longitud de sus palabras. Port de `realinear`."""
    if len(words) < 2:
        return words

    inicio_voz = pauses[0][1] if pauses and pauses[0][0] < 0.05 else _get(words[0], "start")
    fin_voz = pauses[-1][0] if pauses and pauses[-1][1] > total_dur - 0.05 else _get(words[-1], "end")
    internas = [p for p in pauses if p[0] > inicio_voz and p[1] < fin_voz]

    cortes, ultimo = [], -1   # (índice de la palabra antes de la pausa, pausa)
    for ini, fin in internas:
        centro, mejor = (ini + fin) / 2, None
        for i in range(ultimo + 1, len(words) - 1):
            hueco = (_get(words[i], "end") + _get(words[i + 1], "start")) / 2
            if abs(hueco - centro) > VENTANA:
                continue
            d = abs(hueco - centro) - (PREMIO_PUNTUACION
                                       if _get(words[i], "word").endswith(FIN_PAUSA) else 0)
            if mejor is None or d < mejor[0]:
                mejor = (d, i)
        if mejor:
            cortes.append((mejor[1], ini, fin))
            ultimo = mejor[1]

    tramos, desde, t0 = [], 0, inicio_voz
    for i, ini, fin in cortes:
        tramos.append((desde, i, t0, ini))
        desde, t0 = i + 1, fin
    tramos.append((desde, len(words) - 1, t0, fin_voz))

    for a, b, t_ini, t_fin in tramos:
        pesos = [word_weight(_get(words[k], "word")) for k in range(a, b + 1)]
        t = t_ini
        for k in range(a, b + 1):
            words[k]["start"] = round(t, 3)
            t += (t_fin - t_ini) * pesos[k - a] / sum(pesos)
            words[k]["end"] = round(t, 3)
    # normalización de salida: SIEMPRE formato ALBRA (word/start/end)
    return [{"word": _get(w, "word"), "start": w["start"], "end": w["end"]}
            for w in words]


def realign_enabled() -> bool:
    """Gate en caliente (lectura por llamada, patrón INT-069): WHISPER_REALIGN."""
    return str(getattr(config, "WHISPER_REALIGN", "1")).strip().lower() in (
        "1", "true", "yes", "on")


def maybe_realign(words: list[dict], audio_path: str | Path,
                  total_dur: float | None = None) -> list[dict]:
    """Punto de enganche para whisper_service.align_scene: aplica la realineación
    si el gate está activo y hay palabras suficientes; NUNCA lanza (fail-open
    a los timestamps crudos de Whisper)."""
    if not words or not realign_enabled() or len(words) < 2:
        return words
    try:
        if total_dur is None:
            total_dur = _get(words[-1], "end")
        pauses = detect_silences(audio_path)
        out = realign_words([dict(w) for w in words], pauses, float(total_dur))
        log.info("[whisper_realign] %d palabras realineadas con %d pausas reales",
                 len(out), len(pauses))
        return out
    except Exception as ex:                      # noqa: BLE001 — fail-open
        log.warning("[whisper_realign] realineación omitida: %s", ex)
        return words

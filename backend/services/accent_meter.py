"""
YOUTUBE AUTOMATION v2.26 — Medidor espectral de acento para casting de voces (INT-070)

Adaptado de estudio-video-ia (scripts/medir_acento.py, material aportado por el
usuario; sin fichero LICENSE — se porta el ALGORITMO, no el fichero).

¿La voz suena de España (distinción /θ/) o de Latinoamérica (seseo)? Sirve para
VALIDAR el claim de una voz del catálogo (voices_catalog / etiquetas de acento)
antes de gastarla en un canal: cada voz candidata lee exactamente la frase de
prueba y se mide la distinción entre "z/c" y "s" en el espectro.

Física del truco: la frase de prueba empareja 5 palabras con z/c (+5 con s) con
los mismos contextos vocálicos (cima/sima, cena/sena…). Los 10 picos de energía
de silbido (4–10 kHz) corresponden uno a uno a las 10 palabras. En España la
z/c es θ — un soplo MÁS DÉBIL que la s: Δ ≥ 6 dB. Con seseo, ambas mitades
suenan igual: Δ ≈ 0–2 dB.

Valores de referencia medidos en el proyecto origen (voces Higgsfield):
Sterling 1.8 dB (seseo); Gideon 7.6; Gideon con etiqueta castellana 8.7;
Barrett con etiqueta castellana 13.8.
"""
from __future__ import annotations

import logging
import subprocess
import warnings
from pathlib import Path

import numpy as np

log = logging.getLogger("accent_meter")

warnings.filterwarnings("ignore", category=RuntimeWarning)

SR = 44100
UMBRAL_ESPANA = 6.0    # Δ ≥ 6 dB → distinción (España)
UMBRAL_SESEO = 3.0     # Δ ≤ 3 dB → seseo (Latinoamérica); entre ambos: dudoso
FRASE_PRUEBA = "Cima, cena, cien, caza, cocer. Sima, sena, sien, casa, coser."


def cargar(ruta: str | Path) -> np.ndarray:
    """Audio → float32 mono 44.1 kHz vía ffmpeg (sin dependencias de decode)."""
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(ruta), "-ac", "1", "-ar", str(SR),
         "-f", "s16le", "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768


def measure_delta(ruta: str | Path) -> float | None:
    """Δ medio (dB) entre la energía de silbido de las 5 palabras 's' y las 5
    'z/c'. None si no se encuentran 10 picos (la voz no leyó la frase entera)."""
    x = cargar(ruta)
    n, h = 1024, 256
    f = np.fft.rfftfreq(n, 1 / SR)
    alta = (f >= 4000) & (f <= 10000)
    env = np.array([np.abs(np.fft.rfft(x[i:i + n] * np.hanning(n)))[alta].sum()
                    for i in range(0, len(x) - n, h)])
    env_db = 20 * np.log10(env + 1e-9)
    sep = int(0.25 * SR / h)   # un pico por palabra: ≥0.25 s entre picos
    cand = [i for i in range(1, len(env) - 1)
            if env[i] == env[max(0, i - sep):i + sep].max()]
    picos = sorted(sorted(cand, key=lambda i: -env[i])[:10])
    if len(picos) < 10:
        return None
    return float(np.mean([env_db[i] for i in picos[5:]])
                 - np.mean([env_db[i] for i in picos[:5]]))


def classify(delta_db: float, objetivo: str = "es-ES") -> dict:
    """Δ medido → veredicto de casting. objetivo: 'es-ES' exige distinción;
    'es-LATAM' exige seseo. Devuelve dict honesto (sin lanzar)."""
    d = float(delta_db)
    if d >= UMBRAL_ESPANA:
        acento = "espana"
    elif d <= UMBRAL_SESEO:
        acento = "seseo"
    else:
        acento = "dudoso"
    valida = ((objetivo == "es-ES" and d >= UMBRAL_ESPANA)
              or (objetivo == "es-LATAM" and d <= UMBRAL_SESEO))
    return {"delta_db": round(d, 2), "acento": acento,
            "valida": bool(valida), "objetivo": objetivo,
            "frase_prueba": FRASE_PRUEBA}


def audit_voice(audio_path: str | Path, objetivo: str = "es-ES") -> dict:
    """Punto de entrada para casting: mide y clasifica. Si la voz no leyó la
    frase completa (o el audio no sirve) → {'valida': False, 'error': ...}."""
    try:
        d = measure_delta(audio_path)
    except Exception as ex:                      # noqa: BLE001 — fail-closed honesto
        return {"valida": False, "error": f"ACCENT_AUDIO_UNREADABLE: {ex}",
                "objetivo": objetivo, "frase_prueba": FRASE_PRUEBA}
    if d is None:
        return {"valida": False, "error": "ACCENT_PHRASE_INCOMPLETE",
                "objetivo": objetivo, "frase_prueba": FRASE_PRUEBA}
    return classify(d, objetivo)

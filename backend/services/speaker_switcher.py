"""
YOUTUBE AUTOMATION v2.28 — Active Speaker Switcher (INT-052)
Inspirado en OpenShorts (mutonby/openshorts) y OpusClip.

Detecta y alterna dinámicamente el plano visual entre el hablante izquierdo y derecho
en podcasts o entrevistas horizontales (16:9), enfocando en vertical 9:16 a quien
tiene la palabra en cada turno de conversación.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("speaker_switcher")


def detect_speaker_turns(
    segments: list[dict[str, Any]] | None,
    total_duration: float,
    min_turn_sec: float = 2.5
) -> list[dict[str, Any]]:
    """Genera la lista de turnos de conversación (hablante izquierdo / derecho).

    Si se dispone de segmentos transcritos de Whisper, analiza las pausas y
    oraciones para alternar de forma natural. Si no hay transcript, divide la
    duración en bloques rítmicos de 4-6 segundos simulando la conversación.
    """
    turns: list[dict[str, Any]] = []
    dur = max(1.0, float(total_duration))

    if segments and len(segments) > 1:
        current_speaker = "left"
        turn_start = 0.0

        for idx, seg in enumerate(segments):
            seg_start = float(seg.get("start", 0))
            seg_end = float(seg.get("end", seg_start + 1.0))
            text = str(seg.get("text", "")).strip()

            # Condiciones de cambio de turno:
            # - Pausa entre segmentos > 0.4s
            # - La frase termina en punto o signo de interrogación y ha pasado suficiente tiempo
            has_pause = idx > 0 and (seg_start - float(segments[idx-1].get("end", 0)) > 0.4)
            is_question = text.endswith("?") or text.endswith("¿")
            turn_len = seg_end - turn_start

            if (has_pause or is_question or turn_len >= 8.0) and turn_len >= min_turn_sec:
                turns.append({
                    "start": round(turn_start, 2),
                    "end": round(seg_end, 2),
                    "speaker": current_speaker
                })
                current_speaker = "right" if current_speaker == "left" else "left"
                turn_start = seg_end

        # Segmento final restante
        if turn_start < dur:
            turns.append({
                "start": round(turn_start, 2),
                "end": round(dur, 2),
                "speaker": current_speaker
            })
    else:
        # Fallback determinista rítmico: alternancia dinámica cada 4.5s
        t = 0.0
        cur = "left"
        block = 4.5
        while t < dur:
            nxt = min(dur, round(t + block, 2))
            turns.append({
                "start": round(t, 2),
                "end": nxt,
                "speaker": cur
            })
            t = nxt
            cur = "right" if cur == "left" else "left"

    return turns


def build_speaker_switch_filter(
    turns: list[dict[str, Any]],
    width: int = 1080,
    height: int = 1920
) -> str:
    """Construye el filtergraph de FFmpeg para alternar entre el recorte izquierdo y derecho.

    Stream [left_crop]: mitad izquierda escalada a 1080x1920 (Hablante 1).
    Stream [right_crop]: mitad derecha escalada a 1080x1920 (Hablante 2).
    Se superpone [right_crop] sobre [left_crop] únicamente durante los turnos del hablante derecho.
    """
    # Recorte y encuadre 9:16 de la mitad izquierda (Hablante 1)
    left_def = (
        f"[0:v]split=2[src_l][src_r];"
        f"[src_l]crop=iw/2:ih:0:0,"
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}[left_crop];"
    )

    # Recorte y encuadre 9:16 de la mitad derecha (Hablante 2)
    right_def = (
        f"[src_r]crop=iw/2:ih:iw/2:0,"
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}[right_crop];"
    )

    # Obtener intervalos donde habla la derecha
    right_intervals = [
        f"between(t,{t['start']:.2f},{t['end']:.2f})"
        for t in turns if t["speaker"] == "right"
    ]

    if right_intervals:
        enable_expr = "+".join(right_intervals)
        overlay_filter = (
            f"[left_crop][right_crop]overlay=x=0:y=0:"
            f"enable='{enable_expr}'[base]"
        )
    else:
        # Solo habla la izquierda
        overlay_filter = "[left_crop]null[base]"

    return f"{left_def}{right_def}{overlay_filter}"

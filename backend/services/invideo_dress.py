"""
YOUTUBE AUTOMATION v2.35 — InVideo AI & OpusClip Auto-Dress Engine (INT-064)
Clonado limpio de InVideo AI y OpusClip Pro.

Analiza el guion y la duración de escenas para:
1. Detectar valles de retención (>3s sin cambio visual) e inyectar B-roll relevante.
2. Calcular eventos de SFX (Whoosh en cortes, Pop en ganchos, Ding en datos clave).
3. Entregar el manifiesto completo de producción automatizada a $0.00 de coste.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from services import sfx_manager, broll_overlay

log = logging.getLogger("invideo_dress")


def detect_sfx_cues_in_text(text: str) -> list[str]:
    """Identifica palabras clave que ameritan micro-SFX (números, dinero, alertas)."""
    cues = []
    text_lower = text.lower()
    if re.search(r"\b(\$|€|usd|dólares|pesos|dinero|precio|rebaja|descuento|\d+([.,]\d+)?%)\b", text_lower):
        cues.append("ding")
    if re.search(r"\b(cuidado|alerta|atención|error|secreto|truco|mira|ojo)\b", text_lower):
        cues.append("pop")
    return cues


def auto_dress_timeline(
    scenes: list[dict[str, Any]],
    total_duration_sec: float | None = None,
    enable_sfx: bool = True,
    enable_broll: bool = True
) -> dict[str, Any]:
    """Genera la planificación automatizada de B-Roll y SFX estilo InVideo AI / OpusClip."""
    sfx_lib = sfx_manager.ensure_sfx_library()

    scene_durations: list[float] = []
    broll_cutaways: list[dict[str, Any]] = []
    sfx_events: list[dict[str, Any]] = []

    cursor = 0.0

    for idx, sc in enumerate(scenes):
        dur = float(sc.get("duration_sec") or sc.get("duration") or 3.5)
        scene_durations.append(dur)
        text = str(sc.get("narration") or sc.get("text") or "")
        scene_start = cursor
        scene_end = round(cursor + dur, 2)

        # 1. B-Roll Injection: Si la escena dura más de 2.8s, inyectar un corte dinámico de 2.2s a 3.0s
        if enable_broll and dur >= 2.8:
            kws = broll_overlay.extract_broll_keywords_heuristic(text, max_keywords=1)
            query = kws[0] if kws else "cinematic dynamic vertical"

            # Inyectar a la mitad de la escena
            broll_start = round(scene_start + max(0.5, dur * 0.25), 2)
            broll_duration = min(3.0, round(dur * 0.6, 2))
            broll_end = round(broll_start + broll_duration, 2)

            broll_cutaways.append({
                "scene_idx": idx,
                "scene_id": sc.get("scene_id") or f"scene_{idx+1}",
                "query": query,
                "start_sec": broll_start,
                "end_sec": broll_end,
                "duration_sec": broll_duration,
                "transition": "fade_in"
            })

            # Añadir Pop o Whoosh suave al inicio del B-Roll
            if enable_sfx:
                sfx_events.append({
                    "type": "pop",
                    "time_sec": round(broll_start, 2),
                    "volume": 0.25,
                    "label": f"B-Roll Cutaway ({query})"
                })

        # 2. Whoosh en corte de escena (entre escenas)
        if enable_sfx and idx < len(scenes) - 1:
            sfx_events.append({
                "type": "whoosh",
                "time_sec": max(0.1, round(scene_end - 0.06, 2)),
                "volume": 0.22,
                "label": f"Transición Escena {idx+1} ➜ {idx+2}"
            })

        # 3. Ding en mención de números o dinero
        if enable_sfx:
            text_sfx = detect_sfx_cues_in_text(text)
            if "ding" in text_sfx:
                sfx_events.append({
                    "type": "ding",
                    "time_sec": round(scene_start + min(1.2, dur * 0.4), 2),
                    "volume": 0.30,
                    "label": "Énfasis de Dato / Valor"
                })

        cursor = scene_end

    # Ordenar y desduplicar SFX muy cercanos (< 0.20s)
    sfx_events.sort(key=lambda x: x["time_sec"])
    filtered_sfx: list[dict[str, Any]] = []
    last_t = -1.0
    for ev in sfx_events:
        if ev["time_sec"] - last_t >= 0.20:
            filtered_sfx.append(ev)
            last_t = ev["time_sec"]

    total_time = round(cursor, 2) if total_duration_sec is None else round(total_duration_sec, 2)

    # Estimación de boost de retención (% extra vs video estático sin SFX ni B-roll)
    retention_boost = min(48, len(broll_cutaways) * 8 + len(filtered_sfx) * 4)

    return {
        "ok": True,
        "timeline_summary": {
            "total_duration_sec": total_time,
            "scene_count": len(scenes),
            "broll_count": len(broll_cutaways),
            "sfx_count": len(filtered_sfx),
            "predicted_retention_boost": f"+{retention_boost}%",
        },
        "broll_cutaways": broll_cutaways,
        "sfx_events": filtered_sfx,
        "sfx_library_status": {k: p.is_file() for k, p in sfx_lib.items()}
    }

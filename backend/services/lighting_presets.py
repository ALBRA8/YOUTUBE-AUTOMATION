"""
YOUTUBE AUTOMATION — Presets de Iluminación y Estilos Fotográficos / UGC
========================================================================
Procedencia: CHAT-X (src/components/estudio/biblioteca.ts · Adopción Enhancor / Batch C).
Semántica: Fragmentos de iluminación y look cinematográfico / iPhone auténtico para
inyectar en los prompts de generación de escenas (evita el look plano o plástico).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

LIGHTING_PRESETS: List[Dict[str, Any]] = [
    # ── Iluminación Cinematográfica de Estudio ──
    {
        "id": "ethereal-light",
        "nombre": "Ethereal Light",
        "categoria": "cinematic",
        "descripcion": "Luz suave difusa a través de telas finas, resplandor etéreo, piel luminosa",
        "prompt_injection": "soft diffuse lighting through fine fabrics, ethereal glow, luminous skin tones, subtle rim light, shallow depth of field, 8k cinematic photography",
    },
    {
        "id": "blinds-noir",
        "nombre": "Blinds Noir",
        "categoria": "cinematic",
        "descripcion": "Luz dura filtrada por persianas venecianas, rayas noir, sombras profundas",
        "prompt_injection": "dramatic Venetian blinds shadow patterns, hard noir contrast, moody chiaroscuro lighting, deep cinematic shadows, 35mm film still",
    },
    {
        "id": "gobo-spotlight",
        "nombre": "Gobo Spotlight",
        "categoria": "cinematic",
        "descripcion": "Foco gobo con patrones de sombra en deriva, luz principal dramática",
        "prompt_injection": "textured gobo spotlight projection, dramatic key light, sharp geometric light angles, dark textured backdrop, high contrast editorial portrait",
    },
    {
        "id": "golden-hour-window",
        "nombre": "Golden Hour Window",
        "categoria": "cinematic",
        "descripcion": "Sol cálido de golden hour, luz de borde ámbar, sombras largas y suaves",
        "prompt_injection": "warm golden hour sunlight streaming through large window, amber rim lighting, long soft shadows, dust motes in light beam, warm natural tones",
    },
    # ── Realismo UGC / iPhone Auténtico (Batch C Enhancor) ──
    {
        "id": "iphone-selfie-natural",
        "nombre": "iPhone Selfie V1 · Natural",
        "categoria": "ugc",
        "descripcion": "Luz natural de día, sol levemente cenital, look de foto de teléfono auténtica",
        "prompt_injection": "authentic smartphone camera photo, candid angle, natural outdoor daylight, realistic skin texture with visible pores, unedited mobile photography feel",
    },
    {
        "id": "iphone-selfie-studio-soft",
        "nombre": "iPhone Selfie V2 · Studio Soft",
        "categoria": "ugc",
        "descripcion": "Luz interior suave y pareja, cámara frontal de teléfono, candidez",
        "prompt_injection": "casual indoor mobile selfie, soft ambient room lighting, realistic front camera quality, natural expression, unpolished authentic creator aesthetic",
    },
    {
        "id": "iphone-selfie-vivid",
        "nombre": "iPhone Selfie V3 · Vivid",
        "categoria": "ugc",
        "descripcion": "Tonos vívidos de retrato, colores saturados de ciudad, look HDR de teléfono",
        "prompt_injection": "vibrant city dusk mobile portrait, vivid smartphone HDR color science, rich saturated hues, subtle handheld camera shake, authentic TikTok aesthetic",
    },
    {
        "id": "iphone-selfie-night-mode",
        "nombre": "iPhone Selfie V4 · Night Mode",
        "categoria": "ugc",
        "descripcion": "Modo noche de teléfono, luz ambiental de neón, grano leve",
        "prompt_injection": "smartphone night mode capture, ambient neon signage lighting, atmospheric slight grain, realistic low-light phone sensor noise, raw urban aesthetic",
    },
]

PRESETS_BY_ID = {p["id"]: p for p in LIGHTING_PRESETS}


def get_preset(preset_id: str) -> Optional[Dict[str, Any]]:
    return PRESETS_BY_ID.get(preset_id)


def list_lighting_presets(categoria: Optional[str] = None) -> List[Dict[str, Any]]:
    if categoria:
        return [p for p in LIGHTING_PRESETS if p.get("categoria") == categoria]
    return list(LIGHTING_PRESETS)


def enrich_prompt_with_lighting(base_prompt: str, preset_id: Optional[str] = None) -> str:
    """Añade los descriptores lumínicos del preset al prompt base si existe."""
    if not preset_id or preset_id == "auto":
        return base_prompt
    preset = get_preset(preset_id)
    if not preset:
        return base_prompt
    injection = preset["prompt_injection"]
    clean_base = base_prompt.strip().rstrip(",")
    return f"{clean_base}, {injection}"

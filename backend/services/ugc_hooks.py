"""
YOUTUBE AUTOMATION v2.34 — Multi-Angle UGC Hooks Generator (INT-061)
Inspirado en Arcads.ai & CreateUGC.ai.

Genera variantes multi-ángulo del gancho inicial (primeros 3-5 segundos)
para pruebas A/B en TikTok Ads, Meta Ads y Shorts verticales, multiplicando
el Stop-Rate (retención de los primeros 3 segundos).
"""
from __future__ import annotations

import logging
import math
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger("ugc_hooks")

# Fórmulas probadas de retención para UGC / Anuncios de alta conversión
HOOK_ANGLES: dict[str, dict[str, Any]] = {
    "negative_warning": {
        "key": "negative_warning",
        "badge": "⚠️ Advertencia Anti-Error",
        "tag": "Aversión a Pérdida",
        "formula": "¡Detente un segundo si todavía estás {action}! No cometas este grave error con {name}.",
        "fallback": "¡Detente un segundo si sigues haciendo esto mal! No cometas este grave error que todos ignoran.",
        "visual_prompt": "Hand holding up to stop camera gesture, shocking facial expression, dramatic lighting, modern UGC setup, 8k vertical 9:16",
        "visual_cue": "Gesto de parar con la mano extendida a la cámara, expresión de alerta y sorpresa.",
        "predicted_stop_rate": 93,
        "pacing": "Rápido / Alerta urgente",
        "avg_duration": 3.5,
    },
    "curiosity_hack": {
        "key": "curiosity_hack",
        "badge": "🔍 Hack Secreto / Revelación",
        "tag": "Brecha de Curiosidad",
        "formula": "El truco secreto con {name} que las grandes marcas nunca van a revelarte...",
        "fallback": "El truco secreto que la mayoría de creadores y marcas nunca van a revelarte...",
        "visual_prompt": "Extreme close-up whispering to camera, leaning in intimately, showing device half hidden, natural room lighting, 8k vertical 9:16",
        "visual_cue": "Susurro cómplice a la cámara inclinándose hacia adelante, mostrando el producto semi-oculto.",
        "predicted_stop_rate": 90,
        "pacing": "Intrigante / Cómplice",
        "avg_duration": 4.0,
    },
    "transformation_speed": {
        "key": "transformation_speed",
        "badge": "⚡ Transformación Rápida",
        "tag": "Deseo Inmediato",
        "formula": "Cómo pasé de sufrir con {problem} a solucionarlo en menos de 5 minutos gracias a {name}.",
        "fallback": "Cómo pasé del caos total a tener todo solucionado en menos de cinco minutos con esto.",
        "visual_prompt": "Fast split screen transition: frustrated person vs happy satisfied person holding product, clean vibrant lighting, 8k vertical 9:16",
        "visual_cue": "Corte rápido o pantalla partida de expresión frustrada a alivio y sonrisa con el producto.",
        "predicted_stop_rate": 95,
        "pacing": "Dinámico / Alto Impacto",
        "avg_duration": 3.8,
    },
    "social_proof_skeptic": {
        "key": "social_proof_skeptic",
        "badge": "👥 Escepticismo & Prueba Social",
        "tag": "Superación de Objeción",
        "formula": "Pensé que {name} era otra estafa viral de TikTok... hasta que me llegó a la casa hoy.",
        "fallback": "Pensé que este producto era una estafa más de TikTok... hasta que me llegó hoy a casa.",
        "visual_prompt": "Authentic UGC style, unboxing package with curious skeptical face, opening box, real natural bedroom lighting, 8k vertical 9:16",
        "visual_cue": "Abriendo paquete de mensajería con rostro escéptico antes de quedarse con la boca abierta.",
        "predicted_stop_rate": 94,
        "pacing": "Orgánico / Casual UGC",
        "avg_duration": 4.2,
    },
    "urgency_fomo": {
        "key": "urgency_fomo",
        "badge": "🔥 Oferta Flash / Alerta Urgente",
        "tag": "FOMO / Escasez",
        "formula": "Si estás viendo este video hoy tienes mucha suerte: acaban de rebajar {name} antes de que se agote.",
        "fallback": "Si estás viendo este video hoy tienes mucha suerte: acaban de lanzar una rebaja flash antes de que se agote.",
        "visual_prompt": "Holding phone pointing finger down to comments or link, energetic fast movement, vibrant neon flash in background, 8k vertical 9:16",
        "visual_cue": "Señalando hacia abajo o a la pantalla con energía desbordante y sensación de urgencia.",
        "predicted_stop_rate": 88,
        "pacing": "Acelerado / Máxima Energía",
        "avg_duration": 3.6,
    },
}


def generate_multi_angle_hooks(
    name: str = "",
    problem: str = "",
    benefit: str = "",
    action: str = "",
    target_audience: str = ""
) -> list[dict[str, Any]]:
    """Genera 5 ganchos psicológicos optimizados para retención de los primeros 3 segundos.

    Adapta las fórmulas según el nombre del producto, problema o acción descrita.
    """
    clean_name = (name or "").strip()
    clean_problem = (problem or "").strip() or "perder el tiempo sin resultados"
    clean_action = (action or "").strip() or "haciendo las cosas de la forma difícil"

    results: list[dict[str, Any]] = []

    for angle_key, cfg in HOOK_ANGLES.items():
        if clean_name:
            hook_text = cfg["formula"].format(
                name=clean_name,
                problem=clean_problem,
                action=clean_action,
                benefit=benefit or "obtener resultados increíbles"
            )
        else:
            hook_text = cfg["fallback"]

        # Estimación de duración realista basada en palabras (aprox 2.8 palabras/segundo)
        words = len(hook_text.split())
        est_duration = max(2.5, round(words / 2.7, 1))

        results.append({
            "key": angle_key,
            "badge": cfg["badge"],
            "tag": cfg["tag"],
            "hook_text": hook_text,
            "visual_prompt": cfg["visual_prompt"],
            "visual_cue": cfg["visual_cue"],
            "predicted_stop_rate": cfg["predicted_stop_rate"],
            "pacing": cfg["pacing"],
            "duration_sec": est_duration,
            "word_count": words,
        })

    # Ordenar por mayor probabilidad de Stop-Rate estimado
    results.sort(key=lambda x: x["predicted_stop_rate"], reverse=True)
    return results


def build_ab_variants(
    product_name: str,
    base_body: str,
    base_cta: str,
    hooks: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Construye variantes completas de video listas para producción A/B.

    Combina cada gancho (escena 1 de retención) con el cuerpo del video y el CTA.
    """
    if not hooks:
        hooks = generate_multi_angle_hooks(name=product_name)

    letters = ["A", "B", "C", "D", "E"]
    variants: list[dict[str, Any]] = []

    clean_body = (base_body or "").strip() or f"{product_name} está diseñado con la última tecnología para darte resultados rápidos y duraderos."
    clean_cta = (base_cta or "").strip() or "Haz clic en el enlace del perfil antes de que termine la promoción especial."

    for idx, hook in enumerate(hooks):
        variant_letter = letters[idx % len(letters)]
        full_script = f"{hook['hook_text']} {clean_body} {clean_cta}"

        # Escenas estructuradas
        scenes = [
            {
                "scene_id": f"scene_01_hook_{variant_letter}",
                "type": "hook",
                "narration": hook["hook_text"],
                "duration_sec": hook["duration_sec"],
                "visual_prompt": hook["visual_prompt"],
                "visual_cue": hook["visual_cue"]
            },
            {
                "scene_id": f"scene_02_body_{variant_letter}",
                "type": "body",
                "narration": clean_body,
                "duration_sec": 12.0,
                "visual_prompt": f"cinematic demonstration of {product_name or 'product'}, high production quality, clear view, 8k vertical 9:16",
                "visual_cue": "Demostración clara del producto en acción."
            },
            {
                "scene_id": f"scene_03_cta_{variant_letter}",
                "type": "cta",
                "narration": clean_cta,
                "duration_sec": 5.0,
                "visual_prompt": f"product promo screen of {product_name or 'product'} with animated link button, vertical 9:16",
                "visual_cue": "Pantalla final con llamada a la acción y flecha al link."
            }
        ]

        variants.append({
            "variant_id": f"variant_{variant_letter.lower()}_{hook['key']}",
            "variant_letter": variant_letter,
            "angle_key": hook["key"],
            "badge": hook["badge"],
            "predicted_stop_rate": hook["predicted_stop_rate"],
            "pacing": hook["pacing"],
            "full_script": full_script,
            "scenes": scenes,
            "total_duration_sec": round(hook["duration_sec"] + 17.0, 1)
        })

    return variants


def stitch_hook_variants(
    hook_video_path: Path,
    body_video_path: Path,
    output_path: Path
) -> Path:
    """Concatena el video del gancho con el cuerpo del video mediante FFmpeg.

    Garantiza resolución consistente 1080x1920 (Short vertical 9:16) y audio sincronizado.
    """
    if not hook_video_path.is_file():
        raise FileNotFoundError(f"Video de gancho no encontrado: {hook_video_path}")
    if not body_video_path.is_file():
        raise FileNotFoundError(f"Video de cuerpo no encontrado: {body_video_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(hook_video_path),
        "-i", str(body_video_path),
        "-filter_complex",
        "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1[v0];"
        "[1:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1[v1];"
        "[v0][0:a][v1][1:a]concat=n=2:v=1:a=1[outv][outa]",
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        str(output_path)
    ]

    log.info("[ugc_hooks] Ejecutando concatenación FFmpeg de variante: %s", output_path.name)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        log.error("[ugc_hooks] Error FFmpeg en stitch_hook_variants: %s", res.stderr)
        raise RuntimeError(f"FFmpeg concat failed: {res.stderr}")

    return output_path

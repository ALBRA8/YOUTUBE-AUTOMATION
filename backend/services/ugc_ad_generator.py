"""
YOUTUBE AUTOMATION v2.30 — UGC & E-Commerce Ad Generator (INT-054)
Inspirado en v4v.ai (URL-to-Ad para E-Commerce & TikTok Shop).

1. Extrae metadatos de productos de cualquier tienda web (Shopify, Amazon, MercadoLibre, WooCommerce)
   vía OpenGraph y microdatos de e-commerce.
2. Genera guiones virales con fórmulas probadas de conversión UGC:
   - '3_reasons': 3 razones por las que necesitas este producto
   - 'problem_solution': Frustración común vs solución inmediata
   - 'dont_buy_before': Gancho de advertencia y curiosidad
   - 'honest_review': Unboxing y reseña en primera persona
"""
from __future__ import annotations

import logging
import re
from typing import Any
import urllib.request

log = logging.getLogger("ugc_ad_generator")

UGC_ANGLES: dict[str, dict[str, str]] = {
    "3_reasons": {
        "name": "3 Razones",
        "tagline": "3 razones por las que todo el mundo está comprando esto",
        "hook_template": "Tres razones por las que no puedo vivir sin {name}.",
        "cta_template": "El enlace con descuento exclusivo está en el perfil o en el primer comentario. ¡Aprovecha antes de que se agote!"
    },
    "problem_solution": {
        "name": "Problema vs Solución",
        "tagline": "El error que comete el 90% de la gente y la solución",
        "hook_template": "Si estás harto de {problem}, tienes que ver esto.",
        "cta_template": "Haz clic en el enlace y dile adiós a {problem} hoy mismo."
    },
    "dont_buy_before": {
        "name": "No Compres Antes de Ver Esto",
        "tagline": "Gancho de advertencia y máxima retención",
        "hook_template": "¡No compres {name} antes de escuchar este secreto!",
        "cta_template": "Consigue el original con envío rápido en el botón de abajo."
    },
    "honest_review": {
        "name": "Review Honesta / Unboxing",
        "tagline": "Tono casual y auténtico de creador de contenido",
        "hook_template": "Llevo usando {name} durante dos semanas y esta es mi opinión sincera.",
        "cta_template": "Totalmente recomendado. Te dejé el enlace directo aquí abajo."
    }
}


def scrape_product_info(url_or_text: str) -> dict[str, Any]:
    """Extrae título, descripción, precio e imagen de producto desde una URL o texto.

    Soporta scraping de OpenGraph, Twitter Cards y etiquetas meta de e-commerce.
    Si la entrada no es una URL, la trata como descripción directa de producto.
    """
    input_str = (url_or_text or "").strip()
    if not input_str:
        return {"name": "Producto Destacado", "description": "", "image_url": None, "price": None}

    # Si no parece una URL web, estructurar datos a partir del texto
    if not (input_str.startswith("http://") or input_str.startswith("https://")):
        lines = [l.strip() for l in input_str.split("\n") if l.strip()]
        title = lines[0][:80] if lines else "Producto Viral"
        desc = " ".join(lines[1:]) if len(lines) > 1 else lines[0]
        return {
            "name": title,
            "description": desc,
            "image_url": None,
            "price": None,
            "is_url": False
        }

    # Scraping HTTP con headers de navegador moderno
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"
    }

    req = urllib.request.Request(input_str, headers=headers)
    html_content = ""
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html_content = resp.read().decode("utf-8", errors="ignore")
    except Exception as ex:
        log.warning("[ugc_ad_generator] Falló scraping HTTP de %s: %s", input_str, ex)
        # Fallback extrayendo palabras del slug de la URL
        slug = input_str.split("/")[-1].replace("-", " ").replace("_", " ")[:60]
        return {
            "name": slug.title() or "Producto E-Commerce",
            "description": "Producto de alta demanda y calidad garantizada.",
            "image_url": None,
            "price": None,
            "is_url": True
        }

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Título del producto
        title = ""
        og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
        elif soup.find("h1"):
            title = soup.find("h1").get_text().strip()
        elif soup.title:
            title = soup.title.get_text().strip()
        title = re.sub(r"\s+", " ", title)[:90] or "Producto Destacado"

        # 2. Descripción / Beneficios
        desc = ""
        og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        if og_desc and og_desc.get("content"):
            desc = og_desc["content"].strip()
        desc = re.sub(r"\s+", " ", desc)[:300]

        # 3. Imagen principal del producto
        image_url = None
        og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
        if og_img and og_img.get("content"):
            image_url = og_img["content"].strip()

        # 4. Detección de precio
        price = None
        price_meta = soup.find("meta", property="product:price:amount") or soup.find("meta", property="og:price:amount")
        if price_meta and price_meta.get("content"):
            curr = soup.find("meta", property="product:price:currency")
            curr_sym = curr["content"] if curr and curr.get("content") else "$"
            price = f"{curr_sym} {price_meta['content']}"
        else:
            # Regex en el HTML
            m_price = re.search(r"(\$|€|USD)\s*(\d+[.,]\d{2})", html_content)
            if m_price:
                price = f"{m_price.group(1)} {m_price.group(2)}"

        return {
            "name": title,
            "description": desc,
            "image_url": image_url,
            "price": price,
            "is_url": True,
            "source_url": input_str
        }
    except Exception as ex:
        log.warning("[ugc_ad_generator] Error parseando HTML: %s", ex)
        return {
            "name": "Producto E-Commerce",
            "description": "",
            "image_url": None,
            "price": None,
            "is_url": True
        }


def generate_ugc_script(
    product_data: dict[str, Any],
    angle: str = "3_reasons",
    duration_sec: int = 35
) -> dict[str, Any]:
    """Genera un guion de anuncio UGC estructurado por escenas listo para producir.

    Retorna un diccionario con:
    - title: título viral
    - full_script: texto completo de narración
    - scenes: lista de escenas con sus visual prompts sugeridos y duraciones
    """
    name = product_data.get("name") or "este increíble producto"
    desc = product_data.get("description") or "diseño innovador y resultados inmediatos"
    price_info = f" por solo {product_data['price']}" if product_data.get("price") else ""

    angle_cfg = UGC_ANGLES.get(angle, UGC_ANGLES["3_reasons"])
    hook = angle_cfg["hook_template"].format(name=name, problem="perder el tiempo y dinero")
    cta = angle_cfg["cta_template"].format(name=name, problem="los dolores de cabeza")

    # Estructura persuasiva en 4 escenas optimizadas para retención
    scene_duration = round(duration_sec / 4.0, 1)

    s1 = f"{hook} Te aseguro que esto va a cambiar por completo tu rutina diaria."
    s2 = f"Primero: {desc[:120] if desc else 'cuenta con tecnología de última generación que se adapta a tu día a día'}."
    s3 = f"Segundo: olvídate de complicaciones. Es práctico, resistente y lo puedes conseguir hoy mismo{price_info}."
    s4 = f"{cta}"

    full_script = f"{s1} {s2} {s3} {s4}"

    scenes = [
        {
            "scene_id": "scene_01",
            "narration": s1,
            "duration_sec": scene_duration,
            "visual_prompt": f"cinematic close up of {name}, high end product photography, dramatic commercial lighting, 8k vertical 9:16",
            "type": "hook"
        },
        {
            "scene_id": "scene_02",
            "narration": s2,
            "duration_sec": scene_duration,
            "visual_prompt": f"person holding and using {name} happily, bright modern lifestyle aesthetic, clean background, 8k vertical 9:16",
            "type": "benefit_1"
        },
        {
            "scene_id": "scene_03",
            "narration": s3,
            "duration_sec": scene_duration,
            "visual_prompt": f"close detail of {name} premium materials and features, clean studio setting, soft shadows, 8k vertical 9:16",
            "type": "benefit_2"
        },
        {
            "scene_id": "scene_04",
            "narration": s4,
            "duration_sec": scene_duration,
            "visual_prompt": f"hero shot of {name} with glowing subtle light, sale promo commercial aesthetic, 8k vertical 9:16",
            "type": "cta"
        }
    ]

    return {
        "title": f"UGC Ad: {name[:45]}",
        "angle": angle,
        "full_script": full_script,
        "scenes": scenes,
        "product_data": product_data
    }

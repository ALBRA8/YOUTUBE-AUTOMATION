"""
YOUTUBE AUTOMATION v2.0 — INT-086 · Catálogo de Plantillas de Nicho.

Configuraciones de producción preconfiguradas para nichos comunes
(inspirado en la arquitectura de recursos de Sloth). Distinto de
services/niches.py (INT v2.6: prompts de IDEA por nicho) — aquí la
plantilla define CÓMO se produce: ritmo, B-roll, voz, música, subtítulos,
zonas seguras y la identidad de canal (marca.json) con cierre automático.

Persistencia: data/presets/niche_templates.json — auto-siembra con los 5
integrados (patrón niches.json), editable sin tocar código.

Catálogo integrado:
  cocina-recetas        9:16/16:9 · pausado · planos detalle · voz cálida
  crochet-manualidades  9:16 · primer plano manos/tejido · paso a paso · lofi
  ugc-producto          3-beat (gancho avatar → B-roll producto → cierre)
  viral-short           ritmo rápido · corte cada 3 s · bold + safe-zones
  miniaturas            miniatura 1280x720 y cover 768x1376 sin video
"""
import json
import threading
from pathlib import Path

from config import DATA_DIR

PRESETS_DIR = Path(DATA_DIR) / "presets"
PRESETS_PATH = PRESETS_DIR / "niche_templates.json"
_LOCK = threading.RLock()

# ── las 5 plantillas integradas ───────────────────────────────────────────
BUILTIN_TEMPLATES: list[dict] = [
    {
        "id": "cocina-recetas",
        "icono": "🍳",
        "nombre": "Cocina & Recetas",
        "descripcion": ("Recetas paso a paso con planos detalle del plato, "
                        "ritmo pausado, voz cálida en español y música "
                        "acústica suave. Subtítulos limpios inferiores."),
        "format": "short",
        "formatos": ["vertical", "horizontal"],
        "pacing": "slow",          # canon del backend (fast/normal/slow)
        "ritmo": "Pausado (~6 s por plano)",
        "broll": "planos detalle del proceso y del plato terminado (macro)",
        "musica": "acústica suave",
        "style": "auto",
        "voice": "es-CO-SalomeNeural",
        "subtitle_style": "minimal",
        "safe_zones": True,
        "estructura": ["gancho con el plato terminado", "ingredientes",
                       "pasos en planos detalle", "resultado + cierre"],
        "marca": {
            "nicho": "cocina",
            "nombre_canal": "",
            "tono": "cálido",
            "idioma": "es-CO",
            "voz_default": "es-CO-SalomeNeural",
            "cierre": {
                "red": "Instagram",
                "cuenta": "",
                "frase": "Sígueme en Instagram para la receta completa",
            },
        },
    },
    {
        "id": "crochet-manualidades",
        "icono": "🧶",
        "nombre": "Crochet & Manualidades",
        "descripcion": ("Tomas en primer plano de tejido y manos, tiempos "
                        "calculados paso a paso y música lofi tranquila. "
                        "Ideal para tutoriales relajantes."),
        "format": "short",
        "formatos": ["vertical"],
        "pacing": "slow",          # canon del backend (fast/normal/slow)
        "ritmo": "Pausado (~6 s por plano)",
        "broll": "primer plano de manos y tejido, cada paso numerado",
        "musica": "lofi tranquila",
        "style": "auto",
        "voice": "es-MX-DaliaNeural",
        "subtitle_style": "minimal",
        "safe_zones": True,
        "estructura": ["muestra del resultado", "materiales",
                       "paso a paso en primer plano", "resultado + cierre"],
        "marca": {
            "nicho": "crochet",
            "nombre_canal": "",
            "tono": "tranquilo",
            "idioma": "es-CO",
            "voz_default": "es-MX-DaliaNeural",
            "cierre": {
                "red": "Instagram",
                "cuenta": "",
                "frase": "Sígueme para el patrón completo paso a paso",
            },
        },
    },
    {
        "id": "ugc-producto",
        "icono": "🛍️",
        "nombre": "UGC Producto",
        "descripcion": ("Video ad estilo UGC con estructura 3-beat: gancho "
                        "con avatar → B-roll del producto → cierre con "
                        "avatar. Voz enérgica y subtítulos dinámicos en el "
                        "tercio medio."),
        "format": "short",
        "formatos": ["vertical"],
        "pacing": "normal",        # canon del backend
        "ritmo": "Normal (~4 s por plano)",
        "broll": "B-roll del producto en uso (unboxing, textura, resultado)",
        "musica": "energética moderna",
        "style": "auto",
        "voice": "es-CO-GonzaloNeural",
        "subtitle_style": "shorts",
        "safe_zones": True,
        "estructura": ["gancho avatar", "b-roll producto", "cierre avatar"],
        "marca": {
            "nicho": "ugc",
            "nombre_canal": "",
            "tono": "enérgico",
            "idioma": "es-CO",
            "voz_default": "es-CO-GonzaloNeural",
            "cierre": {
                "red": "TikTok",
                "cuenta": "",
                "frase": "Tócalo en el carrito antes de que se acabe",
            },
        },
    },
    {
        "id": "viral-short",
        "icono": "⚡",
        "nombre": "Viral Short",
        "descripcion": ("Ritmo rápido con cortes cada 3 segundos, "
                        "tipografía bold de alta retención y zonas seguras "
                        "móviles respetadas. Para curiosidades y hooks "
                        "virales."),
        "format": "short",
        "formatos": ["vertical"],
        "pacing": "fast",          # canon del backend (fast/normal/slow)
        "ritmo": "Rápido (~2,5 s por plano · corte cada 3 s)",
        "broll": "cambio de plano cada 3 segundos, zoom punch en énfasis",
        "musica": "energética con subidas",
        "style": "auto",
        "voice": "es-ES-AlvaroNeural",
        "subtitle_style": "hormozi",
        "safe_zones": True,
        "cortes_seg": 3,
        "estructura": ["gancho de impacto (3 s)", "desarrollo escalonado",
                       "giro final", "cierre que invita a comentar"],
        "marca": {
            "nicho": "viral",
            "nombre_canal": "",
            "tono": "directo e intrigante",
            "idioma": "es",
            "voz_default": "es-ES-AlvaroNeural",
            "cierre": {
                "red": "TikTok",
                "cuenta": "",
                "frase": "Sígueme para más datos que no creerás",
            },
        },
    },
    {
        "id": "miniaturas",
        "icono": "🖼️",
        "nombre": "Miniaturas",
        "descripcion": ("Generación de miniaturas de YouTube (1280x720) y "
                        "covers verticales (768x1376) SIN video: portadas "
                        "listas para publicar o para reusar en tu editor."),
        "format": "short",
        "formatos": ["miniatura"],
        "pacing": "normal",        # canon del backend
        "ritmo": "Normal",
        "broll": "imagen principal de alto contraste con sujeto recortado",
        "musica": "",
        "style": "auto",
        "voice": "",
        "subtitle_style": "",
        "safe_zones": False,
        "solo_miniaturas": True,
        "miniatura": {"youtube": "1280x720", "cover": "768x1376"},
        "estructura": ["concepto visual", "texto de gancho (≤4 palabras)"],
        "marca": {
            "nicho": "miniaturas",
            "nombre_canal": "",
            "tono": "visual",
            "idioma": "es",
            "voz_default": "",
            "cierre": {},
        },
    },
]


def _seed() -> None:
    """Auto-siembra del catálogo (patrón niches.json) — sin tocar ediciones."""
    if PRESETS_PATH.is_file():
        return
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    PRESETS_PATH.write_text(
        json.dumps(BUILTIN_TEMPLATES, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def list_templates() -> list[dict]:
    """Catálogo completo (del JSON si existe; si no, los integrados)."""
    with _LOCK:
        try:
            _seed()
            return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — el catálogo nunca tumba la API
            return [dict(t) for t in BUILTIN_TEMPLATES]


def get_template(template_id: str) -> dict | None:
    """Una plantilla por id (None si no existe)."""
    tid = str(template_id or "").strip()
    if not tid:
        return None
    return next((t for t in list_templates() if t.get("id") == tid), None)


def marca_from_template(tpl: dict, project: dict | None = None) -> dict:
    """marca.json de la plantilla (con nicho del proyecto como precedencia)."""
    from pipeline.project_workspace import marca_from_template as _mft
    return _mft(tpl, project)

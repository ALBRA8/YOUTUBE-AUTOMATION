"""
YOUTUBE AUTOMATION v2.0 — Paso 5: Subtítulos estilo TikTok / Hormozi
Genera un archivo ASS con palabras gigantes que "poppéan" de 1-3 en 1-3,
color amarillo con borde negro grueso, centrado (estilo Hormozi),
con resaltado de palabra activa. Los tiempos vienen de Whisper.
"""
from __future__ import annotations

from pipeline.typography import find_font, generate_shorts_sub_style

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hormozi,{font},{size},&H0033FFFF,&H00FFFFFF,&H00000000,&H7F000000,-1,0,0,0,100,100,1,0,1,{outline},{shadow},5,60,60,{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# INT-021: cabecera del estilo 'Shorts' — la línea Style la genera
# pipeline.typography (fuente embarcada + contraste dinámico verificado
# WCAG >= 4.5:1; matching libass probado empíricamente, ver INT-021 §3).
SHORTS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style_line}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# Estilos de subtítulo disponibles (INT-021 + INT-041)
SUB_STYLES = {
    "hormozi": {"font": "Impact", "size_ratio": 0.062, "outline": 9, "shadow": 4,
                "active_color": "&H0000FFFF&", "chunks": 3},       # amarillo
    "tiktok":  {"font": "Arial Black", "size_ratio": 0.055, "outline": 7, "shadow": 2,
                "active_color": "&H00FFFFFF&", "chunks": 1},        # blanco clásico
    "karaoke": {"font": "Montserrat", "size_ratio": 0.06, "outline": 8, "shadow": 3,
                "active_color": "&H0000FF7F&", "chunks": 1},        # verde lima
    # INT-021: estilo Shorts — Fontname/colores reales los decide
    # pipeline.typography (fuente embarcada + contraste dinámico); esta
    # entrada fija el ratio tipográfico y la agrupación del pop.
    "shorts":  {"font": "Montserrat ExtraBold", "size_ratio": 0.037,
                "outline": 4, "shadow": 2,
                "active_color": "&H00FFFFFF&", "chunks": 3},
    # INT-041: Presets visuales inspirados en Shorts Virales
    "mrbeast": {"font": "Montserrat ExtraBold", "size_ratio": 0.065, "outline": 10, "shadow": 3,
                "active_color": "&H00FFAA00&", "chunks": 2,
                "primary_color": "&H00FFFFFF&", "secondary_color": "&H00FFAA00&",
                "outline_color": "&H00000000&", "back_color": "&H80000000&",
                "border_style": 1, "alignment": 5, "pop_scale": 125, "uppercase": True},
    "neon":    {"font": "Montserrat ExtraBold", "size_ratio": 0.058, "outline": 6, "shadow": 4,
                "active_color": "&H00FFFF00&", "chunks": 2,
                "primary_color": "&H0000FF7F&", "secondary_color": "&H00FFFF00&",
                "outline_color": "&H00221100&", "back_color": "&H90000000&",
                "border_style": 1, "alignment": 5, "pop_scale": 120, "uppercase": True},
    "boxed":   {"font": "Montserrat ExtraBold", "size_ratio": 0.045, "outline": 4, "shadow": 0,
                "active_color": "&H0000FFFF&", "chunks": 3,
                "primary_color": "&H00FFFFFF&", "secondary_color": "&H0000FFFF&",
                "outline_color": "&H00000000&", "back_color": "&HAA000000&",
                "border_style": 3, "alignment": 5, "pop_scale": 112, "uppercase": False},
    "minimal": {"font": "Montserrat", "size_ratio": 0.038, "outline": 3, "shadow": 1,
                "active_color": "&H00FFFFFF&", "chunks": 4,
                "primary_color": "&H00F0F0F0&", "secondary_color": "&H00FFFFFF&",
                "outline_color": "&H00000000&", "back_color": "&H40000000&",
                "border_style": 1, "alignment": 2, "pop_scale": 105, "uppercase": False},
}

SUBTITLE_PRESETS_CATALOG = [
    {
        "id": "shorts",
        "name": "Shorts Dinámico",
        "emoji": "📱",
        "description": "Montserrat ExtraBold con contraste inteligente WCAG >= 4.5:1. Estándar recomendado para Shorts y Reels.",
        "font": "Montserrat ExtraBold",
        "chunks": 3,
        "preview_css": "font-family:'Montserrat ExtraBold', sans-serif; font-weight:800; color:#FFFFFF; -webkit-text-stroke:2.5px #000; text-shadow:2px 2px 0 #000;",
        "sample_text": "ESTO CAMBIA TODO",
        "tags": ["Recomendado", "Shorts", "Contraste Dinámico", "Viral"],
    },
    {
        "id": "hormozi",
        "name": "Hormozi Gold",
        "emoji": "⚡",
        "description": "El estilo de Alex Hormozi: tipografía masiva en amarillo dorado con borde ultra-grueso y pop enérgico.",
        "font": "Impact",
        "chunks": 3,
        "preview_css": "font-family:Impact, sans-serif; font-weight:900; color:#FFFF00; -webkit-text-stroke:3px #000; text-shadow:2px 2px 0 #000; text-transform:uppercase;",
        "sample_text": "HAZ ESTO AHORA",
        "tags": ["Viral", "Hormozi", "Amarillo", "Enérgico"],
    },
    {
        "id": "mrbeast",
        "name": "MrBeast Bold",
        "emoji": "🔴",
        "description": "Letras gigantes en mayúsculas con máximo pop visual (+25%), outline negro pesado y alta legibilidad.",
        "font": "Montserrat ExtraBold",
        "chunks": 2,
        "preview_css": "font-family:'Montserrat ExtraBold', Impact, sans-serif; font-weight:900; color:#FFFFFF; -webkit-text-stroke:3.5px #000; text-shadow:3px 3px 0 #000; text-transform:uppercase;",
        "sample_text": "EL RETO FINAL",
        "tags": ["MrBeast", "Mayúsculas", "Ultra Grande", "Viral"],
    },
    {
        "id": "neon",
        "name": "Neon Cyberpunk",
        "emoji": "🟢",
        "description": "Verde esmeralda y cian eléctrico con resplandor glow. Diseñado para gaming, tecnología, IA y misterio.",
        "font": "Montserrat ExtraBold",
        "chunks": 2,
        "preview_css": "font-family:'Montserrat ExtraBold', sans-serif; font-weight:800; color:#00FF7F; -webkit-text-stroke:2px #112200; text-shadow:0 0 10px #00FF7F, 0 0 18px #00FFFF;",
        "sample_text": "FUTURO CERCANO",
        "tags": ["Cyberpunk", "Neón", "Gaming", "Tecnología"],
    },
    {
        "id": "tiktok",
        "name": "TikTok Fast",
        "emoji": "💬",
        "description": "1 palabra por bloque en blanco puro sobre fondo de alto contraste. Para ritmos rápidos y locuciones aceleradas.",
        "font": "Arial Black",
        "chunks": 1,
        "preview_css": "font-family:'Arial Black', sans-serif; font-weight:900; color:#FFFFFF; -webkit-text-stroke:2.5px #000; text-shadow:2px 2px 0 #000;",
        "sample_text": "INCREÍBLE",
        "tags": ["TikTok", "1 Palabra", "Rápido"],
    },
    {
        "id": "boxed",
        "name": "Boxed UGC",
        "emoji": "📦",
        "description": "Caja rectangular oscura detrás del texto con tipografía blanca nítida. El estilo favorito para anuncios UGC y reviews.",
        "font": "Montserrat ExtraBold",
        "chunks": 3,
        "preview_css": "font-family:'Montserrat ExtraBold', sans-serif; font-weight:800; color:#FFFFFF; background:rgba(0,0,0,0.82); padding:4px 10px; border-radius:6px; box-shadow:0 4px 12px rgba(0,0,0,0.5);",
        "sample_text": "PROBANDO ESTO",
        "tags": ["UGC", "Caja", "Anuncios", "Limpio"],
    },
    {
        "id": "minimal",
        "name": "Cinema Minimal",
        "emoji": "🎬",
        "description": "Elegancia pura para documentales de historia, crímenes y filosofía. Centrado inferior con borde suave y espaciado de cine.",
        "font": "Montserrat",
        "chunks": 4,
        "preview_css": "font-family:'Montserrat', sans-serif; font-weight:600; color:#F0F0F0; -webkit-text-stroke:1px #000; text-shadow:1px 1px 3px rgba(0,0,0,0.9); letter-spacing:1px;",
        "sample_text": "En el siglo XIX...",
        "tags": ["Cine", "Documental", "Elegante", "Historia"],
    },
    {
        "id": "karaoke",
        "name": "Karaoke Pop",
        "emoji": "🎤",
        "description": "Palabras en verde lima que se iluminan al compás exacto de la narración de audio.",
        "font": "Montserrat",
        "chunks": 1,
        "preview_css": "font-family:'Montserrat', sans-serif; font-weight:800; color:#00FF7F; -webkit-text-stroke:2px #000; text-shadow:2px 2px 0 #000;",
        "sample_text": "PALABRA A PALABRA",
        "tags": ["Karaoke", "Sincronizado", "Musical"],
    },
]


# Pausa (s) entre palabras que rompe el bloque de subtítulo (patrón
# AI-Content-Automation-Engine: "bloques ≤3 palabras / pausa >0.4s")
MAX_GAP_S = 0.4


def _ts(seconds: float) -> str:
    s = max(seconds, 0)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:d}:{m:02d}:{sec:05.2f}"


def group_words(words: list[dict], chunk: int) -> list[list[dict]]:
    """Agrupa palabras en bloques (Hormozi usa bloques de ~3 palabras)."""
    return [words[i:i + chunk] for i in range(0, len(words), chunk)] if words else []


def group_words_smart(words: list[dict], chunk: int = 3,
                      max_gap: float = MAX_GAP_S) -> list[list[dict]]:
    """Agrupación INTELIGENTE (patrón AI-Content-Automation-Engine):
    corta el bloque al llegar a `chunk` palabras PERO también cuando hay una
    pausa natural > `max_gap` s entre dos palabras consecutivas. Así un
    bloque nunca atraviesa una pausa de respiración y el subtítulo “habla”
    al ritmo real de la locución (mejor retención en shorts)."""
    if not words:
        return []
    groups: list[list[dict]] = []
    cur: list[dict] = [words[0]]
    for prev, nxt in zip(words, words[1:]):
        gap = float(nxt.get("start", 0)) - float(prev.get("end", 0))
        if len(cur) >= chunk or gap > max_gap:
            groups.append(cur)
            cur = [nxt]
        else:
            cur.append(nxt)
    groups.append(cur)
    return groups


def build_ass(words: list[dict], w: int, h: int, style: str = "hormozi",
              avg_brightness: float | None = None) -> str:
    """INT-021 + INT-041: Soporte de presets de subtítulos de alta retención.
    Mantiene compatibilidad estricta con el contrato legacy 'hormozi' y el estilo 'shorts'."""
    cfg = (SUB_STYLES["shorts"] if style == "shorts"
           else SUB_STYLES.get(style, SUB_STYLES["hormozi"]))
    font_size = max(int(h * cfg["size_ratio"]), 28)
    if style == "shorts":
        style_name = "Shorts"
        header = SHORTS_HEADER.format(
            w=w, h=h,
            style_line=generate_shorts_sub_style(
                font_path=find_font(), w=w, h=h,
                avg_brightness=0.5 if avg_brightness is None
                else avg_brightness))
    elif style == "hormozi":
        style_name = "Hormozi"
        marginv = int(h * 0.30) if h > w else int(h * 0.22)  # más arriba del centro
        header = ASS_HEADER.format(w=w, h=h, font=cfg["font"], size=font_size,
                                   outline=cfg["outline"], shadow=cfg["shadow"],
                                   marginv=marginv)
    else:
        # Estilos modernos de INT-041 (mrbeast, neon, minimal, boxed, etc.)
        style_name = style.capitalize()
        border_style = cfg.get("border_style", 1)
        alignment = cfg.get("alignment", 5)
        prim = cfg.get("primary_color", "&H00FFFFFF&").replace("&", "")
        sec = cfg.get("secondary_color", "&H00FFFFFF&").replace("&", "")
        outl_col = cfg.get("outline_color", "&H00000000&").replace("&", "")
        back_col = cfg.get("back_color", "&H7F000000&").replace("&", "")
        marginv = 80 if alignment == 2 else (int(h * 0.30) if h > w else int(h * 0.22))
        style_line = (
            f"Style: {style_name},{cfg['font']},{font_size},"
            f"&{prim},&{sec},&{outl_col},&{back_col},"
            f"-1,0,0,0,100,100,1,0,{border_style},{cfg['outline']},{cfg['shadow']},"
            f"{alignment},60,60,{marginv},1"
        )
        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style_line}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []
    usable = max(w - 120, 300)  # ancho útil (margins L/R de 60px)
    pop_max = cfg.get("pop_scale", 118)
    for group in group_words_smart(words, cfg["chunks"]):
        start = group[0]["start"]
        end = group[-1]["end"]
        raw_text = " ".join(x["word"] for x in group)
        text = raw_text.upper() if cfg.get("uppercase") else raw_text
        longest = max(len(x["word"]) for x in group)
        est = 0.53 * font_size * longest  # ancho estimado de esa palabra
        settle = min(100, max(55, int(100 * usable / est))) if est > usable else 100
        fx = (r"{\fscx%d\fscy%d\t(0,120,\fscx%d\fscy%d)}" % (pop_max, pop_max, settle, settle)
              if settle < 100 else r"{\fscx%d\fscy%d\t(0,120,\fscx100\fscy100)}" % (pop_max, pop_max))
        events.append(
            f"Dialogue: 0,{_ts(start)},{_ts(end)},{style_name},,0,0,0,,{fx}{text}")

    return header + "\n".join(events) + "\n"


def words_to_srt(words: list[dict], chunk: int = 3) -> str:
    """SRT alternativo (por si el usuario quiere editar fuera). Usa la
    misma agrupación inteligente con corte por pausas que el ASS."""
    lines: list[str] = []
    for n, group in enumerate(group_words_smart(words, chunk), 1):
        start, end = group[0]["start"], group[-1]["end"]
        text = " ".join(x["word"] for x in group)
        lines += [str(n), f"{_ts(start).replace('.', ',')} --> "
                          f"{_ts(end).replace('.', ',')}", text, ""]
    return "\n".join(lines)

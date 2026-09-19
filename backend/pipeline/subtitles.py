"""
YOUTUBE AUTOMATION v2.0 — Paso 5: Subtítulos estilo TikTok / Hormozi
Genera un archivo ASS con palabras gigantes que "poppéan" de 1-3 en 1-3,
color amarillo con borde negro grueso, centrado (estilo Hormozi),
con resaltado de palabra activa. Los tiempos vienen de Whisper.
"""
from __future__ import annotations

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hormozi,{font},{size},&H0033FFFF,&H00FFFFFF,&H00000000,&H7F000000,-1,0,0,0,100,100,1,0,1,{outline},{shadow},5,60,60,{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# Estilos de subtítulo disponibles
SUB_STYLES = {
    "hormozi": {"font": "Impact", "size_ratio": 0.062, "outline": 9, "shadow": 4,
                "active_color": "&H0000FFFF&", "chunks": 3},       # amarillo
    "tiktok":  {"font": "Arial Black", "size_ratio": 0.055, "outline": 7, "shadow": 2,
                "active_color": "&H00FFFFFF&", "chunks": 1},        # blanco clásico
    "karaoke": {"font": "Montserrat", "size_ratio": 0.06, "outline": 8, "shadow": 3,
                "active_color": "&H0000FF7F&", "chunks": 1},        # verde lima
}


def _ts(seconds: float) -> str:
    s = max(seconds, 0)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:d}:{m:02d}:{sec:05.2f}"


def group_words(words: list[dict], chunk: int) -> list[list[dict]]:
    """Agrupa palabras en bloques (Hormozi usa bloques de ~3 palabras)."""
    return [words[i:i + chunk] for i in range(0, len(words), chunk)] if words else []


def build_ass(words: list[dict], w: int, h: int, style: str = "hormozi") -> str:
    cfg = SUB_STYLES.get(style, SUB_STYLES["hormozi"])
    font_size = max(int(h * cfg["size_ratio"]), 28)
    marginv = int(h * 0.30) if h > w else int(h * 0.22)  # más arriba del centro

    header = ASS_HEADER.format(w=w, h=h, font=cfg["font"], size=font_size,
                               outline=cfg["outline"], shadow=cfg["shadow"],
                               marginv=marginv)

    events: list[str] = []
    for group in group_words(words, cfg["chunks"]):
        start = group[0]["start"]
        end = group[-1]["end"]
        text = " ".join(x["word"] for x in group)
        # pop: escala 118→100 en los primeros 120ms
        fx = r"{\fscx118\fscy118\t(0,120,\fscx100\fscy100)}"
        events.append(
            f"Dialogue: 0,{_ts(start)},{_ts(end)},Hormozi,,0,0,0,,{fx}{text}")

    return header + "\n".join(events) + "\n"


def words_to_srt(words: list[dict], chunk: int = 6) -> str:
    """SRT alternativo (por si el usuario quiere editar fuera)."""
    lines: list[str] = []
    for n, group in enumerate(group_words(words, chunk), 1):
        start, end = group[0]["start"], group[-1]["end"]
        text = " ".join(x["word"] for x in group)
        lines += [str(n), f"{_ts(start).replace('.', ',')} --> "
                          f"{_ts(end).replace('.', ',')}", text, ""]
    return "\n".join(lines)

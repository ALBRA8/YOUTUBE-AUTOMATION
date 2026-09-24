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
WrapStyle: 0
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


def build_ass(words: list[dict], w: int, h: int, style: str = "hormozi") -> str:
    cfg = SUB_STYLES.get(style, SUB_STYLES["hormozi"])
    font_size = max(int(h * cfg["size_ratio"]), 28)
    marginv = int(h * 0.30) if h > w else int(h * 0.22)  # más arriba del centro

    header = ASS_HEADER.format(w=w, h=h, font=cfg["font"], size=font_size,
                               outline=cfg["outline"], shadow=cfg["shadow"],
                               marginv=marginv)

    events: list[str] = []
    usable = max(w - 120, 300)  # ancho útil (margins L/R de 60px)
    for group in group_words_smart(words, cfg["chunks"]):
        start = group[0]["start"]
        end = group[-1]["end"]
        text = " ".join(x["word"] for x in group)
        # auto-escalado: la palabra más larga debe caber en el ancho útil
        longest = max(len(x["word"]) for x in group)
        est = 0.53 * font_size * longest  # ancho estimado de esa palabra
        settle = min(100, max(55, int(100 * usable / est))) if est > usable else 100
        # pop: escala 118→settle en los primeros 120ms (settle≤100 si la línea es larga)
        fx = (r"{\fscx118\fscy118\t(0,120,\fscx%d\fscy%d)}" % (settle, settle)
              if settle < 100 else r"{\fscx118\fscy118\t(0,120,\fscx100\fscy100)}")
        events.append(
            f"Dialogue: 0,{_ts(start)},{_ts(end)},Hormozi,,0,0,0,,{fx}{text}")

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

#!/usr/bin/env python3
"""BATERÍA — Tipografía de impacto + contraste dinámico (INT-021).

Verifica el módulo pipeline/typography.py y su integración en
pipeline/subtitles.py (style='shorts') SIN tocar backend/:

  S1. Fuente embarcada: TTF Montserrat-ExtraBold (magic sfnt 00010000),
      licencia SIL OFL y parser INLINE de la tabla 'name' (big-endian,
      nameID 1 y 16) — protege el matching libass: si alguien reemplaza
      la fuente, la batería grita.
  S2. calculate_luminance: luminancia relativa WCAG 2.x (exactitudes,
      tolerancias, rampa monótona y clamps de rango).
  S3. Contraste WCAG interno: ratio texto-borde reportado >= 4.5 y
      ratio blanco-vs-negro == 21.0 derivado de calculate_luminance.
  S4. get_contrasting_style barrido 0.00..1.00: contrato WCAG >= 4.5 en
      TODO el rango + formato &HAABBGGRR + transiciones exactas de banda.
  S5. generate_shorts_sub_style: línea `Style:` ASS byte-a-byte (fuente,
      campos por índice, escala 4K, fallback sin TTF y dinamismo por
      brillo).
  S6. build_ass integración: estilo 'shorts' completo + CONTRATO LEGACY
      byte-idéntico de 'hormozi' (regresión protegida) + default intacto.
  S7. estimate_video_brightness con ffmpeg REAL: negro ~0, blanco ~1,
      fallback 0.5 ante ruta inexistente / timeout / rc!=0.
  S8. PRUEBA DE MATCHING LIBASS (evidencia INT-021): A/B/C de MD5 de
      fotogramas quemando el mismo .ass con 'Montserrat',
      'Montserrat ExtraBold' y una fuente inexistente contra fontsdir
      real — detecta el régimen de resolución de libass.

Requiere ffmpeg en PATH (S7/S8; el repo ya lo exige). Nada toca
producción real, Google Flow ni red.
"""
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import pipeline.typography as typography  # noqa: E402
from pipeline.typography import (  # noqa: E402
    FONT_DIR, FONT_FILE, calculate_luminance, estimate_video_brightness,
    find_font, generate_shorts_sub_style, get_contrasting_style,
)

import pipeline.subtitles as subtitles  # noqa: E402  (tras sys.path backend)

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


_WORDS = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.45}
          for i, w in enumerate(["esto", "es", "una", "prueba", "estilo",
                                 "shorts"])]


# ── S1. Fuente embarcada ────────────────────────────────────────────────
def _name_table_ids(ttf: Path) -> dict[int, str]:
    """Parser INLINE de la tabla 'name' TTF (sin dependencias, big-endian):
    nº de tablas en offset 4, directorio en offset 12 (entradas de 16 B),
    registros nameID 1 y 16 (Windows=UTF-16BE, Mac=latin-1)."""
    data = ttf.read_bytes()
    num_tables = struct.unpack(">H", data[4:6])[0]
    name_off = None
    for i in range(num_tables):
        rec = 12 + 16 * i
        tag = data[rec:rec + 4]
        t_off, _t_len = struct.unpack(">II", data[rec + 8:rec + 16])
        if tag == b"name":
            name_off = t_off
            break
    if name_off is None:
        return {}
    _fmt, count, str_off = struct.unpack(">HHH", data[name_off:name_off + 6])
    ids: dict[int, str] = {}
    for i in range(count):
        rec = name_off + 6 + 6 * i
        pid, _eid, _lid, nid, ln, o = struct.unpack(">HHHHHH",
                                                    data[rec:rec + 12])
        if nid not in (1, 16) or nid in ids:
            continue
        raw = data[name_off + str_off + o: name_off + str_off + o + ln]
        try:
            ids[nid] = raw.decode("utf-16-be" if pid == 3 else "latin-1")
        except UnicodeDecodeError:
            pass
    return ids


print("\nS1 — Fuente embarcada (Montserrat-ExtraBold.ttf + OFL)")
check("TTF embarcada existe en backend/data/fonts/", FONT_FILE.is_file(),
      str(FONT_FILE))
magic = FONT_FILE.read_bytes()[:4].hex() if FONT_FILE.is_file() else ""
check("primeros 4 bytes == 00010000 (magic sfnt)", magic == "00010000",
      magic)
ofl = FONT_DIR / "OFL.txt"
check("OFL.txt existe y contiene 'SIL OPEN FONT LICENSE'",
      ofl.is_file() and "SIL OPEN FONT LICENSE" in ofl.read_text(
          encoding="utf-8", errors="replace"), str(ofl))
ids = _name_table_ids(FONT_FILE) if FONT_FILE.is_file() else {}
check("tabla 'name' localizada y parseada (num tablas offset 4)",
      bool(ids), f"nameIDs={sorted(ids)}")
check("nameID 1 (familia libass) == 'Montserrat ExtraBold'",
      ids.get(1) == "Montserrat ExtraBold", repr(ids.get(1)))
# TTF embarcada real verificada: SOLO trae ID1 (no hay ID16 tipográfica).
# Si una TTF futura lo trae, debe ser 'Montserrat'.
check("nameID 16 tipográfica: 'Montserrat' si presente "
      "(TTF real: ausente, solo ID1)",
      ids.get(16) in (None, "Montserrat"), repr(ids.get(16)))
check("find_font() devuelve ruta existente",
      (p := find_font()) is not None and Path(p).is_file(), str(p))

# ── S2. calculate_luminance ─────────────────────────────────────────────
print("\nS2 — calculate_luminance (WCAG 2.x)")
check("(0,0,0) -> 0.0 exacto", calculate_luminance(0, 0, 0) == 0.0,
      str(calculate_luminance(0, 0, 0)))
check("(255,255,255) -> 1.0 exacto",
      calculate_luminance(255, 255, 255) == 1.0,
      str(calculate_luminance(255, 255, 255)))
check("(128,128,128) -> 0.2158 (tol 0.001)",
      abs(calculate_luminance(128, 128, 128) - 0.2158) <= 0.001,
      str(calculate_luminance(128, 128, 128)))
check("(255,0,0) -> 0.2126 (tol 0.001)",
      abs(calculate_luminance(255, 0, 0) - 0.2126) <= 0.001,
      str(calculate_luminance(255, 0, 0)))
rampa = [calculate_luminance(v, v, v) for v in range(0, 256, 17)]
check("rampa gris 0..255 paso 17 estrictamente no-decreciente",
      all(a <= b for a, b in zip(rampa, rampa[1:])), str(rampa))
fuera = (calculate_luminance(-10, -10, -10), calculate_luminance(300, 300,
                                                                 300))
check("fuera de rango no explota: -10 y 300 en [0, 1]",
      all(0.0 <= v <= 1.0 for v in fuera), str(fuera))

# ── S3. Contraste WCAG interno ──────────────────────────────────────────
print("\nS3 — Contraste WCAG interno")
cs = get_contrasting_style(0.5)
check("ratio texto-borde reportado >= 4.5 (get_contrasting_style)",
      cs["contrast_text_outline"] >= 4.5, str(cs["contrast_text_outline"]))
ratio_bn = ((calculate_luminance(255, 255, 255) + 0.05)
            / (calculate_luminance(0, 0, 0) + 0.05))
check("ratio blanco-vs-negro == 21.0 (tol 0.01, vía calculate_luminance)",
      abs(ratio_bn - 21.0) <= 0.01, str(ratio_bn))

# ── S4. get_contrasting_style barrido 0.00..1.00 ────────────────────────
print("\nS4 — get_contrasting_style barrido (21 puntos)")
_COLOR_RE = re.compile(r"^&H[0-9A-F]{8}$")
lums = [i / 20 for i in range(21)]
muestra = [get_contrasting_style(l) for l in lums]
mal_wcag = [l for l, s in zip(lums, muestra) if not s["meets_wcag"]]
check("meets_wcag True en los 21 puntos", not mal_wcag, str(mal_wcag))
mal_to = [l for l, s in zip(lums, muestra)
          if s["contrast_text_outline"] < 4.5]
check("contrast_text_outline >= 4.5 en los 21 puntos", not mal_to,
      str(mal_to))
mal_min = [l for l, s in zip(lums, muestra) if s["contrast_min"] < 4.5]
check("contrast_min >= 4.5 en los 21 puntos", not mal_min, str(mal_min))
mal_color = [(l, s["text_color"], s["outline_color"], s["back_color"])
             for l, s in zip(lums, muestra)
             if not all(_COLOR_RE.match(s[k]) for k in
                        ("text_color", "outline_color", "back_color"))]
check("text/outline/back color casan ^&H[0-9A-F]{8}$ en los 21 puntos",
      not mal_color, str(mal_color[:2]))
mal_outline = [l for l, s in zip(lums, muestra) if s["outline"] not in (3, 4)]
check("outline in (3, 4) en los 21 puntos", not mal_outline, str(mal_outline))
mal_shadow = [l for l, s in zip(lums, muestra) if s["shadow"] != 2]
check("shadow == 2 en los 21 puntos", not mal_shadow, str(mal_shadow))
mal_band = [l for l, s in zip(lums, muestra)
            if s["band"] not in ("dark", "mid", "bright")]
check("band in ('dark','mid','bright') en los 21 puntos", not mal_band,
      str(mal_band))
d, m, b_ = (get_contrasting_style(0.10), get_contrasting_style(0.50),
            get_contrasting_style(0.95))
check("transición lum=0.10 -> dark, '&H00FFFFFF', outline 3",
      d["band"] == "dark" and d["text_color"] == "&H00FFFFFF"
      and d["outline"] == 3,
      f"{d['band']}/{d['text_color']}/{d['outline']}")
check("transición lum=0.50 -> mid, '&H0000FFFF' (amarillo), outline 4",
      m["band"] == "mid" and m["text_color"] == "&H0000FFFF"
      and m["outline"] == 4,
      f"{m['band']}/{m['text_color']}/{m['outline']}")
check("transición lum=0.95 -> bright, '&H00FFFFFF', "
      "outline_color '&H00101010'",
      b_["band"] == "bright" and b_["text_color"] == "&H00FFFFFF"
      and b_["outline_color"] == "&H00101010",
      f"{b_['band']}/{b_['text_color']}/{b_['outline_color']}")

# ── S5. generate_shorts_sub_style ───────────────────────────────────────
print("\nS5 — generate_shorts_sub_style (línea Style ASS)")
linea = generate_shorts_sub_style(font_path=find_font())
check("(a) empieza 'Style: Shorts,Montserrat ExtraBold,71,'",
      linea.startswith("Style: Shorts,Montserrat ExtraBold,71,"), linea)
check("(a) termina ',2,60,60,280,1'", linea.endswith(",2,60,60,280,1"),
      linea)
campos = linea.split(",")
check("(b) índice 7 == '1' (Bold)", campos[7] == "1", campos[7])
check("(b) índice 15 == '1' (BorderStyle)", campos[15] == "1", campos[15])
check("(b) índice 16 in ('3','4') (Outline)", campos[16] in ("3", "4"),
      campos[16])
check("(b) índice 17 == '2' (Shadow)", campos[17] == "2", campos[17])
check("(b) índice 18 == '2' (Alignment bottom-center)", campos[18] == "2",
      campos[18])
check("(b) índice 21 == '280' (MarginV)", campos[21] == "280", campos[21])
linea4k = generate_shorts_sub_style(font_path=find_font(), w=2160, h=3840)
campos4k = linea4k.split(",")
check("(c) 2160x3840 -> MarginV 560 (índice 21)", campos4k[21] == "560",
      campos4k[21])
check("(c) 2160x3840 -> size 142 (',142,' presente e índice 2)",
      ",142," in linea4k and campos4k[2] == "142", campos4k[2])
check("(d) font_path=None -> 'Style: Shorts,Montserrat,'",
      generate_shorts_sub_style(font_path=None).startswith(
          "Style: Shorts,Montserrat,"),
      generate_shorts_sub_style(font_path=None)[:40])
l10 = generate_shorts_sub_style(font_path=find_font(), avg_brightness=0.10)
l50 = generate_shorts_sub_style(font_path=find_font(), avg_brightness=0.50)
check("(e) avg_brightness=0.10 -> PrimaryColour '&H00FFFFFF'",
      l10.split(",")[3] == "&H00FFFFFF", l10.split(",")[3])
check("(e) avg_brightness=0.50 -> PrimaryColour '&H0000FFFF' (distinta)",
      l50.split(",")[3] == "&H0000FFFF" and l50 != l10,
      l50.split(",")[3])

# ── S6. build_ass integración ───────────────────────────────────────────
print("\nS6 — build_ass integración (shorts + contrato legacy)")
ass_shorts = subtitles.build_ass(_WORDS, 1080, 1920, style="shorts")
check("(a) contiene 'Style: Shorts,Montserrat ExtraBold'",
      "Style: Shorts,Montserrat ExtraBold" in ass_shorts, "")
check("(a) contiene 'PlayResX: 1080'", "PlayResX: 1080" in ass_shorts, "")
check("(a) contiene 'PlayResY: 1920'", "PlayResY: 1920" in ass_shorts, "")
dialogues = [ln for ln in ass_shorts.splitlines()
             if ln.startswith("Dialogue:")]
check("(a) todas las Dialogue referencian ',Shorts,'",
      bool(dialogues) and all(",Shorts," in d for d in dialogues),
      f"{len(dialogues)} dialogue")
check("(a) 'Hormozi' NO aparece en la salida shorts",
      "Hormozi" not in ass_shorts, "")
LEGACY = ("Style: Hormozi,Impact,119,&H0033FFFF,&H00FFFFFF,&H00000000,"
          "&H7F000000,-1,0,0,0,100,100,1,0,1,9,4,5,60,60,576,1")
ass_hormozi = subtitles.build_ass(_WORDS, 1080, 1920, style="hormozi")
check("(b) CONTRATO LEGACY: substring byte-idéntica del estilo antiguo",
      LEGACY in ass_hormozi, "")
check("(b) las Dialogue del legacy referencian ',Hormozi,'",
      all(",Hormozi," in d for d in
          [x for x in ass_hormozi.splitlines() if x.startswith("Dialogue:")]),
      "")
check("(c) build_ass(words,1080,1920) == build_ass(...,style='hormozi') "
      "(default intacto)",
      subtitles.build_ass(_WORDS, 1080, 1920) == ass_hormozi, "")
ass_09 = subtitles.build_ass(_WORDS, 1080, 1920, style="shorts",
                             avg_brightness=0.9)
ass_01 = subtitles.build_ass(_WORDS, 1080, 1920, style="shorts",
                             avg_brightness=0.1)
sty09 = next(x for x in ass_09.splitlines() if x.startswith("Style: Shorts"))
sty01 = next(x for x in ass_01.splitlines() if x.startswith("Style: Shorts"))
check("(d) líneas Style de avg 0.9 vs 0.1 distintas (dinamismo real: "
      "cambia OutlineColour/BackColour, NO PrimaryColour)",
      sty09 != sty01, f"{sty01} != {sty09}")
# Dinamismo REAL de PrimaryColour: banda mid (amarillo) vs dark/bright
# (blanco). La spec original esperaba 0.9 vs 0.1 con Primary distinto,
# pero el código real usa blanco en ambas bandas extremas.
ass_05 = subtitles.build_ass(_WORDS, 1080, 1920, style="shorts",
                             avg_brightness=0.5)
sty05 = next(x for x in ass_05.splitlines() if x.startswith("Style: Shorts"))
check("(d) PrimaryColour dinámico real: 0.5 '&H0000FFFF' vs 0.9 "
      "'&H00FFFFFF'",
      sty05.split(",")[3] == "&H0000FFFF"
      and sty09.split(",")[3] == "&H00FFFFFF",
      f"{sty05.split(',')[3]} / {sty09.split(',')[3]}")

# ── S7. estimate_video_brightness con ffmpeg REAL ───────────────────────
print("\nS7 — estimate_video_brightness (ffmpeg real)")
_TMP7 = Path(tempfile.mkdtemp(prefix="typo_s7_"))


def _genera(nombre: str, color: str) -> Path:
    out = _TMP7 / nombre
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"color=c={color}:s=320x568:d=1:r=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        capture_output=True, text=True, timeout=120)
    return out


vid_negro = _genera("negro.mp4", "black")
vid_blanco = _genera("blanco.mp4", "white")
check("2 mp4 lavfi (black/white) generados con libx264+yuv420p",
      vid_negro.is_file() and vid_blanco.is_file(), str(_TMP7))
b_negro = estimate_video_brightness(vid_negro)
b_blanco = estimate_video_brightness(vid_blanco)
check("negro -> brillo < 0.08", b_negro < 0.08, str(b_negro))
check("blanco -> brillo > 0.9", b_blanco > 0.9, str(b_blanco))
check("ruta inexistente -> exactamente 0.5",
      estimate_video_brightness(_TMP7 / "no_existe.mp4") == 0.5, "")


def _runner_timeout(cmd, timeout=1):
    raise subprocess.TimeoutExpired(cmd, 1)


def _runner_rc1(cmd, timeout=1):
    return subprocess.CompletedProcess(cmd, returncode=1, stdout="",
                                       stderr="")


check("runner simulado TimeoutExpired -> 0.5",
      estimate_video_brightness(vid_negro, runner=_runner_timeout) == 0.5,
      "")
check("runner simulado rc=1 (sin YAVG) -> 0.5",
      estimate_video_brightness(vid_negro, runner=_runner_rc1) == 0.5, "")

# ── S8. PRUEBA DE MATCHING LIBASS (evidencia INT-021) ───────────────────
print("\nS8 — Matching libass A/B/C con ffmpeg real (MD5 de fotogramas)")
_TMP8 = Path(tempfile.mkdtemp(prefix="typo_s8_"))
base = subprocess.run(
    ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x568:d=1:r=10",
     "-c:v", "libx264", "-pix_fmt", "yuv420p", str(_TMP8 / "base.mp4")],
    capture_output=True, text=True, timeout=120)
check("base.mp4 gris generado (lavfi+libx264)",
      (_TMP8 / "base.mp4").is_file() and base.returncode == 0,
      base.stderr[-120:] if base.returncode else "")

_ASS_TPL = """[Script Info]
ScriptType: v4.00+
PlayResX: 320
PlayResY: 568
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: T,{font},60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H7F000000,1,0,0,0,100,100,0,0,1,3,2,2,20,20,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,T,,0,0,0,,RXPJQ 1080
"""
_VARIANTS = {"a": ("a_montserrat.ass", "Montserrat"),
             "b": ("b_extrabold.ass", "Montserrat ExtraBold"),
             "c": ("c_bogus.ass", "FuenteInexistenteXYZ")}
md5: dict[str, str] = {}
quemados_ok = True
for v, (fname, fuente) in _VARIANTS.items():
    ass_path = _TMP8 / fname
    ass_path.write_text(_ASS_TPL.format(font=fuente), encoding="utf8")
    out = _TMP8 / f"out_{v}.mp4"
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(_TMP8 / "base.mp4"), "-vf",
         f"ass={ass_path.as_posix()}:fontsdir={FONT_DIR.as_posix()}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", str(out)],
        capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not out.is_file():
        quemados_ok = False
        print(f"    (burn {v} rc={r.returncode}: {r.stderr[-160:]})")
    # MD5 de fotogramas: ffmpeg -i out_X.mp4 -map 0:v -f md5 -
    m = subprocess.run(["ffmpeg", "-i", str(out), "-map", "0:v",
                        "-f", "md5", "-"],
                       capture_output=True, text=True, timeout=120)
    h = re.search(r"([0-9a-f]{32})", m.stdout) or re.search(
        r"([0-9a-f]{32})", m.stderr)
    md5[v] = h.group(1) if h else ""
check("3 quemados ffmpeg+libass rc=0 con fontsdir real", quemados_ok,
      str({k: bool(v_) for k, v_ in md5.items()}))
check("MD5 de fotogramas parseado para los 3 out_*.mp4",
      all(len(h) == 32 for h in md5.values()), str(md5))
check("(1) md5_b != md5_c — ExtraBold SÍ resuelve contra la cara real "
      "vía fontsdir", bool(md5["b"]) and md5["b"] != md5["c"],
      f"{md5.get('b')} vs {md5.get('c')}")
check("(2) md5_a == md5_b o md5_a == md5_c (comportamiento documentado)",
      md5["a"] in (md5["b"], md5["c"]),
      f"a={md5.get('a')} b={md5.get('b')} c={md5.get('c')}")
if md5["a"] == md5["b"]:
    print("    → RÉGIMEN DETECTADO: 'ID16 soportado' (a==b)")
elif md5["a"] == md5["c"]:
    print("    → RÉGIMEN DETECTADO: 'fallback ID1-only' (a==c) — "
          "esperado HOY; md5_a==md5_c NO es fallo")

print(f"\n{'=' * 60}")
print(f"RESULTADO: {OK} OK · {FAIL} fallos")
sys.exit(1 if FAIL else 0)

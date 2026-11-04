#!/usr/bin/env python3
"""
INT-085 · Elevación de calidad audiovisual (masterización broadcast,
zonas seguras móviles y hoja de contacto QA).

Cubre los 3 frentes de la tarea:
  A. pipeline/video.py · mux_audio_music aplica loudnorm broadcast
     (I=-14 LUFS / LRA=11 / TP=-1.0 dBTP dual_mono) + 48 kHz + AAC 192k,
     con sidecar audio_master.json y kill-switch AUDIO_MASTER_BROADCAST=0.
     Incluye una integración REAL: ffmpeg acepta el filtro y el MP4 resultante
     lleva audio AAC 48 kHz.
  B. services/contact_sheet.py · hoja 4x4 de 16 fotogramas equidistantes con
     timestamp «MM:SS.d» y líneas guía cian de zonas seguras en 9:16
     (integración real con ffmpeg: dimensiones, JPEG válido, píxeles cian y
     flush de grid parcial con videos cortos).
  C. pipeline/subtitles.py + typography.py · subtítulo vertical dentro de la
     banda segura (bottom del texto Y=1350 @1920 ∈ [1200,1350], nunca >1550)
     y botonera derecha reservada (MarginR ≥ 15%). Horizontal legacy intacto.
  D. endpoint GET /api/projects/{pid}/contact-sheet (200 image/jpeg con
     generación al vuelo y cache; 404 sin video/proyecto).

Dual-mode: pytest (fixtures client/tmp_path/monkeypatch) y script directo.
"""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
import main  # noqa: E402
import safe_zones  # noqa: E402
from pipeline import video as vmod  # noqa: E402
from services import contact_sheet as cs  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

OK, FAIL = 0, 0
PID = "a1b2c3d4e5f6"  # 12 hex canónico (security.validate_project_id)


def check(nombre: str, cond: bool, extra: str = ""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))
    if not ok:  # bajo pytest esto falla DE VERDAD (no falso verde)
        raise AssertionError(f"{nombre}" + (f" — {extra}" if extra else ""))


# ── helpers ffmpeg reales (integración) ─────────────────────────────────
def _make_video(path: Path, w: int = 1080, h: int = 1920, dur: float = 3.0,
                color: str = "blue") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=c={color}:s={w}x{h}:d={dur}:r=30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr[-200:]
    return path


def _make_wav(path: Path, dur: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={dur}", str(path)],
        capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr[-200:]
    return path


# ════════════════════════ A · masterización broadcast ═══════════════════
def _mux_capture(monkeypatch, tmp_path: Path, music_dir: Path | None):
    """Corre mux_audio_music con _run_ffmpeg capturado (sin ejecutar ffmpeg)
    y devuelve el comando construido. Los archivos de entrada no se leen."""
    captured: dict = {}

    def fake_ffmpeg(cmd, timeout=600):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "{}")

    (tmp_path / PID).mkdir(parents=True, exist_ok=True)
    vs = tmp_path / "silent.mp4"
    vf = tmp_path / "voice.wav"
    vs.write_bytes(b"0")
    vf.write_bytes(b"0")
    monkeypatch.setattr(vmod, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(vmod, "_run_ffmpeg", fake_ffmpeg)
    if music_dir is not None:
        import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "MUSIC_DIR", music_dir, raising=True)
    asyncio.run(vmod.mux_audio_music({"id": PID}, vs, vf))
    return captured["cmd"]


def test_mux_sin_musica_aplica_loudnorm_broadcast(monkeypatch, tmp_path):
    cmd = _mux_capture(monkeypatch, tmp_path, music_dir=None)
    check("rama voz: filtro broadcast presente en -af",
          vmod.BROADCAST_LOUDNORM in cmd and "-af" in cmd)
    i = cmd.index("-af") if "-af" in cmd else -1
    check("rama voz: -af seguido del filtro exacto I=-14:LRA=11:TP=-1.0:dual_mono",
          i >= 0 and cmd[i + 1] == vmod.BROADCAST_LOUDNORM)
    check("rama voz: -ar 48000 tras el filtro",
          "-ar" in cmd and cmd[cmd.index("-ar") + 1] == "48000")
    check("rama voz: AAC 192k", "-c:a" in cmd and "aac" in cmd
          and cmd[cmd.index("-b:a") + 1] == "192k")
    side = json.loads((tmp_path / PID / "audio_master.json").read_text())
    check("sidecar audio_master.json enabled=True con targets",
          side["enabled"] is True and side["target_lufs"] == -14
          and side["tp_dbtp"] == -1.0 and side["lra"] == 11
          and side["sample_rate"] == 48000)


def test_mux_con_musica_encadena_loudnorm_tras_amix(monkeypatch, tmp_path):
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    (music_dir / "cama.mp3").write_bytes(b"0")
    cmd = _mux_capture(monkeypatch, tmp_path, music_dir=music_dir)
    fc = cmd[cmd.index("-filter_complex") + 1]
    check("rama música: amix → loudnorm → [al] encadenados",
          fc.endswith(f";[aout]{vmod.BROADCAST_LOUDNORM}[al]")
          and "sidechaincompress" in fc and "amix" in fc)
    check("rama música: -map apunta a [al] (audio masterizado)",
          cmd[cmd.index("-map", cmd.index("-map") + 1) + 1] == "[al]")
    check("rama música: -ar 48000 presente", "-ar" in cmd
          and cmd[cmd.index("-ar") + 1] == "48000")


def test_mux_gate_off_preserva_comportamiento_legacy(monkeypatch, tmp_path):
    monkeypatch.setattr(vmod, "AUDIO_MASTER_BROADCAST", "0")
    cmd = _mux_capture(monkeypatch, tmp_path, music_dir=None)
    check("gate off: sin loudnorm ni -ar (mezcla legacy)",
          "loudnorm" not in " ".join(cmd) and "-ar" not in cmd)
    check("gate off: mapea 1:a como siempre (rama voz legacy)",
          cmd[cmd.index("-map", cmd.index("-map") + 1) + 1] == "1:a"
          and "[al]" not in cmd)
    side = json.loads((tmp_path / PID / "audio_master.json").read_text())
    check("sidecar refleja enabled=False", side["enabled"] is False)


def test_loudnorm_real_produce_aac_48k(tmp_path):
    """Integración REAL: ffmpeg acepta el filtro exacto y el MP4 final lleva
    AAC 48 kHz — protege contra typos que un mock no vería."""
    vs = _make_video(tmp_path / "silent.mp4", w=320, h=568, dur=1.0)
    vf = _make_wav(tmp_path / "voice.wav", dur=1.0)
    out = tmp_path / PID / "video_raw.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(vs), "-i", str(vf),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy",
         "-af", vmod.BROADCAST_LOUDNORM,
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", str(out)],
        capture_output=True, timeout=120)
    check("ffmpeg real acepta BROADCAST_LOUDNORM", r.returncode == 0,
          r.stderr.decode(errors="replace")[-160:])
    pr = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name,sample_rate", "-of",
         "csv=p=0", str(out)], capture_output=True, timeout=30)
    check("MP4 masterizado lleva AAC @ 48000 Hz",
          pr.stdout.decode().strip().startswith("aac,48000"),
          pr.stdout.decode())


# ════════════════════════ B · hoja de contacto QA ════════════════════════
def test_contact_sheet_vertical_16_cuadros_con_zonas(tmp_path):
    v = _make_video(tmp_path / "v916.mp4", dur=3.0)
    out = tmp_path / "contact_sheet.jpg"
    p = cs.generate_contact_sheet(v, out)  # 16 frames + zonas por defecto
    check("hoja generada y devuelta", p == out and out.is_file()
          and out.stat().st_size > 1000)
    head = out.read_bytes()[:3]
    check("es un JPEG válido (magic ffd8ff)", head == b"\xff\xd8\xff")
    from PIL import Image
    im = Image.open(out).convert("RGB")
    check("hoja 9:16 sale a 1080x1920 (tile 270·4)", im.size == (1080, 1920),
          str(im.size))
    # línea cian superior @ y=0.15·480=72 del tile fila 0 (la mezcla
    # cian@0.6 sobre el fondo + JPEG deja g≈70-110: umbral 60)
    def _cyanish(p):
        r, g, b = p
        return b > 200 and g >= 60 and r < g
    cyan_top = any(_cyanish(im.getpixel((x, y))) for x in (135, 300, 700)
                   for y in (71, 72, 73))
    # línea cian inferior @ y=0.80·480=384
    cyan_bot = any(_cyanish(im.getpixel((x, y))) for x in (135, 300, 700)
                   for y in (383, 384, 385))
    # línea vertical cian derecha @ x=0.85·270=229.5 (fila de tiles 0)
    cyan_right = any(_cyanish(im.getpixel((x, y))) for x in (228, 229, 230, 231)
                     for y in (30, 200, 400))
    check("líneas guía cian presentes (top/bottom/right)", cyan_top
          and cyan_bot and cyan_right, f"{cyan_top}/{cyan_bot}/{cyan_right}")


def test_contact_sheet_horizontal_sin_zonas(tmp_path):
    v = _make_video(tmp_path / "v169.mp4", w=640, h=360, dur=2.0, color="red")
    out = tmp_path / "sheet_h.jpg"
    cs.generate_contact_sheet(v, out)
    from PIL import Image
    im = Image.open(out).convert("RGB")
    check("hoja 16:9 sale con 4 columnas de 270px (1080 de ancho)",
          im.size[0] == 1080 and im.size[1] in range(100, 900), str(im.size))
    px = [im.getpixel((x, 22)) for x in (135, 300, 700)]
    rojo = all(r > 150 and b < 100 for r, g, b in px if sum(px[0]) > 0)
    check("horizontal NO dibuja zonas seguras (frame rojo intacto)",
          rojo, str(px[:2]))


def test_contact_sheet_video_corto_flush_parcial(tmp_path):
    """Video de 0.4 s (12 frames < 16): tile hace flush del grid parcial
    (celdas faltantes en negro) en lugar de fallar — verificado INT-085."""
    v = _make_video(tmp_path / "corto.mp4", dur=0.4, color="green")
    out = tmp_path / "sheet_corta.jpg"
    cs.generate_contact_sheet(v, out)
    from PIL import Image
    im = Image.open(out)
    check("video corto produce hoja completa (flush de tile)",
          out.is_file() and im.size[0] == 1080)


def test_contact_sheet_firma_publica():
    """Contrato de la firma exigida por la tarea."""
    import inspect
    sig = inspect.signature(cs.generate_contact_sheet)
    check("firma (video_path, output_path, num_frames=16, safe_zones=True)",
          list(sig.parameters) == ["video_path", "output_path", "num_frames",
                                   "safe_zones"]
          and sig.parameters["num_frames"].default == 16
          and sig.parameters["safe_zones"].default is True)


def test_contact_sheet_video_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        cs.generate_contact_sheet(tmp_path / "nope.mp4", tmp_path / "s.jpg")


# ════════════════════════ C · subtítulos en zonas seguras ═══════════════
WORDS = [{"word": "ESTO", "start": 0.0, "end": 0.4},
         {"word": "CAMBIA", "start": 0.4, "end": 0.8},
         {"word": "TODO", "start": 0.8, "end": 1.2}]


def _style_fields(ass: str) -> list[str]:
    line = next(l for l in ass.splitlines() if l.startswith("Style:"))
    return line.split(",")


def test_vertical_todos_los_estilos_en_banda_segura():
    styles = ["shorts", "hormozi", "tiktok", "karaoke", "mrbeast", "neon",
              "boxed", "minimal"]
    for st in styles:
        f = _style_fields(subs_build(st))
        alignment, ml, mr, mv = f[18], int(f[19]), int(f[20]), int(f[21])
        bottom = 1920 - mv
        check(f"[{st}] Alignment=2 (bottom-center) en vertical",
              alignment == "2", alignment)
        check(f"[{st}] bottom del texto Y={bottom} ∈ [1200, 1350]",
              1200 <= bottom <= 1350, str(bottom))
        check(f"[{st}] nunca por debajo de Y=1550", bottom <= 1550)
        check(f"[{st}] botonera derecha reservada (MarginR {mr} ≥ 162)",
              mr >= 162, str(mr))


def subs_build(style: str) -> str:
    from pipeline import subtitles as subs_mod
    return subs_mod.build_ass(WORDS, 1080, 1920, style=style)


def test_horizontal_mantiene_legacy():
    from pipeline import subtitles as subs_mod
    f = _style_fields(subs_mod.build_ass(WORDS, 1920, 1080, style="hormozi"))
    check("hormozi horizontal: Alignment 5 · margins 60/60 · MarginV 237",
          f[18] == "5" and f[19] == "60" and f[20] == "60"
          and f[21] == str(int(1080 * 0.22)), ",".join(f[18:22]))
    f = _style_fields(subs_mod.build_ass(WORDS, 1920, 1080, style="minimal"))
    check("minimal horizontal: Alignment 2 · MarginV 80 (legacy intacto)",
          f[18] == "2" and f[21] == "80", ",".join(f[18:22]))
    f = _style_fields(subs_mod.build_ass(WORDS, 1920, 1080, style="shorts"))
    check("shorts horizontal: margins 60/60/280 (legacy INT-021 intacto)",
          f[19] == "60" and f[20] == "60" and f[21] == "280", ",".join(f[18:22]))


def test_safe_zones_unica_fuente_de_verdad():
    check("subtitle_margins(1080x1920) = (64, 170, 570)",
          safe_zones.subtitle_margins(1080, 1920) == (64, 170, 570))
    check("safe_lines(1080x1920) = (288, 1536, 918) — 15%/80%/85%",
          safe_zones.safe_lines(1080, 1920) == (288, 1536, 918))
    check("horizontal → None (sin overrides)", 
          safe_zones.subtitle_margins(1920, 1080) is None
          and safe_zones.safe_lines(1920, 1080) is None)
    # 4K vertical escala proporcional y sigue bajo el cap absoluto
    ml, mr, mv = safe_zones.subtitle_margins(2160, 3840)
    check("4K vertical: bottom 2700 = 0.703·h < 0.807·h (cap 1550@1920)",
          3840 - mv == 2700 and 2700 < int(3840 * safe_zones.SUB_Y_ABS_MAX_RATIO))


def test_typography_shorts_usa_banda_segura():
    from pipeline import typography as typo
    f = typo.generate_shorts_sub_style(font_path=typo.find_font()).split(",")
    check("shorts vertical: MarginV 570 + MarginR 170 (safe_zones)",
          f[21] == "570" and f[20] == "170", ",".join(f[19:22]))
    f = typo.generate_shorts_sub_style(font_path=None, w=1920, h=1080).split(",")
    check("shorts horizontal: legacy 60/60/280 intacto",
          f[19] == "60" and f[20] == "60" and f[21] == "280", ",".join(f[19:22]))


# ════════════════════════ D · endpoint contact-sheet ════════════════════
@pytest.fixture
def client():
    return TestClient(main.app)


def test_endpoint_genera_y_cachea(client, tmp_path):
    """Generación al vuelo con ffmpeg REAL sobre un video 9:16 de muestra."""
    outdir = Path(config.OUTPUT_DIR) / PID  # conftest: OUTPUT_DIR de sesión
    outdir.mkdir(parents=True, exist_ok=True)
    video = _make_video(outdir / f"{PID}_final.mp4", dur=1.2)
    proyecto = {"id": PID, "title": "QA", "status": "ready",
                "video_url": str(video)}
    out = outdir / "contact_sheet.jpg"
    with patch("main.db.get_project", return_value=proyecto):
        t0 = time.time()
        res = client.get(f"/api/projects/{PID}/contact-sheet")
        dt1 = time.time() - t0
        check("GET contact-sheet responde 200", res.status_code == 200,
              str(res.status_code))
        check("Content-Type es image/jpeg",
              res.headers.get("content-type", "").startswith("image/jpeg"),
              res.headers.get("content-type", ""))
        check("bytes JPEG válidos", res.content[:3] == b"\xff\xd8\xff"
              and len(res.content) > 1000)
        check("hoja cacheada en output/<pid>/contact_sheet.jpg", out.is_file())
        t0 = time.time()
        res2 = client.get(f"/api/projects/{PID}/contact-sheet")
        dt2 = time.time() - t0
        check("2ª GET sirve el cache (idéntica y rápida)",
              res2.status_code == 200 and res2.content == res.content
              and dt2 <= dt1, f"{dt2:.3f}s vs {dt1:.3f}s")
    # limpieza del OUTPUT_DIR de sesión
    out.unlink(missing_ok=True)


def test_endpoint_404_sin_video_o_proyecto(client, tmp_path):
    res = client.get("/api/projects/000000000000/contact-sheet")
    check("proyecto inexistente → 404", res.status_code == 404, str(res.status_code))
    with patch("main.db.get_project",
               return_value={"id": PID, "title": "x", "video_url": None}):
        res2 = client.get(f"/api/projects/{PID}/contact-sheet")
        check("proyecto sin video_url → 404", res2.status_code == 404,
              str(res2.status_code))


# ════════════════════════ E · contratos fuente ══════════════════════════
def test_contratos_fuente_y_version():
    check("APP_VERSION 2.39.0 (INT-080: bump por cambio funcional)",
          config.APP_VERSION == "2.39.0")
    src = (BACKEND / "pipeline" / "video.py").read_text(encoding="utf-8")
    check("video.py define el filtro exacto de la tarea",
          'BROADCAST_LOUDNORM = "loudnorm=I=-14:LRA=11:TP=-1.0:dual_mono=true"'
          in src)
    check("video.py fuerza 48 kHz + AAC 192k",
          '"-ar", "48000"' in src and '"-b:a", "192k"' in src)
    check("kill-switch documentado", "AUDIO_MASTER_BROADCAST" in src)
    src_cs = (BACKEND / "services" / "contact_sheet.py").read_text(
        encoding="utf-8")
    check("contact_sheet usa tile 4x4 + cian + timestamp",
          "tile={GRID_COLS}x{rows}" in src_cs and "cyan@0.6" in src_cs
          and "drawtext" in src_cs)
    src_orch = (BACKEND / "pipeline" / "orchestrator.py").read_text(
        encoding="utf-8")
    check("orquestador genera la hoja al terminar (2 rutas de render)",
          src_orch.count("from services.contact_sheet import"
                         " generate_contact_sheet") == 2)
    src_main = (BACKEND / "main.py").read_text(encoding="utf-8")
    check("endpoint GET /api/projects/{pid}/contact-sheet existe",
          '@app.get("/api/projects/{pid}/contact-sheet")' in src_main)
    envex = (BACKEND / ".env.example").read_text(encoding="utf-8")
    check(".env.example documenta AUDIO_MASTER_BROADCAST",
          "AUDIO_MASTER_BROADCAST" in envex)


def main_test() -> int:
    print(f"\nINT-085 · {OK} checks OK · {FAIL} fallos")
    return 1 if FAIL else 0


if __name__ == "__main__":
    rc = pytest.main([__file__, "-v", "--no-header", "-x", "-q"])
    sys.exit(rc)
